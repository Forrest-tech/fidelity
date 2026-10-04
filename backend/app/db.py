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


def trust_rw() -> sqlite3.Connection:
    """trust.db 可写连接。WAL 只在 init_trust 设一次；这里只设 busy_timeout，
    避免多 worker 并发反复切 journal_mode 导致锁/只读降级。"""
    con = sqlite3.connect(config.TRUST_DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    return con


def trust_write(fn, retries=5):
    """把一次写操作包成带重试的函数（吸收瞬时锁/只读降级）。"""
    import time as _t
    last = None
    for i in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
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
"""


def init_trust():
    con = trust_rw()
    con.executescript(_SCHEMA)
    # 轻量迁移：老库补列。SQLite 不支持 ADD COLUMN IF NOT EXISTS，
    # 已存在时抛异常，忽略即可（幂等）。
    for sql in ("ALTER TABLE file_eval ADD COLUMN flags TEXT",
                "ALTER TABLE file_eval ADD COLUMN src_chars INTEGER",
                "ALTER TABLE file_eval ADD COLUMN md_chars INTEGER",
                "ALTER TABLE file_eval ADD COLUMN src_words INTEGER",
                "ALTER TABLE file_eval ADD COLUMN md_words INTEGER",):
        try:
            con.execute(sql)
        except Exception:
            pass
    con.commit()
    con.close()


def now() -> float:
    return time.time()
