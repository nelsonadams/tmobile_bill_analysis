"""Run ad-hoc read-only SQL against a disposable in-memory copy of the bills DB."""

import duckdb
import pandas as pd


class UnsafeQueryError(ValueError):
    pass


def _validate(sql: str) -> None:
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        raise UnsafeQueryError(f"Could not parse query: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeQueryError("Run exactly one statement at a time.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeQueryError("Only SELECT queries are allowed.")


def _build_sandbox(src: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    sandbox = duckdb.connect(
        ":memory:",
        config={"enable_external_access": False, "lock_configuration": True},
    )
    names = [
        r[0]
        for r in src.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = current_database() AND table_schema = 'main'"
        ).fetchall()
    ]
    for name in names:
        df = src.execute(f'SELECT * FROM "{name.replace(chr(34), chr(34) * 2)}"').fetchdf()
        sandbox.register("_sandbox_src", df)
        sandbox.execute(
            f'CREATE TABLE "{name.replace(chr(34), chr(34) * 2)}" AS SELECT * FROM _sandbox_src'
        )
        sandbox.unregister("_sandbox_src")
    return sandbox


def run_readonly_query(src: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Validate ``sql`` is a single SELECT and run it in an isolated sandbox.

    The sandbox is an in-memory copy of the source tables/views with file
    system access disabled, so queries cannot modify data, read server files,
    or ATTACH other databases.
    """
    _validate(sql)
    sandbox = _build_sandbox(src)
    try:
        return sandbox.execute(sql).fetchdf()
    finally:
        sandbox.close()
