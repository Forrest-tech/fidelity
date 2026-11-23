# Fidelity 管理员运维手册

给负责蒸馏和维护 AI 工具的人。命令都在 `backend/` 目录下、用项目环境运行（Windows 上是
`..\.venv\Scripts\python`），并设置 `PYTHONUTF8=1`。

## 铁律（绝不能违反）
1. **Dropbox 源文件夹只读。** 任何程序都不在那里写入、移动或删除；每次同步都会对比源文件夹前后快照，
   证明保存在 `<目标>/_sync/`。
2. **只发布验证通过的内容。** 不通过或需要审核的进入 `_pending/`。
3. **`data/` 永远不提交到 git**——里面有 Dropbox 凭据和工作文件。

## 启动应用
- 双击项目文件夹里的 `启动.bat` → 浏览器打开 <http://127.0.0.1:8000>。重复双击无害（只会再打开浏览器）。
- 或者：`python -m scripts.serve`（加 `--check` 只检查端口）。

## 用户和角色
- **首次启动：**还没有任何用户时，登录页会提供"创建第一个管理员"。
- 新建或重置用户：`python scripts/create_admin.py name@example.com --role admin|reviewer|viewer`
  （密码会提示输入，或取自 `FIDELITY_NEW_PASSWORD`；绝不写在命令行上）。
- admin：全部权限 · reviewer：审核队列和审核决定 · viewer：只读。
- 登录限制每个 IP 每 5 分钟 5 次；登录记录在审计日志里。

## 登录：Google、Microsoft、GitHub、公司 SSO；人机验证；限流
- 用户可以用邮箱和密码登录，也可以点登录方式按钮。只有在服务器环境变量里设置了对应凭据（然后重启）时才显示该按钮：
  `FIDELITY_OAUTH_GOOGLE_CLIENT_ID` / `_SECRET`、`FIDELITY_OAUTH_MICROSOFT_CLIENT_ID` / `_SECRET`
  （可选 `FIDELITY_OAUTH_MICROSOFT_TENANT`，默认 `common`）、`FIDELITY_OAUTH_GITHUB_CLIENT_ID` / `_SECRET`、
  `FIDELITY_OAUTH_OIDC_CLIENT_ID` / `_SECRET` / `_DISCOVERY_URL`（另可设 `FIDELITY_OAUTH_OIDC_LABEL`，如 "Okta"）。
- 在登录服务商处登记回调地址：`<站点>/api/v1/auth/oauth/<google|microsoft|github|oidc>/callback`。
  经过反向代理时设置 `FIDELITY_PUBLIC_URL`（如 `https://fidelity.example.com`）。
- 仅限邀请：只有 Fidelity 里已有相同邮箱的用户才能用第三方登录（在“用户”里添加）。要让整个公司域名以查看者身份登录，
  设置 `FIDELITY_OAUTH_ALLOWED_DOMAINS=example.com`。只接受服务商已验证的邮箱；不保存服务商的令牌。
- 人机验证（ALTCHA，在本服务器上运行，无需点击）保护登录和首次设置，在办公室的纯 HTTP 地址上也能用。
  `FIDELITY_CAPTCHA=off` 仅用于脚本化部署。
- 限流：每个地址 5 分钟内 5 次密码错误、每个账号 15 分钟内 10 次（之后返回 HTTP 429 和 Retry-After）；
  每个地址每分钟 300 次登录相关请求（`FIDELITY_AUTH_CALLS_PER_MINUTE`）。
- 忘记密码：用户 → 选中此人 → 设置密码。最后一个启用的管理员不能被降级或停用。

## Dropbox 权限
**在网页里（推荐）：**设置 → **网盘连接**（管理员）。两个权限（*读取*用于源文件夹，*写入*用于输出文件夹）
分别填 App key，点"连接"，在 Dropbox 里允许，然后粘贴授权码。连接保存在本服务器上，不需要在机器之间拷贝文件。

两个应用角色，都保存在 `data/dropbox_auth.json`：
- **reader**（只读权限）——用于源文件夹和只读拷贝。
- **writer**——只用于目标文件夹；受保护的写入器会拒绝目标以外的任何路径。

重新授权（例如权限范围改变后）：`python -m app.distill.dropbox_io auth --app-key <key> --role reader --read-only`
（或 `--role writer`）。打开链接，粘贴授权码。

