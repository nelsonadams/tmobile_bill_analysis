import os

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
ADMIN = "admin@example.com"
VIEWER = "viewer@example.com"
GOOGLE = {"client_id": "test-client", "client_secret": "test-secret"}


def _seed_bills(path):
    from parser import init_schema, load_bill_data, rebuild_dimensions

    con = duckdb.connect(str(path))
    init_schema(con)
    line = dict(file_name="test.pdf", bill_date="2026-01-23", status="active", annotation="",
                equipment_charge=0.0, services_charge=0.0, onetime_charge=0.0)
    load_bill_data(con, dict(
        invoice=dict(file_name="test.pdf", account_number="000", bill_date="2026-01-23",
                     bill_month="2026-01", due_date="2026-02-15", total_due=100.0,
                     plans_total=90.0, equipment_total=0.0, services_total=10.0,
                     onetime_charges=0.0, total_savings=0.0, previous_balance=0.0,
                     voice_line_count=1, connected_device_count=0, wearable_count=0),
        lines=[dict(line, phone_number="Account", line_type="Account", plans_charge=40.0, line_total=40.0),
               dict(line, phone_number="(555) 555-0100", line_type="Voice", plans_charge=50.0, line_total=60.0)],
        savings=[], payments=[],
    ))
    rebuild_dimensions(con)
    con.close()


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TMOBILE_DATA_DIR", str(tmp_path))
    _seed_bills(tmp_path / "tmobile_bills.duckdb")
    return tmp_path


def _app(secrets, **state):
    at = AppTest.from_file(APP, default_timeout=30)
    for k, v in secrets.items():
        at.secrets[k] = v
    for k, v in state.items():
        at.session_state[k] = v
    return at


def _logged_in(email, page="Raw Data Explorer"):
    return dict(authenticated=True, user_email=email, display_name=email, _nav_page=page)


def _run_query(at, sql):
    at.text_area[0].set_value(sql).run()
    next(b for b in at.button if b.label == "Run Query").click().run()
    return [e.value for e in at.error]


def test_fails_closed_without_auth_config():
    at = _app({}).run()
    assert any("Authentication is not configured" in e.value for e in at.error)
    assert len(at.sidebar.button) == 0


def test_anonymous_opt_in_is_viewer_only():
    at = _app({"auth_settings": {"allow_anonymous": True}}, _nav_page="Raw Data Explorer").run()
    assert any("Admin access required" in e.value for e in at.error)
    assert "nav_Raw Data Explorer" not in [b.key for b in at.sidebar.button]


def test_viewer_cannot_open_raw_data_explorer(data_dir):
    con = duckdb.connect(str(data_dir / "auth.duckdb"))
    con.execute(
        "CREATE TABLE allowed_users (email VARCHAR PRIMARY KEY, name VARCHAR, "
        "role VARCHAR DEFAULT 'viewer', added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    con.execute("INSERT INTO allowed_users (email, name, role) VALUES (?, 'v', 'viewer')", [VIEWER])
    con.close()
    at = _app({"google_auth": GOOGLE}, **_logged_in(VIEWER)).run()
    assert any("Admin access required" in e.value for e in at.error)
    assert len(at.text_area) == 0


def test_removed_user_is_logged_out():
    at = _app({"google_auth": GOOGLE}, **_logged_in("gone@example.com", page="Overview")).run()
    assert "authenticated" not in at.session_state
    assert any("Sign in with Google" in m.value for m in at.markdown)


def test_admin_query_is_sandboxed():
    secrets = {"google_auth": GOOGLE, "auth_settings": {"admin_emails": [ADMIN]}}
    at = _app(secrets, **_logged_in(ADMIN)).run()
    assert at.session_state["user_role"] == "admin"
    assert any("Only SELECT queries are allowed" in e for e in _run_query(at, "DELETE FROM invoices"))
    assert any(
        "file system operations are disabled" in e
        for e in _run_query(at, "SELECT * FROM read_text('/etc/hostname')")
    )
    assert not _run_query(at, "SELECT COUNT(*) FROM invoices")
