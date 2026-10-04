# -*- coding: utf-8 -*-
"""后端启动器：先做「单实例 + 端口」预检，再决定是否真的拉起 uvicorn。

为什么需要这个（真实事故）：
    重复执行启动命令时，uvicorn 会因端口被占用而退出非零，任务面板显示 **Failed**，
    但服务其实一直是好的（旧实例仍在跑）。用户看到 Failed 会误以为系统坏了，
    甚至去重启服务 —— 而这一重启会把正在跑的批量评测任务标成「被重启中断」。

行为：
    1. 端口上已有健康的本服务 → 打印说明并以退出码 0 安静结束（不算失败）。
    2. 端口被别的程序占用（非本服务）→ 明确报错并退出码 2。
    3. 端口空闲 → 正常启动 uvicorn。

用法：
    python -m scripts.serve            # 前台启动
    python -m scripts.serve --check    # 只做预检，不启动
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, instance  # noqa: E402


def main():
    port = config.SERVER_PORT
    host = config.SERVER_HOST

    if "--check" in sys.argv:
        ok, detail = instance.preflight_port(port, host)
        lock = instance.read_owner()
        print("[serve] 预检端口 %s:%s -> %s" % (host, port, "健康实例在运行" if ok else "可启动"))
        print("[serve] %s" % detail)
        print("[serve] 实例锁: %s" % (lock or "无"))
        return 0 if not ok else 0

    healthy, detail = instance.preflight_port(port, host)
    if healthy:
        # 关键：已有健康服务在跑，这是「无需重复启动」，不是失败。
        lock = instance.read_owner() or {}
        print("[serve] 检测到已有健康实例：%s" % detail)
        print("[serve] 实例持有者 pid=%s" % lock.get("pid"))
        print("[serve] 不重复启动。服务地址： http://%s:%s" % (host, port))
        return 0

    if instance.port_open(port, host):
        print("[serve] 端口 %d 被非本服务占用：%s" % (port, detail), file=sys.stderr)
        print("[serve] 请先释放该端口，或设置 QA_SERVER_PORT 换一个端口。", file=sys.stderr)
        return 2

    print("[serve] 启动 uvicorn on %s:%s ..." % (host, port))
    env = dict(os.environ, QA_SERVER_PORT=str(port), QA_SERVER_HOST=host)
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
           "--host", host, "--port", str(port)]
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
