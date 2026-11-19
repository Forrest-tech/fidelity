"""A queued job is claimed by exactly one worker, even when several workers ask at the same moment."""
import threading

from app import db
from app.jobs.queue import JobQueue


def test_concurrent_workers_never_claim_the_same_job():
    db.init_trust()
    q = JobQueue()
    con = db.trust_rw()
    con.execute("DELETE FROM job WHERE kind='claimtest'")
    con.commit()
    con.close()
    for _ in range(3):
        jid = q.submit("claimtest", "", "queued")
    got, start = [], threading.Barrier(8)

    def worker():
        start.wait()
        while True:
            j = q._claim()
            if j is None:
                return
            got.append(j["id"])

    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    mine = [g for g in got if g]
    con = db.trust_rw()
    ids = [r[0] for r in con.execute("SELECT id FROM job WHERE kind='claimtest'").fetchall()]
    con.close()
    assert sorted(mine) == sorted(ids) and len(mine) == len(set(mine)) == 3   # each job exactly once