## Google Drive
设置 → 网盘连接 → **Google Drive**（管理员），使用 Google 标准的 OAuth 2.0 流程：
1. Google Cloud Console：新建或选择项目；启用 **Google Drive API**；配置 OAuth 同意屏幕
   （Workspace 选 Internal，否则选 External 并把自己加为测试用户）。
2. 凭据 → OAuth 客户端 ID → **Web 应用**；添加页面上显示的*已获授权的重定向 URI*
   （如 `http://localhost:8000/api/v1/storage/google/callback`——打开本系统时用同一个主机名）。
3. 把客户端 ID 和密钥粘贴到页面并保存，然后分别**连接**读取权限（范围 `drive.readonly`）和写入权限
   （范围 `drive`，只用于输出文件夹）。令牌保存在服务器上（`data/google_auth.json`）。
在云盘同步里用 Drive 文件夹链接（`https://drive.google.com/drive/folders/…`）作为源或输出。Google 文档、表格、
幻灯片会导出为 .docx、.xlsx、.pptx，按 Office 文件蒸馏；在 Drive 上删除只会移到回收站。Dropbox 和 Google Drive
可以混用（例如 Drive → Dropbox）。参考：developers.google.com/identity/protocols/oauth2/web-server 和
developers.google.com/drive/api。

## 蒸馏和发布
**在网页里**（reviewer 或 admin）：**数据源 → Dropbox 同步**。粘贴源文件夹的共享链接和输出文件夹的共享链接，
第一次保持勾选**试运行**，点开始，在"最近的运行"里看进度、每个文件的结果和日志。去掉"试运行"即正式发布。
管理员可以在同一处回滚已发布的运行。它执行的就是下面的命令。

**用命令行：**
```
python -m app.distill.sync --source-link <源共享链接> --dest-link <目标共享链接> --dry-run
python -m app.distill.sync --source-link <…> --dest-link <…>
```
- `--dry-run` 只蒸馏和验证，不上传——新文件夹第一次一定先跑它。
- 没变化的文件会跳过（账本记录）；`--force` 全部重新蒸馏；`--only 名称` 只处理文件名含该文字的文件。
- 输出先放到 `<目标>_staging`，检查后再正式发布；旧版本移到 `<目标>_archive`。
- **回滚一次发布**：`python -m app.distill.sync --source-link <…> --dest-link <…> --rollback <RUN>`
  （每次同步结束时会打印"undo with: … --rollback <RUN>"；该次运行的清单在
  `data/work/publish/publish-<RUN>.json`）。
- 加密文件会被列出但不蒸馏；`--publish-protected-metadata` 为它们发布只含元数据的条目。
- 看运行汇总：每个文件的 PASS / REVIEW / FAIL / SKIP，重复文件，不支持的文件。

## 审核队列
在网页里（reviewer 或 admin）：**Overview（概览）→ Needs attention（需要处理）**和 **Documents** 页
（按结果筛选）列出没有通过的文件；**Review（审核）**页左右对照原文和 Markdown。两个 OCR 引擎读得不一致的
扫描件、没有标题栏的图纸、任何检查不通过的文件都在这里；在 Dropbox 上它们在 `<目标>/_pending/`，
不会进入正式目录。

## OCR（扫描件和图片）
- 引擎：RapidOCR（pip 安装）和 **Tesseract 5**（单独安装；Windows 上用 UB Mannheim 版本，装在
  `C:\Program Files\Tesseract-OCR`，程序会自动找到）。
- RapidOCR 英文模型只需下载一次，版本固定并核对哈希：`python scripts/fetch_ocr_models.py`（存到 `data/models/`）。
- 基准测试：`python scripts/ocr_benchmark.py --synthetic --out <目录>`，或 `--pdf <文字型PDF> --pages 1,5 --out <目录>`。

## 术语表（OCR 修正用）
大批量发布后重建一次，让它学到新词（只读取 `auto_verified` 的文件）：
1. 用 **reader** 角色把已发布的知识库拷到本地（rclone 示例）：
   `rclone copy dbx:/Transfer_Md data/work/transfer_md_snapshot --filter "- _*/**" --filter "+ *.md" --filter "- *"`
2. `python -m app.distill.glossary build ../data/work/transfer_md_snapshot` → 生成 `data/glossary.json`。

## 适配包（Grok 技能及其他工具）
知识库有明显变化、或修改了 `adapters/house_rules.yaml` 后，重新生成：
1. 刷新本地知识库拷贝（同上；正式库则拷贝 `Md_Library`）。
2. `python -m app.adapters.build --library ../data/work/transfer_md_snapshot`
3. 看 `adapters/dist/build-report.json`：**starting_points_missing** 列出 `house_rules.yaml` 里知识库没有的
   常用入口——修正或删掉。
