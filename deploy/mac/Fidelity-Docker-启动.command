#!/bin/bash
# Fidelity on a Mac, in Docker — one click (double-click this file in Finder, or run it in Terminal).
#
# What it does, every time (safe to run again; it is also the update):
#   1. makes sure Docker Desktop is installed and running (installs it with Homebrew if Homebrew is there)
#   2. gets the newest code when this folder is a git clone with no local changes
#   3. writes deploy/docker/fidelity.env the first time (built-in SQLite database, nothing else to install)
#   4. builds and starts the container (docker compose up -d --build); data stays in Docker volumes
#   5. waits until the app answers, then opens http://127.0.0.1:8000 in the browser
#
# Stop it with "Fidelity-Docker-停止.command". Logs: docker compose logs -f (in this folder).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd)"
URL="http://127.0.0.1:8000"
say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m✗ %s\033[0m\n' "$*"; read -r -p "按回车关闭 / Press Return to close " _; exit 1; }

[ -f "$ROOT/docker-compose.yml" ] || fail "找不到 docker-compose.yml：请把这个文件留在 fidelity 项目的 deploy/mac 文件夹里运行。"

# ---- 1. Docker Desktop
if ! command -v docker >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    say "安装 Docker Desktop（Homebrew）… / Installing Docker Desktop"
    brew install --cask docker || fail "Docker Desktop 安装失败。请从 https://www.docker.com/products/docker-desktop/ 手动安装后再运行。"
  else
    open "https://www.docker.com/products/docker-desktop/"
    fail "这台 Mac 还没有 Docker Desktop。已打开下载页：安装（选 Apple 芯片或 Intel 对应版本）并打开一次后，再双击本文件。"
  fi
fi
if ! docker info >/dev/null 2>&1; then
  say "启动 Docker Desktop… / Starting Docker Desktop"
  open -a Docker || fail "无法启动 Docker Desktop，请手动打开它。"
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || fail "Docker Desktop 3 分钟内没有就绪。请确认它已打开并同意了许可协议，再运行一次。"
fi
docker compose version >/dev/null 2>&1 || fail "这个 Docker 版本没有 'docker compose'，请更新 Docker Desktop。"

# ---- 2. newest code (only a clean git clone; never overwrites local edits)
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  if [ -z "$(git status --porcelain --untracked-files=no)" ]; then
    say "获取最新代码… / Updating the code"
    git pull --ff-only || echo "  (没有更新成功，继续用当前代码 / could not update; using the code as it is)"
  else
    echo "  本地有改动，跳过更新 / local changes: not updating"
  fi
fi

# ---- 3. settings file (first run only)
if [ ! -f deploy/docker/fidelity.env ]; then
  say "生成设置文件 deploy/docker/fidelity.env（内置 SQLite 数据库）"
  cat > deploy/docker/fidelity.env <<'EOF'
# Written by Fidelity-Docker-启动.command. Database: SQLite inside the Docker volume (nothing to install).
# For PostgreSQL see deploy/docker/fidelity.env.example and the runbook.
FIDELITY_VISUAL_SAMPLES=3
EOF
fi

# backups: every daily backup is also copied to ~/FidelityBackups on this Mac (outside the Docker volumes)
mkdir -p "$HOME/FidelityBackups"
grep -q '^FIDELITY_BACKUP_COPY_DIR=' deploy/docker/fidelity.env || echo 'FIDELITY_BACKUP_COPY_DIR=/backup-copies' >> deploy/docker/fidelity.env
export FIDELITY_BACKUP_HOST_DIR="$HOME/FidelityBackups"

# ---- 4. port free?
if lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | grep -qv com.docker; then
  if ! docker compose ps --status running 2>/dev/null | grep -q fidelity; then
    fail "端口 8000 已被其他程序占用（lsof -iTCP:8000 查看）。请关闭它后再运行。"
  fi
fi

# ---- 5. build and start
say "构建并启动容器（第一次约 5–15 分钟，之后很快）… / Building and starting"
docker compose config -q || fail "Docker Compose 读不懂 docker-compose.yml（版本 $(docker compose version --short 2>/dev/null)）。请更新 Docker Desktop 后再运行。"
# Always build for this Mac's own chip. An image built as linux/amd64 runs under emulation on an Apple-silicon Mac and
# reads scanned pages several times slower (found 2026-11-26: about 52 s a page). If an older run left such an image,
# it is rebuilt here.
case "$(uname -m)" in arm64|aarch64) NATIVE=linux/arm64 ;; *) NATIVE=linux/amd64 ;; esac
export DOCKER_DEFAULT_PLATFORM="$NATIVE"
docker compose up -d --build || fail "构建失败。请把上面的输出发给维护者。"
ARCH="$(docker compose exec -T fidelity uname -m 2>/dev/null | tr -d '\r')"
case "$NATIVE:$ARCH" in
  linux/arm64:x86_64)
    say "容器在模拟 x86 方式下运行（会很慢），按本机芯片重新构建… / Rebuilding for this Mac's chip"
    docker compose build --no-cache && docker compose up -d --force-recreate || fail "重新构建失败。请把上面的输出发给维护者。" ;;
esac
echo "  容器架构 / container architecture: ${ARCH:-?}（本机 / this Mac: $(uname -m)）"

# ---- 6. wait until it answers, then open the browser
say "等待服务就绪… / Waiting for the app"
for _ in $(seq 1 120); do
  curl -fsS "$URL/api/v1/health" >/dev/null 2>&1 && break
  sleep 2
done
if curl -fsS "$URL/api/v1/health" >/dev/null 2>&1; then
  # Keep the Mac from idle sleep while Docker Desktop runs: a long distilling run lost its connection to Dropbox for
  # minutes on 2026-11-26 (likely the Mac idling to sleep, which pauses Docker's network). Closing the lid still sleeps.
  DPID="$(pgrep -n -f 'com.docker.backend' || pgrep -n -x 'Docker Desktop' || true)"
  if [ -n "$DPID" ] && ! pgrep -f "caffeinate -i -w $DPID" >/dev/null 2>&1; then
    nohup caffeinate -i -w "$DPID" >/dev/null 2>&1 &
  fi
  open "$URL"
  cat <<EOF

✅ Fidelity 已在运行：$URL
   第一次使用：在打开的页面里创建管理员账户，然后到"设置 → 网盘与本机目录"连接 Dropbox
   （需要 Dropbox App key，可在原系统的同一页面看到），"设置 → AI"填 DeepSeek 密钥，"设置 → 邮件"填 SMTP。
   停止：双击 Fidelity-Docker-停止.command    日志：在项目文件夹运行 docker compose logs -f
EOF
else
  docker compose logs --tail 40
  fail "服务 4 分钟内没有响应。上面是最近的日志，请发给维护者。"
fi
read -r -p "按回车关闭这个窗口（服务会继续在后台运行）/ Press Return to close (the app keeps running) " _
