import duckdb
import pytest

from sql_sandbox import UnsafeQueryError, run_readonly_query


@pytest.fixture
def src(tmp_path):
    con = duckdb.connect(str(tmp_path / "bills.duckdb"))
    con.execute("CREATE TABLE invoices AS SELECT 1 AS id, 100.0 AS total_due")
    con.execute("CREATE VIEW invoice_totals AS SELECT SUM(total_due) AS s FROM invoices")
    (tmp_path / "secret.txt").write_text("top-secret")
    yield con
    con.close()


def test_select_on_tables_and_views(src):
    assert run_readonly_query(src, "SELECT * FROM invoices")["total_due"].tolist() == [100.0]
    assert run_readonly_query(src, "SELECT s FROM invoice_totals")["s"].tolist() == [100.0]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM invoices",
        "DROP TABLE invoices",
        "UPDATE invoices SET total_due = 0",
        "ATTACH 'other.duckdb' AS o",
        "COPY invoices TO 'out.csv'",
        "SET enable_external_access = true",
        "SELECT 1; DELETE FROM invoices",
    ],
)
def test_rejects_non_select(src, sql):
    with pytest.raises(UnsafeQueryError):
        run_readonly_query(src, sql)
    assert src.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1


@pytest.mark.parametrize(
    "fn",
    ["read_text('{p}')", "read_csv('{p}')", "read_blob('{p}')", "'{p}'"],
)
def test_blocks_file_access(src, tmp_path, fn):
    sql = "SELECT * FROM " + fn.format(p=tmp_path / "secret.txt")
    with pytest.raises(duckdb.Error):
        run_readonly_query(src, sql)
