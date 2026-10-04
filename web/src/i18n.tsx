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

    "tree.search": "搜索文件或目录…",
    "tree.loading": "读取中…",
    "tree.failed": "读取目录失败",
    "tree.retry": "重试",
    "tree.empty": "没有匹配的文件",
    "tree.selected": "已选 {n} 项",
    "tree.batchPass": "批量标记通过",
    "tree.threshold": "正确率阈值",
    "tree.multiHint": "按住 Ctrl 多选，Shift 连续选择；点文件夹名右侧复选框可整目录选择",

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
    "pane.page": "第 {cur} / {total} 页",
    "pane.prev": "上一页",
    "pane.next": "下一页",
    "pane.path": "路径",

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

    "reviewer.title": "审核人配置",
    "reviewer.add": "添加",
    "reviewer.name": "姓名",
    "reviewer.role": "角色",
    "reviewer.enabled": "启用",
    "reviewer.empty": "尚未配置审核人，请至少添加一位。",
    "reviewer.lastOne": "至少保留一位审核人",

    "decide.title": "待决定队列",
    "decide.include": "入库",
    "decide.exclude": "排除",
    "decide.empty": "没有待决定的文件。",

    "salvage.title": "需要重新转换",
    "salvage.desc": "原 .md 是二进制字符串打捞产物，用真实提取结果重写。写盘前会自动备份为 .md.salvage.bak。",
    "salvage.run": "重新转换所选",
    "salvage.empty": "没有需要重新转换的文件。",

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

    "tree.search": "Search files or folders…",
    "tree.loading": "Loading…",
    "tree.failed": "Failed to load directory",
    "tree.retry": "Retry",
    "tree.empty": "No matching files",
    "tree.selected": "{n} selected",
    "tree.batchPass": "Mark passing",
    "tree.threshold": "Accuracy threshold",
    "tree.multiHint": "Ctrl to multi-select, Shift for a range; use the folder checkbox to select a whole directory",

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
    "pane.page": "Page {cur} / {total}",
    "pane.prev": "Previous",
    "pane.next": "Next",
    "pane.path": "Path",

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

    "reviewer.title": "Reviewers",
    "reviewer.add": "Add",
    "reviewer.name": "Name",
    "reviewer.role": "Role",
    "reviewer.enabled": "Enabled",
    "reviewer.empty": "No reviewers yet — add at least one.",
    "reviewer.lastOne": "Keep at least one reviewer",

    "decide.title": "Decision queue",
    "decide.include": "Include",
    "decide.exclude": "Exclude",
    "decide.empty": "Nothing to decide.",

    "salvage.title": "Needs re-conversion",
    "salvage.desc": "These .md files were salvaged binary dumps. Rewriting them with real extracted text; the original is backed up as .md.salvage.bak.",
    "salvage.run": "Re-convert selected",
    "salvage.empty": "Nothing to re-convert.",

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
