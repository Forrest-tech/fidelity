# -*- coding: utf-8 -*-
"""数据访问层。
- kb.db：生产知识库，**只读**连接（绝不写，避免与解析/OCR 抢锁）。
- trust.db：质检与裁决库，**可写**。含 file_eval / file_trust / file_trust_log / job。
"""
import os, sqlite3, time
from . import config


def kb_ro(kb_path: str) -> sqlite3.Connection:
    """生产库只读连接（WAL 下可与后台写并发读）。"""
    con = sqlite3.connect("file:%s?mode=ro" % kb_path.replace("\\", "/"), uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    return con


# Phase 8: the trust/job tables can live in PostgreSQL. FIDELITY_TRUST_URL=postgresql://user:pw@host/db
# switches trust_rw() to psycopg behind a small adapter that keeps the sqlite3 calling style
# (`?` placeholders, rows readable by index and by name, execute/commit/close).
TRUST_URL = os.environ.get("FIDELITY_TRUST_URL", "")


def is_pg() -> bool:
    return TRUST_URL.startswith(("postgresql://", "postgres://"))


class PgRow(tuple):
    """Row readable as row[0], row["col"] and dict(row), like sqlite3.Row."""
    _cols: tuple = ()

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._cols.index(k))
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._cols)


def _pg_row_factory(cursor):
    cols = tuple(d.name for d in (cursor.description or ()))
    cls = type("Row", (PgRow,), {"_cols": cols})
    return lambda values: cls(values)


def _pg_sql(sql: str) -> str:
    """sqlite3 style -> psycopg style: '?' placeholders become %s; literal % is escaped."""
    out, quote = [], None
    for ch in sql:
        if quote:
            out.append("%%" if ch == "%" else ch)        # psycopg parses % even inside literals
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


class PgConnection:
    def __init__(self, url):
        import psycopg
        self._con = psycopg.connect(url, row_factory=_pg_row_factory)

    def execute(self, sql, params=()):
        return self._con.execute(_pg_sql(sql), tuple(params))

    def executemany(self, sql, seq):
        with self._con.cursor() as cur:
            cur.executemany(_pg_sql(sql), [tuple(p) for p in seq])

    def commit(self):
        self._con.commit()

    def rollback(self):
        self._con.rollback()

    def close(self):
        self._con.close()


