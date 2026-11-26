#!/bin/bash
# Stop Fidelity's Docker container. The data stays in the Docker volumes; start again with Fidelity-Docker-启动.command.
cd "$(dirname "$0")/../.." || exit 1
if docker info >/dev/null 2>&1; then
  docker compose down && echo "✅ 已停止（数据保留）/ Stopped (data kept)"
else
  echo "Docker Desktop 没有在运行，Fidelity 也就没有在运行。/ Docker Desktop is not running, so Fidelity is not either."
fi
read -r -p "按回车关闭 / Press Return to close " _