4. 安装：
   - **Grok**：Skills → 打开 `au-compliance-kb` → 用 `adapters/dist/grok/au-compliance-kb.md` 替换全部内容。
     只在蒸馏库替换了 `Md_Library` 之后才这样做：适配包里的目录说明描述的是生成它时用的那个库。员工现在用的版本
     保存在 `adapters/installed/`。
   - **Grok 试运行技能**（蒸馏库还在 `/Transfer_Md` 期间）：从 `/Transfer_Md` 的拷贝生成，加
     `--house ../adapters/house_rules.trial.yaml --out ../adapters/dist-trial --tools grok`；然后 Skills → New →
     名称 `au-compliance-kb-trial`，粘贴 description 和 front matter 下面的正文。对话开头说"用试运行库"即可选中它。
   - **Claude**：Settings → Capabilities → Skills → 上传 `adapters/dist/claude/au-compliance-kb/`（压缩成 zip）。
   - **Codex / Gemini CLI**：把 `AGENTS.md` / `GEMINI.md` 复制到同步到本地的知识库根目录。
5. 问一个已知答案的问题（例如楼梯踏步高度，D3D14），确认适配包生效。

业主维护的事实（日期、地区规则、常用入口）放在 `adapters/house_rules.yaml`；知识库事实（版本、草案、
文件数）由程序生成——不要手写。

## 错误报告（每周）
1. 用 reader 角色把 `<logs>/_error_reports/` 拷到本地。
2. `python scripts/collect_error_reports.py --reports <本地拷贝>` → 写入 `docs/acceptance/regression.json`。
3. 对每条 `reported`：核对原文页；改成 `confirmed`（修正原因，填写 `expected`）或 `rejected`。
   确认的条目加入题库。

## Token 成本
`python scripts/measure_tokens.py --library <本地拷贝> --out ../docs/benchmarks/token-cost`——
文件大小、列目录成本、在 10k–30k 目标范围内的比例。

## Docker（Mac 和服务器上推荐）
不改动 Mac 本机环境：全部运行在一个容器里，数据放在两个 Docker 卷中。
1. 安装 Docker Desktop。在项目文件夹里：`cp deploy/docker/fidelity.env.example deploy/docker/fidelity.env`，
   填上 PostgreSQL 密码（或删掉两行数据库设置，改用容器内的 SQLite）。
2. Mac 上的 PostgreSQL：先建好用户和数据库（见"服务器数据库"）。容器通过 `host.docker.internal` 访问 Mac，
   Docker Desktop 会把它转发到 Mac 本机，所以只监听 localhost 的 PostgreSQL 一般就能连上。如果被拒绝，
   把 `listen_addresses = '*'`，并在 `pg_hba.conf` 里允许 `192.168.65.0/24`（Docker Desktop 的网络），用 `scram-sha-256`。
3. 运行 `docker compose up -d --build`，然后打开 <http://127.0.0.1:8000>，创建第一个管理员，在"设置 → 网盘连接"里
   连接 Dropbox / Google Drive。更新：`git pull` 后再运行同一条命令。日志：`docker compose logs -f`。
   停止：`docker compose down`（数据保留在卷里）。
4. 可选的本地修正模型：在 Mac **本机**安装 Ollama（它能用 Apple GPU，容器用不了），然后在 env 文件里取消
   `FIDELITY_LLM_URL=http://host.docker.internal:11434` 的注释。
Docker 里的 OCR 引擎是 RapidOCR 和 Tesseract（CPU）。Apple Vision 只能在 macOS 本机运行，所以只有下面的本机安装
方式才有；基准测试里它排第三，用 Docker 准确率损失很小。

## Mac mini（第六阶段）
1. 运行 `./deploy/mac/install.sh`：安装 Homebrew 软件（Python 3.11、Tesseract、Node、Ollama）、Python 环境
   （有 `deploy/mac/requirements-macos.lock` 时按锁定版本安装——从 CI 产物 `macos-benchmarks-and-lock` 下载）、
   第六阶段组件（Apple Vision、PaddleOCR、pix2tex）、本地修正模型、网页界面，以及开机登录即启动、
   意外退出自动重启的 launchd 服务。可重复运行。`--check` 只检查前置条件。