def trust_rw():
    """trust.db 可写连接。WAL 只在 init_trust 设一次；这里只设 busy_timeout，
    避免多 worker 并发反复切 journal_mode 导致锁/只读降级。PostgreSQL when FIDELITY_TRUST_URL is set."""
    if is_pg():
        return PgConnection(TRUST_URL)
    con = sqlite3.connect(config.TRUST_DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    return con


def _transient_errors():
    errs = [sqlite3.OperationalError]
    if is_pg():
        import psycopg
        errs.append(psycopg.OperationalError)
    return tuple(errs)


def trust_write(fn, retries=5):
    """把一次写操作包成带重试的函数（吸收瞬时锁/只读降级）。"""
    import time as _t
    last = None
    for i in range(retries):
        try:
            return fn()
        except _transient_errors() as e:
            last = e
            _t.sleep(0.2 * (i + 1))
    raise last


_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_eval (
  rel TEXT PRIMARY KEY,
  auto_score REAL,            -- 0-100 综合转化率
  coverage REAL,              -- 内容覆盖率 0-1
  number_fidelity REAL,       -- 数字保真率 0-1
  engine_b TEXT,
  status TEXT,                -- evaluated / not_applicable / error
  fail_reasons TEXT,
  evaluated_at REAL
);
CREATE TABLE IF NOT EXISTS file_trust (
  rel TEXT PRIMARY KEY,
  trust_state TEXT,           -- 人工裁决: ok(一致) / diff_big(差异大) / rejected(不接受) / NULL(未审)
  reviewer TEXT,
  reviewed_at REAL,
  note TEXT,
  rev_no INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS file_trust_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rel TEXT, from_state TEXT, to_state TEXT,
  reviewer TEXT, ts REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS ingest_decision (
  rel TEXT PRIMARY KEY,
  decision TEXT,              -- include(入库) / exclude(不入库)
  reviewer TEXT,
  decided_at REAL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY,
  kind TEXT,                  -- parse / compare / ocr
  rel TEXT,
  status TEXT,                -- queued / running / done / error
  progress REAL DEFAULT 0,
  message TEXT,
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);
-- A distillation room: its own input, output and rules. Runs and per-file results hang off it.
CREATE TABLE IF NOT EXISTS room (
  id TEXT PRIMARY KEY,
  name TEXT,
  position INTEGER DEFAULT 0,
  source TEXT,                -- JSON {kind: dropbox|gdrive, link: ...}
  dest TEXT,                  -- JSON, same shape, empty for "distill only"
  mode TEXT DEFAULT 'distill',-- distill (keep results local) / upload (publish those that qualify)
  threshold REAL DEFAULT 99,  -- accuracy (%) from which a result may be accepted in one click
  number_guard INTEGER DEFAULT 1,
  priority INTEGER DEFAULT 1, -- 0 low / 1 normal / 2 high
  points INTEGER DEFAULT 1,   -- capacity points a run occupies (2 once a scanned file needed OCR)
  archived INTEGER DEFAULT 0,
  archived_at REAL, archived_by TEXT,
  created_by TEXT, created_at REAL, updated_at REAL,
  last_job_id TEXT
);
-- One row per source file of a room. `outcome` is NULL until the file has been processed.
CREATE TABLE IF NOT EXISTS room_file (
  room_id TEXT, rel TEXT,
  kind TEXT, size INTEGER,
  activity TEXT,              -- NULL / processing
  outcome TEXT,               -- result / unprocessable / skipped
  reason TEXT, detail TEXT,
  accuracy REAL, parts TEXT, diffs INTEGER DEFAULT 0, number_diffs INTEGER DEFAULT 0, findings TEXT,
  pages INTEGER, run_id TEXT,
  confirmed INTEGER DEFAULT 0, confirmed_by TEXT, confirmed_at REAL,
  updated_at REAL,
  PRIMARY KEY (room_id, rel)
);
CREATE INDEX IF NOT EXISTS idx_room_file_room ON room_file(room_id, outcome);
-- A correction a person confirmed, applied again wherever the same reading appears (see distill/rules.py).
CREATE TABLE IF NOT EXISTS correction_rule (
  id TEXT PRIMARY KEY,
  num INTEGER,                -- shown as #num
  find TEXT, replace_with TEXT,
  before_ctx TEXT, after_ctx TEXT,   -- number rules only: the exact text around the place
  kind TEXT,                  -- text / number
  scope TEXT,                 -- document / series / all
  series TEXT, doc TEXT,
  enabled INTEGER DEFAULT 1,
  reverts INTEGER DEFAULT 0,  -- how often a person undid it in a document
  source_room TEXT, source_rel TEXT,
  created_by TEXT, created_at REAL, updated_at REAL
);
-- A person undid a rule in one document: it is not applied there again.
CREATE TABLE IF NOT EXISTS correction_exempt (
  rule_id TEXT, room_id TEXT, rel TEXT, by_user TEXT, at REAL,
  PRIMARY KEY (rule_id, room_id, rel)
);
-- Every AI request, answered or not: what was asked, what came back, what it cost and what a person decided.
CREATE TABLE IF NOT EXISTS ai_call (
  id TEXT PRIMARY KEY,
  skill TEXT, version TEXT, provider TEXT, model TEXT,
  room_id TEXT, rel TEXT,
  input TEXT, output TEXT, result TEXT,
  status TEXT,                -- ok / cached / invalid / error / blocked
  message TEXT,
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, cost REAL DEFAULT 0, seconds REAL DEFAULT 0,
  decision TEXT, final TEXT, decided_by TEXT, decided_at REAL,
  created_by TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_ai_call_skill ON ai_call(skill, created_at);
-- An answer already given for the same question by the same skill version and model.
CREATE TABLE IF NOT EXISTS ai_cache (
  key TEXT PRIMARY KEY, skill TEXT, version TEXT, raw TEXT, result TEXT, created_at REAL
);
-- A place a person settled after an AI suggestion: shown to the AI as an example next time, and used to test models.
CREATE TABLE IF NOT EXISTS ai_example (
  id TEXT PRIMARY KEY, skill TEXT, input TEXT, answer TEXT, room_id TEXT, rel TEXT, by_user TEXT, at REAL, call_id TEXT
);
-- A person checked a number rule's change in one document and found it right.
CREATE TABLE IF NOT EXISTS correction_check (
  rule_id TEXT, room_id TEXT, rel TEXT, by_user TEXT, at REAL,
  PRIMARY KEY (rule_id, room_id, rel)
);
"""

# Columns added to `job` after its first version (a worker/process id and heartbeat for run supervision,
# and what the scheduler needs: owning room, priority, capacity points, output folder key).
_ROOM_FILE_COLUMNS = (("out_dir", "TEXT"), ("content_hash", "TEXT"), ("single_file", "INTEGER"), ("n_files", "INTEGER"),
                      ("verdict", "TEXT"), ("corrections", "TEXT"), ("rule_checks", "INTEGER DEFAULT 0"))
_JOB_COLUMNS = (("pid", "INTEGER"), ("heartbeat_at", "REAL"), ("room_id", "TEXT"),
                ("priority", "INTEGER DEFAULT 1"), ("points", "INTEGER DEFAULT 0"), ("dest_key", "TEXT"))


_ADDED_COLUMNS = (("flags", "TEXT"), ("src_chars", "INTEGER"), ("md_chars", "INTEGER"),
                  ("src_words", "INTEGER"), ("md_words", "INTEGER"))


def init_trust():
    con = trust_rw()
    if is_pg():
        schema = _SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        for stmt in (s.strip() for s in schema.split(";")):
            body = "\n".join(l.split("--")[0] for l in stmt.splitlines()).strip()
            if body:
                con.execute(body)
        for col, typ in _ADDED_COLUMNS:
            con.execute(f"ALTER TABLE file_eval ADD COLUMN IF NOT EXISTS {col} {typ}")
        for col, typ in _JOB_COLUMNS:
            con.execute(f"ALTER TABLE job ADD COLUMN IF NOT EXISTS {col} {typ}")
        for col, typ in _ROOM_FILE_COLUMNS:
            con.execute(f"ALTER TABLE room_file ADD COLUMN IF NOT EXISTS {col} {typ}")
        con.commit()
        con.close()
        return
    con.executescript(_SCHEMA)
    # 轻量迁移：老库补列。SQLite 不支持 ADD COLUMN IF NOT EXISTS，
    # 已存在时抛异常，忽略即可（幂等）。
    for col, typ in _ADDED_COLUMNS:
        try:
            con.execute(f"ALTER TABLE file_eval ADD COLUMN {col} {typ}")
        except Exception:
            pass
    for col, typ in _JOB_COLUMNS:
        try:
            con.execute(f"ALTER TABLE job ADD COLUMN {col} {typ}")
        except Exception:
            pass
    for col, typ in _ROOM_FILE_COLUMNS:
        try:
            con.execute(f"ALTER TABLE room_file ADD COLUMN {col} {typ}")
        except Exception:
            pass
    con.commit()
    con.close()


def now() -> float:
    return time.time()
