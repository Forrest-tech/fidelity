# Fidelity · 转换保真度评测系统

> **Fidelity**（保真度）衡量的是"转换有没有失真"。本系统对「原始文档 → Markdown 转换产物」
> 做**自动比对评分 + 人工复核 + 可信度标记**，让知识库检索只采信可信内容。

针对的是这样一个现实问题：文档被转换成 Markdown 后，**你无法再确认转换是否忠实**。
OCR 会把 `25mm` 认成 `2Smm`，表格会被重复展开，某些专有格式干脆什么都没提取出来。
本系统把这些"看不见的失真"变成**可量化、可复核、可追溯**的结论。

> **命名说明**：早期版本叫 "QA-Platform / 转换质检"。但「质检」暗示检查一个已完成的产物，
> 而这套系统真正在做的事是**拿源文件与转换产物逐行对账**——很多文件的正确结论是
> 「存疑待人工确认」，而非「通过/失败」。故更名为 Fidelity（保真度）。

---

## 一、它解决什么问题

| 能力 | 说明 |
|---|---|
| **自动评分** | 0.5×词级内容覆盖率 + 0.5×数字保真率 → 0–100 分 |
| **数字保真检测** | 专抓 OCR 数字错误（`25mm`→`2Smm`）、千分位错写（`1,000`→`1.000`） |
| **分屏逐行对比** | 绿色=一致，红色=转换遗漏/多出，黄色=OCR 改写；按源文阅读顺序排列 |
| **字数统计** | 源文/Markdown 的字符数与字数（CJK 按字 + 拉丁按词） |
| **原文件预览** | 13 种格式：PDF、图片、CAD、Word、Excel、PPT、邮件、压缩包、纯文本 |
| **格式专用算法** | 每种格式走最合适的处理器，而非一个模型打天下 |
| **可信度标记** | 人工判"一致" + 自动分 ≥80 → 标记为可信，供检索层采信 |

### 关键设计：假差异必须为零

源文 `600X600 ACCESS CHAMBER` 与 md `- 600X600 ACCESS CHAMBER` 内容完全一致，
但 md 多了一个列表符 `-`。早期版本把它判成差异，在界面上刷出满屏红色 ——
**这会让整个质检结论失真**。因此系统剥离所有纯排版标记（列表符、标题井号、强调符、
表格竖线、front-matter、HTML 注释）。

但有些东西**故意不剥**，因为剥了会丢真实内容：

| 保留 | 原因 |
|---|---|
| `12) Check the cover` | 右括号编号在技术规范里是真实条款号 |
| `A_B_C` / `2_5` | 下划线在技术文档极常见，剥会破坏内容 |
| `2.5m` | 是尺寸，不是"第 2 项"列表 |

---

## 二、快速开始

### 前置要求
- **Python 3.11+**（开发环境 3.13）
- **Node.js 18+**（仅构建前端时需要）
- **Windows / macOS / Linux** 均可；DWG 支持在 Windows 上最完整

### 1. 安装后端依赖

```bash
cd fidelity/backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 启动后端

```bash
cd fidelity/backend
python -m scripts.serve
```

首次运行会自动创建 `data/trust.db`（评测数据库）。

| 情况 | 行为 | 退出码 |
|---|---|---|
| 正常启动 | `http://127.0.0.1:8000` | — |
| **已有实例在运行** | 打印提示并安静退出 | **0** |
| 端口被其它程序占用 | 明确报错，提示换端口 | 2 |

> **单实例保护**：`data/server.lock` 记录持有者 PID + 心跳（90 秒过期）。
> 第二个实例既不会启动 worker，也不会把第一个实例正在跑的任务误标为"已中断"。
> 这解决了此前反复出现的"任务莫名 Failed"问题。

### 3. 配置知识库路径

编辑 `backend/data/config.json`：

```json
{
  "sources": [
    {
      "id": "n2",
      "name": "我的合规库",
      "src_root": "C:/path/to/原始文档目录",
      "md_root":  "C:/path/to/Markdown目录",
      "enabled": true
    }
  ]
}
```