2. 设置在 `deploy/mac/mac.env`（不进 git，由 `mac.env.example` 生成）：逐页视觉抽查、公式 OCR、本地模型、
   可选的 PostgreSQL。重启：`launchctl kickstart -k gui/$UID/com.fidelity.app`。日志：`data/logs/app.*.log`。
3. 安装脚本会对所有已装的 OCR 引擎做基准测试，把最准的两个记录在 `data/ocr_engines.json`
   （随时可重跑：`python scripts/ocr_benchmark.py --synthetic --out <目录> --select`；或用
   `FIDELITY_OCR_ENGINES=applevision,paddle` 强制指定）。吞吐量：`PERF_PDF=<pdf> ./deploy/mac/install.sh`，或
   `python scripts/perf_benchmark.py --pdf <pdf> --label "Mac mini" --out ../docs/benchmarks/perf-mac`。

**修正模型。** 设置 `FIDELITY_LLM_URL` 后，两个 OCR 引擎仍读得不一样的词会交给本地模型判断；模型只能在两个引擎
的读法（或术语表里的词）中选一个，数字一律不由模型决定。每次选择都记录在该页的修正日志里。

**公式。** `python scripts/formulas.py list <pdf>` 列出不可读公式（页码和顺序）；`read <pdf>` 运行公式 OCR 并给出
候选（两个引擎一致的标为 `agreed`）；对照原文页核对后，执行
`approve <pdf> --page N --k K --latex "…" --reviewer <姓名>`。下次蒸馏时以"已审核的转录"发布。未经批准一律不发布。

## 服务器数据库（PostgreSQL）
默认使用 `data/` 下的 SQLite 文件。上服务器时，把两个库都指向 PostgreSQL 16：
```
FIDELITY_DB_URL=postgresql+asyncpg://fidelity:<密码>@<主机>:5432/fidelity      # 用户、审计日志
FIDELITY_TRUST_URL=postgresql://fidelity:<密码>@<主机>:5432/fidelity           # 任务、审核决定
```
首次启动时自动建表（用户/审计用 Alembic；任务表不存在时自动创建）。服务器访问量大时设
`FIDELITY_DB_POOL=1` 打开连接池。CI 每次改动都会在 PostgreSQL 上跑完整测试（`backend-tests-postgres`）。
自己跑测试时，数据库名必须以 `_test` 结尾——测试会先清空它，其他名字一律拒绝。

## 备份
备份 `data/fidelity.db`（用户、审计日志）、`data/trust.db`（任务）和 `data/dropbox_auth.json`（注意保密）。
已发布的 Markdown 随时可以从源文件重新生成。

## 常见问题
| 现象 | 原因 / 处理 |
|---|---|
| Dropbox 报 `missing_scope` | 重新授权该角色（见"Dropbox 权限"） |
| 找不到 Tesseract | 安装它，或把 `tesseract.exe` 加到 PATH |
| 某扫描件总是进审核 | 两个引擎不一致时这是预期的；看报告里的 `disagreements` |
| Windows 长路径找不到文件 | 用提供的命令——它们已处理长路径 |
| GitHub API "rate limit" | 等一小时；轮询不要快于每分钟一次 |


## 部署更新
运行 `powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1`。可以先加 `-Check` 看会改什么。

脚本依次：
1. 如果当前不在 `main` 分支，或有本地改动，就停止。
2. 备份并校验。
3. 把代码更新到 `origin/main`。
4. Python 包和前端包的清单有变化时才安装。
5. 把前端构建到新文件夹，再替换旧的。
6. 重启服务器进程，正在进行的蒸馏会被接管。
7. 等待 `/healthz` 和新的页面包就绪。

7 分钟内没有恢复正常，脚本会自动换回上一个版本和上一份页面，再重启。每一步都记在 `data/work/deploy.log`。

## 备份
每天自动做一次备份并校验，放在 `data/backups`，保留最近 14 份。设置 → 系统状态里可以看到最近一次备份，也有「立即备份」。

恢复步骤：
1. 停掉计划任务。
2. 在 `backend` 目录运行 `python -c "from app.ops import backup as B; B.restore_to(r'<zip>', r'<空文件夹>')"`，把备份解压到一个空文件夹。
3. 把 `databases\*.db` 放回 `backend\data`，`backend-data\…` 放回 `backend\data\…`，`data\…` 放回 `data\…`。
4. 重新启动计划任务。

设置 `FIDELITY_BACKUP_COPY_DIR`，可以在另一块磁盘上多保留一份。
