# -*- coding: utf-8 -*-
"""异步任务队列（规格 §5.1-5.2）。
解析/OCR/对比全部入队，后台 worker 执行，HTTP 立即返回 job_id，前端轮询进度。
任务持久化在 trust.db 的 job 表，重启不丢。
"""
import uuid, threading, time, traceback
from .. import db

_MAX_WORKERS = 2  # 并发 worker（本地单用户，避免多开 PaddleOCR 抢内存）


class JobQueue:
    def __init__(self):
        self._handlers = {}
        self._threads = []
        self._stop = False
        self._wake = threading.Event()

    def register(self, kind, fn):
        self._handlers[kind] = fn

    def submit(self, kind, rel="", message=""):
        jid = uuid.uuid4().hex[:12]
        now = db.now()

        def _do():
            con = db.trust_rw()
            try:
                con.execute(
                    "INSERT INTO job(id,kind,rel,status,progress,message,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (jid, kind, rel, "queued", 0.0, message, now, now),
                )
                con.commit()
            finally:
                con.close()

        # WAL 下多 worker + 主线程并发时偶发 "readonly database" 瞬时降级，重试吸收
        db.trust_write(_do)
        self._wake.set()
        return jid

    def _update(self, jid, **kw):
        kw["updated_at"] = db.now()
        sets = ",".join("%s=?" % k for k in kw)

        def _do():
            con = db.trust_rw()
            try:
                con.execute("UPDATE job SET %s WHERE id=?" % sets, (*kw.values(), jid))
                con.commit()
            finally:
                con.close()

        db.trust_write(_do)

    def _claim(self):
        con = db.trust_rw()
        row = con.execute(
            "SELECT * FROM job WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row:
            con.execute("UPDATE job SET status='running', updated_at=? WHERE id=?",
                        (db.now(), row["id"]))
            con.commit()
        con.close()
        return dict(row) if row else None

    def get(self, jid):
        con = db.trust_rw()
        row = con.execute("SELECT * FROM job WHERE id=?", (jid,)).fetchone()
        con.close()
        return dict(row) if row else None

    def _loop(self):
        while not self._stop:
            job = self._claim()
            if not job:
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            base_kind = job["kind"].split(":", 1)[0]
            fn = self._handlers.get(base_kind)
            try:
                if not fn:
                    raise RuntimeError("no handler for kind=%s" % job["kind"])
                # handler(job_dict, report)  report(progress:0-100, message:str)
                fn(job, lambda p, m="": self._update(job["id"], progress=p, message=m))
                self._update(job["id"], status="done", progress=100.0, message="完成")
            except Exception as e:
                self._update(job["id"], status="error", message=str(e)[:500])
                traceback.print_exc()

    def start(self, n=_MAX_WORKERS):
        for i in range(n):
            t = threading.Thread(target=self._loop, daemon=True, name="job-%d" % i)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop = True
        self._wake.set()


queue = JobQueue()