改完后重启服务。可配置多组 `sources`。

### 4. 构建前端（可选）

```bash
cd fidelity/web
npm install
npm run build      # 产物在 web/dist
```

后端会直接托管 `web/dist`，构建后访问 `http://127.0.0.1:8000` 即是完整界面。
开发模式用 `npm run dev`（热更新）。

> **注意**：`web/dist` 不存在时后端**不会报错**，只是不挂载前端 ——
> 此时 `http://127.0.0.1:8000/` 返回 404，API 接口（`/api/*`）仍正常可用。
> 这是有意设计：后端可独立跑批处理，不强制依赖前端构建产物。

### 5. 运行批量评测

在界面点击「批量评测」，或调用 API：

```bash
# 增量评测（默认）：只跑尚未评测过的文件
curl -X POST "http://127.0.0.1:8000/api/batch"

# 全量重跑：忽略已有结果，全部重新评测
curl -X POST "http://127.0.0.1:8000/api/batch?mode=force"

# 只补跑此前被延后的大文件
curl -X POST "http://127.0.0.1:8000/api/batch?mode=defer"
```

`mode` 取值：`all`（增量，默认）/ `force`（全量重跑）/ `defer`（只补跑延后项）。
`defer_mb` / `defer_sec` 可覆盖延后阈值（0 表示沿用模式默认值）。

接口返回 `{"job_id": "..."}`，用进度查询接口跟踪：

```bash
curl "http://127.0.0.1:8000/api/job/<job_id>"
```

---

## 三、DWG 支持（可选）

DWG 是专有二进制格式，需要外部转换器。系统按以下顺序自动探测：

1. `fidelity/tools/libredwg/dwg2dxf.exe` ← **推荐，随项目放置于此**
2. 工作区级 `tools/libredwg/`
3. 项目级 `tools/libredwg/`
4. `C:\tools\libredwg`、`C:\Program Files\libredwg`
5. 系统 `PATH`

**没有转换器时**：DWG 文件会明确标注"DWG 需要转换器"并进入人工决定队列 ——
**不会静默伪装成"这个文件没有内容"**。

获取 LibreDWG（GNU，官方提供 win64 便携版）：https://www.gnu.org/software/libredwg/
解压后把 `dwg2dxf.exe` 等文件放入 `tools/libredwg/` 即可。

> 该二进制共 51MB，**不随本仓库分发**（`.gitignore` 已排除），请按上述链接单独获取。

---

## 四、测试

```bash
cd fidelity/backend
python scripts/run_all_tests.py
```

共 **257 项**：

| 套件 | 项数 | 覆盖内容 |
|---|---|---|
| `unit_tests.py` | 101 | 归一化、md 伪影剥离（含「故意不剥」反例）、行对齐四态、数字保真、覆盖率、评分公式、字数、重复检测、分页、性能红线、并发安全 |
| `test_router.py` | 82 | 扩展名分诊、不支持格式降级、缺失文件优雅降级、CAD 人工确认标记、DWG 临时目录清理（含**用户文件不被误删**的回归） |
| `ui_contract_check.py` | 74 | API↔UI 契约一致性（**需服务已在 8000 运行**） |

单跑某套：`python scripts/unit_tests.py`

### 性能红线（测试中已锁定）

| 场景 | 实测 | 红线 |
|---|---|---|
| 5,000 行 vs 5,000 行（全部错位，最坏情况） | 0.22s | < 3s |
| 20,000 行全等 | 0.20s | < 3s |
| 并发 8 线程对齐 | 无异常 | 不报错 |

对齐算法是 O(n)（归一化行哈希 + 倒排索引 + token 级 Dice 系数），
**不使用 `difflib.SequenceMatcher`**（O(n²)，历史上在 200 页 PDF 上跑十几万次，
把请求拖到 2 分钟以上直接超时）。

---

## 五、架构

