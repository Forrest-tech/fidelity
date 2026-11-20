# -*- coding: utf-8 -*-
"""异步任务队列（规格 §5.1-5.2）。
解析/OCR/对比全部入队，后台 worker 执行，HTTP 立即返回 job_id，前端轮询进度。
任务持久化在 trust.db 的 job 表，重启不丢。
"""
import uuid, threading, time, traceback
from .. import db
from . import capacity

_MAX_WORKERS = 2  # 并发 worker（本地单用户，避免多开 PaddleOCR 抢内存）


class Interrupted(RuntimeError):
    """A run's process ended without finishing (killed, the machine restarted). Work already done is kept,
    so the run can simply be started again and carries on."""


class JobQueue:
    def __init__(self):
        self._handlers = {}
        self._threads = []
        self._stop = False
        self._wake = threading.Event()
        self._claim_lock = threading.Lock()      # capacity is checked and a job taken as one step
        self.after_done = []                     # callables(job_dict), run once a job has finished well

    def register(self, kind, fn):
        self._handlers[kind] = fn

    def submit(self, kind, rel="", message="", *, room_id=None, priority=1, points=0, dest_key=None):
        """Queue a job. `points` is how much machine capacity a run needs (0 = does not count against capacity),
        `priority` 0 low / 1 normal / 2 high, `dest_key` names an output folder that only one run may write at a time."""
        jid = uuid.uuid4().hex[:12]
        now = db.now()

        def _do():
            con = db.trust_rw()
            try:
                con.execute(
                    "INSERT INTO job(id,kind,rel,status,progress,message,created_at,updated_at,room_id,priority,points,dest_key) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (jid, kind, rel, "queued", 0.0, message, now, now, room_id, priority, points, dest_key),
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
        if kw.get("status") == "done":
            row = self.get(jid)
            for hook in self.after_done:
                try:
                    hook(row)
                except Exception:                              # noqa: BLE001 - a follow-up must never break the job itself
                    traceback.print_exc()

    def _claim(self):
        """Take the next job that may start now.

        Order: higher priority first, then oldest. A job is skipped for now (not dropped) when its capacity points
        do not fit beside what is already running, or when another running job writes the same output folder.
        A job larger than the whole machine still runs, but alone. The take itself is atomic: a worker only gets
        the job if ITS update moved the row from queued to running (found in testing: one Dropbox sync started
        twice and the copies collided on the same file)."""
        with self._claim_lock:
            con = db.trust_rw()
            try:
                for _ in range(5):
                    rows = con.execute(
                        "SELECT * FROM job WHERE status='queued' ORDER BY COALESCE(priority,1) DESC, created_at").fetchall()
                    if not rows:
                        return None
                    running = con.execute("SELECT points, dest_key FROM job WHERE status='running'").fetchall()
                    used = sum((r["points"] or 0) for r in running)
                    busy = {r["dest_key"] for r in running if r["dest_key"]}
                    cap = capacity.points()
                    row = None
                    for cand in rows:
                        pts = cand["points"] or 0
                        if pts and used and used + pts > cap:
                            continue
                        if cand["dest_key"] and cand["dest_key"] in busy:
                            continue
                        row = cand
                        break
                    if row is None:
                        return None
                    cur = con.execute("UPDATE job SET status='running', updated_at=? WHERE id=? AND status='queued'",
                                      (db.now(), row["id"]))
                    con.commit()
                    if cur.rowcount == 1:
                        job = dict(row)
                        job["status"] = "running"
                        return job
                return None                               # lost every race this round; try again on the next tick
            finally:
                con.close()

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
            except Interrupted as e:
                self._update(job["id"], status="interrupted", message=str(e)[:500])
            except Exception as e:
                self._update(job["id"], status="error", message=str(e)[:500])
                traceback.print_exc()

    def start(self, n=None):
        n = n or max(_MAX_WORKERS, capacity.points() + 1)     # one worker per capacity point, plus one for light jobs
        for i in range(n):
            t = threading.Thread(target=self._loop, daemon=True, name="job-%d" % i)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop = True
        self._wake.set()


queue = JobQueue()
