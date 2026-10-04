# -*- coding: utf-8 -*-
"""单实例守卫：防止重复启动把「在跑的任务」标成「被重启中断」。

为什么需要这个（真实事故）：
    同一个trust.db 上起第二个后端实例时，旧实例仍在后台跑批量评测。
    第二个实例的 startup 钩子会执行
        UPDATE job SET status='error' WHERE status IN ('running','queued')
    把**第一个实例正在跑的任务**标成「服务重启中断」。
    结果：任务反复被杀 → job 表里堆了一串 error → 用户以为系统有问题。

    同时第二个实例还会因为端口被占用而启动失败，任务面板显示 Failed，
    但服务其实一直是好的（第一个实例照常在跑）——这是最迷惑人的地方。

本模块提供：
    claim()  抢占实例所有权。已有活实例 → 返回 (False, info)，调用方应安静退出。
    release() 释放所有权（进程正常退出时调用）。
    preflight_port() 探测端口上是否已有健康实例（供启动脚本在绑定端口前判断）。
"""
import os
import json
import time
import errno
import socket
import urllib.request

from . import config

# /api/health 里标识「这是本服务」的值。第一个是当前名称，其余为历史名称。
# 改名升级期间旧实例仍在跑，preflight 必须仍然认得它 —— 否则重启时会去抢
# 自己已经占着的端口，任务面板又显示 Failed（这正是本模块要消灭的现象）。
SERVICE_IDS = ("fidelity", "qa-platform")

LOCK_PATH = os.path.join(config.DATA_DIR, "server.lock")
# 锁文件里附带心跳时间；超过这个秒数没心跳，视为进程已死（防 PID 复用误判）
HEARTBEAT_STALE_SEC = 90


def _pid_alive(pid):
    """pid 是否还活着。探测不了时保守返回 True（宁可漏判重启，也不要误杀在跑的任务）。"""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return True
            finally:
                k.CloseHandle(h)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM
    return True


def _read_lock():
    try:
        with open(LOCK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_owner():
    """返回当前锁信息（无锁返回 None）。不校验存活，仅供展示。"""
    return _read_lock()


def _write_lock(pid, port):
    tmp = LOCK_PATH + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "port": port, "started_at": time.time(),
                   "heartbeat_at": time.time()}, f)
    os.replace(tmp, LOCK_PATH)


def claim(port=0):
    """抢占实例所有权。

    返回 (ok, info)：
      ok=True  info={"pid":...}         —— 抢到，本进程负责跑 worker
      ok=False info={"pid":...,"reason":...} —— 已有活实例，调用方应安静退出
    """
    lock = _read_lock()
    if lock:
        pid = lock.get("pid")
        hb = lock.get("heartbeat_at") or 0
        fresh = (time.time() - hb) <= HEARTBEAT_STALE_SEC
        if _pid_alive(pid) and fresh:
            return False, {"pid": pid, "port": lock.get("port"),
                           "reason": "已有实例在运行"}
        # 锁在但进程已死（或心跳过期）→ 直接覆盖写，不要先删文件。
        #
        # 真实事故（2026-10-05）：这里原本先 os.remove(LOCK_PATH) 再写。
        # 某些宿主环境（如 WorkBuddy）会给 os.remove 挂安全钩子，把删除拦下来
        # 后抛 SystemExit —— 它继承自 BaseException，下面的 except OSError
        # 捕不到，于是直接崩在启动阶段，表现为「服务起不来」且日志里只有
        # 一句无关的批量删除告警。SystemExit 不该由业务代码吞掉，但更根本的
        # 修法是根本不要删：_write_lock 本来就是覆盖写，删那一步是多余的。
    _write_lock(os.getpid(), port)
    return True, {"pid": os.getpid(), "port": port}


def heartbeat(port=0):
    """刷新心跳。定时调用，让长时间无任务时锁不会被当成死锁。"""
    lock = _read_lock()
    if not lock or lock.get("pid") != os.getpid():
        return False
    lock["heartbeat_at"] = time.time()
    lock["port"] = port or lock.get("port")
    try:
        _write_lock(os.getpid(), lock.get("port"))
        return True
    except OSError:
        return False


def release():
    """只释放自己持有的锁，避免把别人的锁删了。

    删除可能失败（文件被占用、宿主环境给 os.remove 挂了拦截钩子并抛
    SystemExit 等 BaseException），所以这里捕获 BaseException：释放失败
    不该影响进程退出，残留的锁会被下一次 claim 依据「进程已死」覆盖掉。
    """
    lock = _read_lock()
    if lock and lock.get("pid") == os.getpid():
        try:
            os.remove(LOCK_PATH)
        except BaseException:
            # 含 SystemExit / KeyboardInterrupt 之外的宿主钩子异常。
            # 锁文件残留是无害的：claim() 会覆盖写。
            pass


def port_open(port, host="127.0.0.1", timeout=1.0):
    """端口是否已被占用。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, int(port))) == 0
    finally:
        s.close()


def preflight_port(port, host="127.0.0.1", timeout=2.0):
    """端口上是否已经是「健康的本服务」。

    返回 (healthy, detail)。用于启动脚本在绑定端口前判断：
    如果已经健康，就不要再去抢端口（会报 address already in use → 任务显示 Failed），
    直接安静退出即可。
    """
    if not port_open(port, host, timeout=0.8):
        return False, "端口 %s 未被占用" % port
    url = "http://%s:%s/api/health" % (host, port)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("service") in SERVICE_IDS and data.get("ok"):
            return True, "已有健康实例在 %s:%s（workers=%s）" % (
                host, port, data.get("workers"))
        return False, "端口被占用但不是本服务：%s" % data
    except Exception as e:
        return False, "端口被占用但健康检查失败：%s" % str(e)[:120]