```
fidelity/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI 入口 + 单实例守卫
│   │   ├── instance.py          PID + 心跳的所有权锁
│   │   ├── config.py            配置（端口/路径可用环境变量覆盖）
│   │   ├── db.py                SQLite 访问（WAL + 重试）
│   │   ├── domain/
│   │   │   ├── compare.py       ★ 核心算法：归一化/对齐/评分/字数
│   │   │   └── trust.py         可信度、判定、审计、字数统计
│   │   ├── ingest/
│   │   │   ├── format_router.py ★ 格式分诊与引擎选择
│   │   │   ├── ocr.py           RapidOCR + 置信度 + 预算控制
│   │   │   ├── cad.py           LibreDWG → DXF → ezdxf
│   │   │   ├── parsers.py       PDF/Office/Msg 解析
│   │   │   ├── preview.py       13 种格式预览渲染
│   │   │   ├── reconvert.py     打捞产物重转换
│   │   │   └── zip_handler.py   压缩包递归解包
│   │   ├── jobs/                SQLite 异步任务队列
│   │   └── api/routes.py        HTTP 接口
│   ├── scripts/                 测试与运维脚本
│   └── data/                    ⚠️ 运行时生成，已 gitignore
└── web/src/                     React + TypeScript 前端
```

### 格式路由策略

| 格式 | 处理方式 |
|---|---|
| `.pdf`（有文本层） | **pymupdf** 主 → pypdf 兜底 → pdfplumber 小文件兜底 |
| `.pdf`（扫描件） | RapidOCR + 预处理 + 置信度，超预算标 `partial` |
| `.jpg/.png/.tif…` | RapidOCR |
| `.dwg` | dwg2dxf → DXF → ezdxf（多布局全提取） |
| `.dxf` | ezdxf 直接提取 TEXT/MTEXT/标注 |
| `.docx/.xlsx/.xlsm/.pptx/.msg` | 各自解析器 |
| `.zip/.7z/.rar` | 递归解包，成员逐一走本路由 |
| `.rfa/.rvt/.mp4/.exe…` | **显式标"需人工决定"并给出原因**，不静默返回空 |

---

## 六、已知限制（诚实说明）

1. **扫描件 OCR 质量不足以无人值守**
   RapidOCR 在 CPU 下约 60 秒/页，实测 170 个 OCR 文件均分 40.9，其中 124 个低于 50 分。
   系统因此**默认把扫描件送人工队列，而不是自动判合格**。
   CPU 环境无法实现通用 99% OCR —— 这是物理限制，不是配置问题。

2. **专有格式无自动提取方案**
   RFA（Revit 族文件）等 153 个文件占库内 9%，没有免费可靠的文本提取方式，
   只能人工决定去留。系统会明确告知原因，不伪造内容。

3. **无浏览器端 E2E 测试**
   当前 `ui_contract_check.py` 是 API↔UI 契约测试（校验字段与结构），
   不是真实浏览器点击测试。

4. **DWG 转换器需单独获取**（见第三节）

---

## 七、安全说明

- 只读挂载原始文档目录，系统**不修改任何源文件**
- 所有路径参数都经过边界校验，`../` 穿越被拦（返回空结果而非文件内容）
- 数据库查询全部参数化，无 SQL 注入面
- 服务仅监听 `127.0.0.1`，不对外暴露

---

## 八、常用命令

```bash
# 启动 / 预检
python -m scripts.serve
python -m scripts.serve --check

# 测试
python scripts/run_all_tests.py

# 一次性脚本
python -m scripts.backfill_wordcount     # 补字数统计（无待办立即退出）

# 环境变量
QA_SERVER_PORT=8080   QA_SERVER_HOST=127.0.0.1
```

---

## 九、许可与数据归属

代码采用 [MIT 许可](LICENSE)。

本仓库仅含**代码**。你的文档、Markdown 产物、评测数据库（`backend/data/`）、
提取缓存均已在 `.gitignore` 中排除，**不会随仓库分发**。