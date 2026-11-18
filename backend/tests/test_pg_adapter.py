"""Phase 8: the sqlite3-style SQL used by the trust/job tables translates to psycopg correctly."""
from app.db import PgRow, _pg_sql


def test_placeholders_and_percent_signs():
    assert _pg_sql("SELECT * FROM job WHERE id=? AND rel LIKE '%a?b%'") == \
        "SELECT * FROM job WHERE id=%s AND rel LIKE '%%a?b%%'"
    assert _pg_sql("UPDATE t SET x=? WHERE y=?") == "UPDATE t SET x=%s WHERE y=%s"
    assert _pg_sql("SELECT 100 % 7") == "SELECT 100 %% 7"


def test_row_reads_like_sqlite_row():
    Row = type("Row", (PgRow,), {"_cols": ("id", "status")})
    r = Row(("j1", "done"))
    assert r[0] == "j1" and r["status"] == "done" and dict(zip(r.keys(), r)) == {"id": "j1", "status": "done"}
    assert dict(r) == {"id": "j1", "status": "done"}          # dict(row) works as with sqlite3.Row
