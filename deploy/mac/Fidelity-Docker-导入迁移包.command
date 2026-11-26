#!/bin/bash
# Load a migration package (made on the old server by backend/scripts/migrate_export.py) into Fidelity on this Mac.
#   Double-click: uses the newest fidelity-migration-*.zip in Downloads or on the Desktop.
#   Terminal:     bash deploy/mac/Fidelity-Docker-导入迁移包.command /path/to/fidelity-migration-XXXX.zip
# Accounts, rooms, publish records and the Dropbox / AI / e-mail settings then come from the old server.
# What it replaces is kept in a pre-import backup inside the container (data/backups).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
URL="http://127.0.0.1:8000"
fail() { printf '\n\033[31m✗ %s\033[0m\n' "$*"; read -r -p "按回车关闭 / Press Return to close " _; exit 1; }

PKG="${1:-}"
if [ -z "$PKG" ]; then
  PKG="$(ls -t "$HOME"/Downloads/fidelity-migration-*.zip "$HOME"/Desktop/fidelity-migration-*.zip 2>/dev/null | head -1)"
fi
[ -n "$PKG" ] && [ -f "$PKG" ] || fail "找不到迁移包。请把 fidelity-migration-*.zip 放到"下载"或桌面，或把它拖到这个命令后面再运行。"
echo "迁移包 / Package: $PKG"

docker info >/dev/null 2>&1 || fail "Docker Desktop 没有运行。请先双击 Fidelity-Docker-启动.command。"
docker compose ps --status running 2>/dev/null | grep -q fidelity || fail "Fidelity 没有在运行。请先双击 Fidelity-Docker-启动.command。"

echo "▶ 复制到容器并校验、导入… / Copying, checking and importing"
docker compose cp "$PKG" fidelity:/tmp/fidelity-migration.zip || fail "复制到容器失败。"
docker compose exec -T fidelity python scripts/migrate_import.py /tmp/fidelity-migration.zip || fail "导入失败（上面是原因）。什么都没有改动。"
docker compose exec -T fidelity rm -f /tmp/fidelity-migration.zip

echo "▶ 重启服务… / Restarting"
docker compose restart >/dev/null || fail "重启失败。"
for _ in $(seq 1 90); do curl -fsS "$URL/api/v1/health" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$URL/api/v1/health" >/dev/null 2>&1 || fail "重启后服务没有响应：docker compose logs --tail 50 查看原因。"
open "$URL"
cat <<EOF

✅ 导入完成。请用原系统的账户登录（导入前在这台 Mac 上新建的账户已被替换）。
   迁移包里有密钥（Dropbox、AI、邮件）：确认无误后请删除它：
   $PKG
EOF
read -r -p "按回车关闭 / Press Return to close " _
