/**
 * 极简 i18n：仅界面文案，**不翻译文件内容**（源文/入库 md 永远原样呈现）。
 *
 * 设计取舍：
 *  - 不引第三方库：这个项目只要「一套 key → 两种文案」，引入 i18next 反而更重。
 *  - key 用语义名（verdict.ok / pane.source），不把中文当 key —— 中文会随措辞调整而失效。
 *  - 语言持久化到 localStorage，刷新后保持。
 *  - t() 缺 key 时回落到 key 本身，便于开发期暴露漏译，而不是静默显示空白。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "zh" | "en";

const KEY = "fidelity.lang";

const DICT = {
  zh: {
    "app.title": "转换保真度评测",
    "app.subtitle": "Fidelity",

    "src.label": "数据源",
    "src.manage": "数据源…",
    "src.pickSrc": "选择源文件目录",
    "src.pickMd": "选择 .md 输出镜像目录",

    "act.batch": "批量评测",
    "act.rebatch": "重跑全部",
    "act.deferred": "补跑延后",
    "act.deferredList": "延后清单",
    "act.decide": "待决定",
    "act.salvage": "需重新转换",
    "act.upload": "上传文件",
    "act.reviewer": "审核人",
    "act.config": "配置",
    "act.lang": "语言",
    "act.recalc": "重新评测",
    "act.marks": "高亮命中",
    "act.all": "全部内容",
    "act.diff": "只看差异",
    "act.searchMd": "在 md 中查找…",
    "act.close": "关闭",
    "act.cancel": "取消",
    "act.save": "保存",
    "act.revoke": "撤销",
    "act.selectAll": "全选",
    "act.expandAll": "全部展开",
    "act.collapseAll": "全部折叠",
    "act.expandAllTip": "展开全部目录（{n} 个）",
    "act.collapseAllTip": "折叠全部目录，只保留顶层",

    "tree.search": "搜索文件或目录…",
    "tree.loading": "读取中…",
    "tree.failed": "读取目录失败",
    "tree.retry": "重试",
    "tree.empty": "没有匹配的文件",
    "tree.selected": "已选 {n} 项",
    "tree.batchPass": "批量标记通过",
    "tree.threshold": "正确率阈值",
    "tree.multiHint": "按住 Ctrl 多选，Shift 连续选择；点文件夹名右侧复选框可整目录选择",
    "tree.selectFile": "选择此文件（加入批量审核）",

    "filter.all": "全部",
    "filter.unreviewed": "未审",
    "filter.need_review": "待复核",
    "filter.trusted": "可信",
    "filter.diff_big": "差异大",
    "filter.rejected": "不接受",

    "pane.source": "源文件",
    "pane.md": "入库 .md",
    "pane.zoomIn": "放大",
    "pane.zoomOut": "缩小",
    "pane.zoomReset": "实际大小",
    "pane.zoom": "缩放",
    "pane.page": "第 {cur} / {total} 页",
    "pane.prev": "上一页",
    "pane.next": "下一页",
    "pane.path": "路径",
    "pane.sheet": "工作表",
    "pane.loadingPage": "正在载入…",
    "pane.emptyFile": "（空文件）",

    "md.chars": "字",
    "md.words": "词",
    "md.salvageTip": "该 .md 是旧转换管线的二进制打捞产物，自动分偏低，建议重新转换",
    "md.scopeLabel": "显示范围",
    "md.scopeAll": "整篇",
    "md.scopePage": "本页",
    "md.scopeAllTip": "显示整篇 md 的全部行（与左栏页码不同步）",
    "md.scopePageTip": "只显示左栏当前页对应的 md 行，一页对一页，便于逐页比对",
    "md.pageCount": "本页 {n} / 全篇 {total} 行",
    "md.scopeCountTip": "当前只显示本页 {n} 行，全篇共 {total} 行。点「整篇」可查看全部。",
    "md.pageEmpty": "本页没有对应的 md 行。可翻到其他页，或点「整篇」查看全文。",
    "md.pageBeyondCap": "本页没有比对结果：超大文件一次只比对前 {n} 行，本页在比对范围之外。这不代表转换漏了内容 —— 点「整篇」可查看并搜索全部正文。",

    "legend.match": "两侧一致",
    "legend.mdOnly": "md 多出 / 源文有",
    "legend.srcOnly": "md 缺 / 源文有",
    "legend.changed": "改写",
    "legend.nocmp": "未比对",

    "verdict.label": "人工裁决",
    "verdict.ok": "一致",
    "verdict.diff_big": "差异大",
    "verdict.rejected": "不接受",
    "verdict.reviewer": "审核人",
    "verdict.pick": "选择…",
    "verdict.manage": "管理",
    "verdict.note": "裁决备注（可选，写入审计日志）",
    "verdict.none": "未人工审核",

    "stat.evaluated": "已评测 / 全部",
    "stat.avg": "平均保真度",
    "stat.unreviewed": "未审",
    "stat.trusted": "可信",
    "stat.need_review": "待复核",
    "stat.diff_big": "差异大",
    "stat.pending": "待决定",
    "stat.deferred": "延后",
    "stat.chars": "总字数 源 → md",
    "stat.keep": "保留 {n}%",
    "stat.expand": "膨胀 +{n}%",
    "stat.keepTip": "md 字数 ÷ 源文件抽取字数。低于 100% 说明 md 比源文件少（可能漏内容）；高于 100% 说明 md 反而更多（含 front-matter、表格标记等）。",
    "stat.evaluatedTip": "已跑过自动评测的文件数 / 全部文件数。注意：这是「机器评测过」，与下面「未审」（人工裁决过没有）是两个维度。",
    "stat.unreviewedTip": "尚未经人工裁决的文件数（含自动评测过、但还没人确认的）。",
    "stat.progress": "进度",

    "file.auto": "自动 {n}%",
    "file.noScore": "无自动分",
    "file.chars": "字数",
    "file.none": "从左侧选择一个文件开始核对",
    "file.lines": "{n} 行",
    "file.selected": "共 {n} 行",

    "msg.recalcQueued": "已提交重新评测",
    "msg.batchQueued": "已提交批量评测",
    "msg.batchQueuedAll": "已提交重跑全部",
    "msg.deferredQueued": "已提交补跑",
    "msg.deferredNone": "当前没有被延后的文件。",
    "msg.deferredTitle": "被延后的文件 {n} 个（体积 / 原因 / 路径）：",
    "msg.reviewerNeeded": "请先选择审核人",
    "msg.verdictSaved": "已记录裁决：{v}（{r}）",
    "msg.verdictRevoked": "已撤销裁决",
    "msg.uploaded": "已上传 {rel}，等待转换生成 .md",
    "msg.reconvertQueued": "已提交重新转换：{n} 个",
    "msg.batchDone": "批量审核完成：通过 {ok} 个，跳过 {skip} 个",
    "msg.backendDown": "后端未就绪：{m}",
    "msg.confirmDeferred": "重试被延后的大文件（放宽时间预算，耗时较长）。继续？",
    "msg.confirmRebatch": "重跑全部将重新评分所有文件（含已评测），耗时较长。继续？",
    "msg.confirmBatchPass": "{n} 个文件，正确率 ≥ {th}% 的将标记为「{label}」。继续？",

    "reviewer.title": "审核人配置",
    "reviewer.add": "添加",
    "reviewer.name": "姓名",
    "reviewer.role": "角色",
    "reviewer.enabled": "启用",
    "reviewer.empty": "尚未配置审核人，请至少添加一位。",
    "reviewer.lastOne": "至少保留一位审核人",
    "reviewer.sub": "裁决与入库决定都只能由名单内的人做出，保证审计身份唯一",
    "reviewer.currentUsing": "当前使用：{name}。在下方点「设为当前」切换，或在底部裁决栏直接下拉选择。",
    "reviewer.current": "当前",
    "reviewer.disabled": "已停用",
    "reviewer.unregistered": "未登记",
    "reviewer.unregisteredTip": "历史数据中的审核人，未登记进名单",
    "reviewer.setCurrent": "设为当前",
    "reviewer.enable": "启用",
    "reviewer.disable": "停用",
    "reviewer.remove": "删除",
    "reviewer.renameTip": "点击改名",
    "reviewer.namePh": "真实姓名或工号",
    "reviewer.rolePh": "审核人",
    "reviewer.roleDefault": "审核人",
    "reviewer.emptyList": "名单为空，请先添加审核人",
    "reviewer.footNote": "姓名可点击就地修改；至少保留一位启用中的审核人。",
    "reviewer.counts": "裁决 {v} · 一致 {ok} · 差异大 {diff} · 不接受 {rej} · 入库决定 {dec}",
    "reviewer.confirmRemove": "删除审核人「{name}」？\n\n已产生的裁决记录与审计日志会保留（历史可追溯），\n但此人将不再出现在选择列表中。",
    "reviewer.unregisteredBlock": "未登记的历史审核人不可编辑",

    "decide.title": "人工决定队列",
    "decide.sub": "无法自动比对的文件，入库与否由人工拍板",
    "decide.close": "关闭",
    "decide.tabPending": "待决定",
    "decide.tabInclude": "已入库",
    "decide.tabExclude": "已排除",
    "decide.total": "共 {n} 个",
    "decide.reviewerOf": "· 审核人 {name}",
    "decide.noReviewer": "未选择",
    "decide.allInclude": "全部入库",
    "decide.allExclude": "全部不入库",
    "decide.refresh": "刷新",
    "decide.empty": "没有文件",
    "decide.unknown": "未知",
    "decide.include": "入库",
    "decide.exclude": "不入库",
    "decide.included": "已入库",
    "decide.excluded": "已排除",
    "decide.undo": "撤销",
    "decide.includeTip": "纳入管理：可自动处理的格式会自动重跑识别评测",
    "decide.excludeTip": "标记无效材料，不计入失败统计，可随时撤销",
    "decide.confirmAll": "将把当前 {n} 个待决定文件全部标记「{label}」{extra}。之后可逐个撤销。继续？",
    "decide.confirmAllExtra": "，并对扫描件/图片/CAD/压缩包重跑识别评测",
    "decide.batchNote": "批量标记{label}",

    "salvage.title": "重新转换",
    "salvage.sub": "原转换产物是二进制打捞的文件，用真实提取结果重写",
    "salvage.close": "关闭",
    "salvage.descShort": "原 .md 是二进制字符串打捞产物，用真实提取结果重写。写盘前会自动备份为 .md.salvage.bak。",
    "salvage.desc": "这些 .md 是原转换管线的「二进制字符串打捞」产物（内容形如 AC1032 / RdAkRdAkRdA），不是文档内容，所以自动分很低。",
    "salveKey.title": "问题在转换侧，不在源文件侧。",
    "salvage.descTail": "重写会保留原 front-matter，正文换成真实提取结果，并把原文件备份为 .md.salvage.bak。",
    "salvage.total": "共 {n} 个",
    "salvage.runAll": "全部重新转换",
    "salvage.refresh": "刷新",
    "salvage.running": "正在重新转换并重评，较大的文件需要一些时间…",
    "salvage.empty": "没有需要重新转换的文件",
    "salvage.current": "当前 {n}%",
    "salvage.engine": "引擎 {e} · ",
    "salvage.runOne": "重新转换",
    "salvage.confirmAll": "将对 {n} 个文件重新转换：\n· 用真实提取结果（CAD 文字 / OCR）重写 .md\n· 原文件自动备份为 .md.salvage.bak，可回滚\n· 转换后立刻重评打分\n\n继续？",

    "src.mgrTitle": "数据源管理",
    "src.mgrSub": "源目录 → .md 镜像目录的映射",
    "src.close": "关闭",
    "src.configured": "已配置 {n} 个数据源",
    "src.srcLabel": "源：{p}",
    "src.mdLabel": ".md：{p}",
    "src.edit": "编辑",
    "src.remove": "删除",
    "src.addEdit": "新增 / 修改",
    "src.idLabel": "数据源 ID（英文，唯一）",
    "src.nameLabel": "显示名称",
    "src.srcDirLabel": "源文件目录（放原始 PDF / Word / CAD 等）",
    "src.mdDirLabel": ".md 输出镜像目录（转换结果按同构路径落盘）",
    "src.pick": "选择…",
    "src.pickPh": "点击右侧选择",
    "src.clear": "清空",
    "src.save": "保存数据源",
    "src.needFields": "请填写 id、名称、源目录与镜像目录",
    "src.confirmRemove": "删除数据源「{name}」？已入库的文件不受影响。",

    "folder.current": "当前：{p}",
    "folder.noDrive": "（先选择盘符）",
    "folder.up": "‹‹ 上一级",
    "folder.noDriveFound": "未找到可用盘符",
    "folder.pickThis": "选定当前目录",

    "ext.cad": "CAD 图纸",
    "ext.rfa": "Revit 族",
    "ext.rvt": "Revit 模型",
    "ext.pdf": "扫描 PDF",
    "ext.img": "图片",
    "ext.zip": "压缩包",
    "ext.video": "视频",

    "compare.truncated": "该 md 共 {total} 行，一次最多比对前 {n} 行；其余 {rest} 行仍可查看与搜索，但不着色（灰色「未比对」）。",
    "compare.notApplicable": "本文件不做逐行比对：{r}。下方为 md 原文（无绿/红标记）。",
    "compare.tooBig": "源文件过大，抽取超时（需人工抽检）",
    "compare.noMd": "该文件还没有对应的 .md —— 请先运行「批量评测」触发转换。",
    "compare.legend": "绿色 = md 中已收录该处内容；红色 = 源文有但 md 中没有",
  },

  en: {
    "app.title": "Conversion Fidelity Review",
    "app.subtitle": "Fidelity",

    "src.label": "Source",
    "src.manage": "Sources…",
    "src.pickSrc": "Pick source folder",
    "src.pickMd": "Pick .md mirror folder",

    "act.batch": "Batch score",
    "act.rebatch": "Re-run all",
    "act.deferred": "Retry deferred",
    "act.deferredList": "Deferred list",
    "act.decide": "To decide",
    "act.salvage": "Re-convert",
    "act.upload": "Upload",
    "act.reviewer": "Reviewer",
    "act.config": "Manage",
    "act.lang": "Language",
    "act.recalc": "Re-score",
    "act.marks": "Highlights",
    "act.all": "All content",
    "act.diff": "Differences only",
    "act.searchMd": "Search in md…",
    "act.close": "Close",
    "act.cancel": "Cancel",
    "act.save": "Save",
    "act.revoke": "Revoke",
    "act.selectAll": "Select all",
    "act.expandAll": "Expand all",
    "act.collapseAll": "Collapse all",
    "act.expandAllTip": "Expand every folder ({n})",
    "act.collapseAllTip": "Collapse all folders, keep top level only",

    "tree.search": "Search files or folders…",
    "tree.loading": "Loading…",
    "tree.failed": "Failed to load directory",
    "tree.retry": "Retry",
    "tree.empty": "No matching files",
    "tree.selected": "{n} selected",
    "tree.batchPass": "Mark passing",
    "tree.threshold": "Accuracy threshold",
    "tree.multiHint": "Ctrl to multi-select, Shift for a range; use the folder checkbox to select a whole directory",
    "tree.selectFile": "Select this file (add to the batch review)",

    "filter.all": "All",
    "filter.unreviewed": "Unreviewed",
    "filter.need_review": "Review",
    "filter.trusted": "Trusted",
    "filter.diff_big": "Major diff",
    "filter.rejected": "Rejected",

    "pane.source": "Source file",
    "pane.md": "Stored .md",
    "pane.zoomIn": "Zoom in",
    "pane.zoomOut": "Zoom out",
    "pane.zoomReset": "Actual size",
    "pane.zoom": "Zoom",
    "pane.page": "Page {cur} / {total}",
    "pane.prev": "Previous",
    "pane.next": "Next",
    "pane.path": "Path",
    "pane.sheet": "Sheet",
    "pane.loadingPage": "Loading…",
    "pane.emptyFile": "(empty file)",

    "md.chars": "chars",
    "md.words": "words",
    "md.salvageTip": "This .md is a salvaged binary dump from the old conversion pipeline, so its score is low — consider re-converting",
    "md.scopeLabel": "Display scope",
    "md.scopeAll": "Whole file",
    "md.scopePage": "This page",
    "md.scopeAllTip": "Show every line of the md (not synced to the left-hand page number)",
    "md.scopePageTip": "Show only the md lines for the current left-hand page, one page to one page",
    "md.pageCount": "This page {n} / {total} lines",
    "md.scopeCountTip": "Showing {n} lines of this page; the file has {total} lines in total. Use “Whole file” to see everything.",
    "md.pageEmpty": "No md lines for this page. Turn to another page, or choose “Whole file” to read it all.",
    "md.pageBeyondCap": "No comparison result for this page: for very large files only the first {n} lines are compared, and this page is outside that range. This does not mean content was lost — choose “Whole file” to read and search the whole text.",

    "legend.match": "Match",
    "legend.mdOnly": "Extra in md",
    "legend.srcOnly": "Missing in md",
    "legend.changed": "Rewritten",
    "legend.nocmp": "Not compared",

    "verdict.label": "Reviewer verdict",
    "verdict.ok": "Match",
    "verdict.diff_big": "Major diff",
    "verdict.rejected": "Rejected",
    "verdict.reviewer": "Reviewer",
    "verdict.pick": "Select…",
    "verdict.manage": "Manage",
    "verdict.note": "Note (optional, written to audit log)",
    "verdict.none": "Not reviewed",

    "stat.evaluated": "Scored / total",
    "stat.avg": "Avg fidelity",
    "stat.unreviewed": "Unreviewed",
    "stat.trusted": "Trusted",
    "stat.need_review": "Review",
    "stat.diff_big": "Major diff",
    "stat.pending": "To decide",
    "stat.deferred": "Deferred",
    "stat.chars": "Chars src → md",
    "stat.keep": "{n}% kept",
    "stat.expand": "+{n}% expanded",
    "stat.keepTip": "md chars ÷ extracted source chars. Below 100% means the md is smaller than the source (content may be missing); above 100% means the md is larger (front-matter, table markup).",
    "stat.evaluatedTip": "Files that have been auto-scored / all files. This is 'machine-scored', a different dimension from 'Unreviewed' below (has a human verdict or not).",
    "stat.unreviewedTip": "Files with no human verdict yet (may already have been auto-scored).",
    "stat.progress": "Progress",

    "file.auto": "Auto {n}%",
    "file.noScore": "No score",
    "file.chars": "Chars",
    "file.none": "Select a file on the left to start reviewing",
    "file.lines": "{n} lines",
    "file.selected": "{n} lines",

    "msg.recalcQueued": "Re-score submitted",
    "msg.batchQueued": "Batch scoring submitted",
    "msg.batchQueuedAll": "Full re-run submitted",
    "msg.deferredQueued": "Retry submitted",
    "msg.deferredNone": "No deferred files.",
    "msg.deferredTitle": "Deferred files ({n}) — size / reason / path:",
    "msg.reviewerNeeded": "Pick a reviewer first",
    "msg.verdictSaved": "Verdict saved: {v} ({r})",
    "msg.verdictRevoked": "Verdict revoked",
    "msg.uploaded": "Uploaded {rel}; waiting for conversion",
    "msg.reconvertQueued": "Re-convert submitted: {n}",
    "msg.batchDone": "Batch review done: {ok} passed, {skip} skipped",
    "msg.backendDown": "Backend not ready: {m}",
    "msg.confirmDeferred": "Retry the deferred large files (the time budget is relaxed, so this takes a while). Continue?",
    "msg.confirmRebatch": "A full re-run re-scores every file (including ones already scored), so it takes a while. Continue?",
    "msg.confirmBatchPass": "{n} files at or above {th}% accuracy will be marked “{label}”. Continue?",

    "reviewer.title": "Reviewers",
    "reviewer.add": "Add",
    "reviewer.name": "Name",
    "reviewer.role": "Role",
    "reviewer.enabled": "Enabled",
    "reviewer.empty": "No reviewers yet — add at least one.",
    "reviewer.lastOne": "Keep at least one reviewer",
    "reviewer.sub": "Verdicts and ingest decisions can only be made by people on this list, so the audit identity stays unique",
    "reviewer.currentUsing": "In use: {name}. Use “Set as current” below, or pick from the dropdown in the verdict bar.",
    "reviewer.current": "Current",
    "reviewer.disabled": "Disabled",
    "reviewer.unregistered": "Unregistered",
    "reviewer.unregisteredTip": "A reviewer found in historical data who is not on the list",
    "reviewer.setCurrent": "Set as current",
    "reviewer.enable": "Enable",
    "reviewer.disable": "Disable",
    "reviewer.remove": "Remove",
    "reviewer.renameTip": "Click to rename",
    "reviewer.namePh": "Real name or staff ID",
    "reviewer.rolePh": "Reviewer",
    "reviewer.roleDefault": "Reviewer",
    "reviewer.emptyList": "The list is empty — add a reviewer first",
    "reviewer.footNote": "Click a name to edit it in place; keep at least one enabled reviewer.",
    "reviewer.counts": "Verdicts {v} · Match {ok} · Major diff {diff} · Rejected {rej} · Ingest decisions {dec}",
    "reviewer.confirmRemove": "Remove reviewer “{name}”?\n\nExisting verdicts and audit records are kept (for traceability),\nbut this person will no longer appear in the picker.",
    "reviewer.unregisteredBlock": "Unregistered historical reviewers cannot be edited",

    "decide.title": "Decision queue",
    "decide.sub": "Files that cannot be compared automatically — a human decides whether to ingest them",
    "decide.close": "Close",
    "decide.tabPending": "To decide",
    "decide.tabInclude": "Ingested",
    "decide.tabExclude": "Excluded",
    "decide.total": "{n} total",
    "decide.reviewerOf": "· Reviewer {name}",
    "decide.noReviewer": "none selected",
    "decide.allInclude": "Include all",
    "decide.allExclude": "Exclude all",
    "decide.refresh": "Refresh",
    "decide.empty": "No files",
    "decide.unknown": "Unknown",
    "decide.include": "Include",
    "decide.exclude": "Exclude",
    "decide.included": "Ingested",
    "decide.excluded": "Excluded",
    "decide.undo": "Undo",
    "decide.includeTip": "Accept for management: formats that can be handled automatically will be re-scored",
    "decide.excludeTip": "Mark as invalid material; excluded from failure stats, and reversible at any time",
    "decide.confirmAll": "Mark all {n} pending files as “{label}”{extra}. You can undo them individually afterwards. Continue?",
    "decide.confirmAllExtra": ", and re-run recognition on scans/images/CAD/archives",
    "decide.batchNote": "Bulk marked {label}",

    "salvage.title": "Re-convert",
    "salvage.sub": "The original conversion output is a binary dump — rewrite it with real extracted text",
    "salvage.close": "Close",
    "salvage.descShort": "These .md files are salvaged binary dumps; rewrite them with real extracted text. The original is backed up as .md.salvage.bak first.",
    "salvage.desc": "These .md files are “binary string salvage” output from the old pipeline (content like AC1032 / RdAkRdAkRdA), not document content, so their scores are low.",
    "salveKey.title": "The problem is in the conversion, not the source file.",
    "salvage.descTail": "Rewriting keeps the original front-matter, replaces the body with real extracted text, and backs up the original as .md.salvage.bak.",
    "salvage.total": "{n} total",
    "salvage.runAll": "Re-convert all",
    "salvage.refresh": "Refresh",
    "salvage.running": "Re-converting and re-scoring — larger files take a while…",
    "salvage.empty": "Nothing to re-convert",
    "salvage.current": "currently {n}%",
    "salvage.engine": "engine {e} · ",
    "salvage.runOne": "Re-convert",
    "salvage.confirmAll": "Re-convert {n} files:\n· Rewrite the .md with real extracted text (CAD text / OCR)\n· Back up the original as .md.salvage.bak (reversible)\n· Re-score immediately after conversion\n\nContinue?",

    "src.mgrTitle": "Sources",
    "src.mgrSub": "Source folder → .md mirror folder mapping",
    "src.close": "Close",
    "src.configured": "{n} source(s) configured",
    "src.srcLabel": "Source: {p}",
    "src.mdLabel": ".md: {p}",
    "src.edit": "Edit",
    "src.remove": "Delete",
    "src.addEdit": "Add / edit",
    "src.idLabel": "Source ID (letters, unique)",
    "src.nameLabel": "Display name",
    "src.srcDirLabel": "Source folder (original PDF / Word / CAD files)",
    "src.mdDirLabel": ".md output mirror folder (converted files land here with the same structure)",
    "src.pick": "Pick…",
    "src.pickPh": "Use the button on the right",
    "src.clear": "Clear",
    "src.save": "Save source",
    "src.needFields": "Please fill in the ID, name, source folder and mirror folder",
    "src.confirmRemove": "Delete source “{name}”? Files already ingested are not affected.",

    "folder.current": "Current: {p}",
    "folder.noDrive": "(pick a drive first)",
    "folder.up": "‹‹ Up one level",
    "folder.noDriveFound": "No drives found",
    "folder.pickThis": "Use this folder",

    "ext.cad": "CAD drawing",
    "ext.rfa": "Revit family",
    "ext.rvt": "Revit model",
    "ext.pdf": "Scanned PDF",
    "ext.img": "Image",
    "ext.zip": "Archive",
    "ext.video": "Video",

    "compare.truncated": "This md has {total} lines; at most {n} are compared at once. The remaining {rest} lines are still readable and searchable but uncolored (grey “not compared”).",
    "compare.notApplicable": "Line comparison is not applicable: {r}. The md text is shown below without green/red marks.",
    "compare.tooBig": "Source file too large; extraction timed out (manual spot-check required)",
    "compare.noMd": "No .md for this file yet — run “Batch score” to trigger conversion.",
    "compare.legend": "Green = captured in md; red = present in source but missing from md",
  },
} as const;

export type TKey = keyof (typeof DICT)["zh"];

type Ctx = {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (k: TKey, vars?: Record<string, string | number>) => string;
};

const LangCtx = createContext<Ctx>({
  lang: "zh",
  setLang: () => {},
  t: (k) => String(k),
});

/** 把 {n} 占位符替换成实参；没给实参就保留占位符，方便一眼看出漏传。 */
function fill(tpl: string, vars?: Record<string, string | number>) {
  if (!vars) return tpl;
  return tpl.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    try {
      const v = localStorage.getItem(KEY);
      return v === "en" ? "en" : "zh";
    } catch {
      return "zh";
    }
  });

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* 隐私模式下写不进去，忽略即可（本次会话仍生效） */
    }
    // 切语言会改变所有按钮宽度，立刻重排一次，避免出现点击区错位
    window.dispatchEvent(new Event("resize"));
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const t = useCallback(
    (k: TKey, vars?: Record<string, string | number>) => {
      const table = DICT[lang] as Record<string, string>;
      return fill(table[k] ?? (DICT.zh as Record<string, string>)[k] ?? String(k), vars);
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LangCtx.Provider value={value}>{children}</LangCtx.Provider>;
}

export function useLang() {
  return useContext(LangCtx);
}

/** 组件里更顺手的写法：const [t, lang, setLang] = useI18n(); */
export function useI18n() {
  const { lang, setLang, t } = useLang();
  return [t, lang, setLang] as const;
}
