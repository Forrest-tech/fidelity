# -*- coding: utf-8 -*-
"""FastAPI 入口。启动：uvicorn app.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .spa import SPAStaticFiles
import os

from . import db, config, instance
from .jobs import handlers
from .jobs.queue import queue
from .api.routes import router
from .auth.routes import router as auth_router
from .auth.users import current_user
from .auth.models import Role
from fastapi import Depends, Request

app = FastAPI(title="转换保真度评测系统 (Fidelity)", version="0.4.0")

from .auth.guard import GuardMiddleware
app.add_middleware(GuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


async def _authorize(request: Request, user=Depends(current_user)):
    """Every API route needs a login; mutating routes need reviewer or admin."""
    # a person's own bookkeeping (which notifications they have read) is not a change to the system
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path not in ("/api/v1/notifications/read", "/api/v1/account/password"):
        if user.role not in (Role.reviewer, Role.admin):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="insufficient role")
    return user


app.include_router(auth_router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1", dependencies=[Depends(_authorize)])
_OWNED = {"ok": False, "pid": None}


def _reap_stale_jobs():
    """把上次进程被 kill 时残留的 running/queued 任务收尾。

    ⚠️ 只有**本进程确实拥有实例所有权**时才允许执行。
    否则（重复启动）会把另一个正在跑的任务误标成「中断」——这是历史上
    job 表堆出一串 error 的根因。
    """
    if not _OWNED["ok"]:
        print("[startup] 非实例持有者，跳过僵死任务清理（避免误杀他人任务）")
        return
    try:
        con = db.trust_rw()
        try:
            running = [dict(r) for r in con.execute(
                "SELECT * FROM job WHERE status='running'").fetchall()]
        finally:
            con.close()
        from .jobs import sync_job
        for job in running:
            # A sync runs as its own process and survives a restart of this server: take it back. Anything else
            # (or a sync whose process is gone) is marked, never left showing "running".
            if job["kind"] == "dropbox_sync" and sync_job.adopt(job, queue._update):
                print("[startup] 已接管仍在运行的蒸馏任务 %s" % job["id"])
                continue
            status = "interrupted" if job["kind"] == "dropbox_sync" else "error"
            queue._update(job["id"], status=status,
                          message="服务重启导致任务中断（已完成的进度都已保存，可重新提交继续）")
    except Exception as e:
        print("[startup] 清理僵死任务失败：%s" % str(e)[:80])


@app.on_event("startup")
def _startup():
    db.init_trust()
    from .migrate import upgrade
    upgrade()

    # 单实例守卫：抢不到所有权说明已有一个健康的实例在跑。
    # 此时**不启动 worker、不清理任务**，让新进程安静退出即可。
    ok, info = instance.claim(port=config.SERVER_PORT)
    _OWNED["ok"] = ok
    _OWNED["pid"] = info.get("pid")
    if not ok:
        print("[startup] 检测到已有实例在运行(pid=%s)：%s" % (info.get("pid"), info.get("reason")))
        print("[startup] 本进程不启动 worker，也不改动任务状态（服务本身仍然可用）")
        return

    _reap_stale_jobs()
    handlers.register()
    from .jobs import rooms as _rooms
    _rooms.install_hooks()
    queue.start()
    print("[startup] trust.db ready, job workers started (owner pid=%s)" % os.getpid())


@app.on_event("shutdown")
def _shutdown():
    if _OWNED["ok"]:
        instance.release()
        print("[shutdown] 已释放实例锁")


@app.get("/api/v1/health")
def health():
    owner = instance.read_owner() or {}
    return {
        "ok": True,
        "service": "fidelity",
        "workers": len(queue._threads),
        "pid": os.getpid(),
        "is_owner": bool(_OWNED["ok"]),
        "owner_pid": owner.get("pid"),
        "version": app.version,
    }


# ---- 静态托管必须放最后：挂载到 "/" 会兜住所有未匹配路径，
#      若在 API 路由之前挂载，会把 /api/* 也吃掉（FastAPI 按注册顺序匹配）。
# 生产模式：前端 build 后由后端托管，实现"单端口启动"。
# 注意 config.BASE_DIR 指向 backend/，前端在同级 web/ 下。
# FIDELITY_WEB_DIST serves another build (the browser tests use their own, so the running app is not touched)
WEB_DIST = os.environ.get("FIDELITY_WEB_DIST") or os.path.join(os.path.dirname(config.BASE_DIR), "web", "dist")
if os.path.isdir(WEB_DIST):
    app.mount("/", SPAStaticFiles(directory=WEB_DIST, html=True), name="web")
