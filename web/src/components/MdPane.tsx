import { useEffect, useMemo, useRef, useState } from "react";
import type { AlignResp, MdResp } from "../types";

/**
 * 右栏：入库 .md 逐行显示，**绿色 = 该行在源文件里也找到了**。
 *
 * 与左栏的对应关系：
 *   左栏源文件绿色块 ←→ 本栏绿色行（同一段内容两侧都绿）
 *   点本栏行尾的页码 → 左栏跳到源文件对应页并高亮
 *
 * ⚠️ 索引安全：status[i] 与 lines[i] 由后端保证同一下标语义（都用 splitlines()），
 * 这里只做防御性兜底（长度不一致时按最短的渲染并提示），避免错位上色。
 */
export default function MdPane({
  md,
  align,
  onlyDiff,
  search,
  curLine,
  onPickLine,
}: {
  md: MdResp;
  align: AlignResp | null;
  onlyDiff: boolean;
  search: string;
  curLine: number | null;
  onPickLine: (i: number, page: number | null) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const rowRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const lines = md.lines || [];
  const status = align?.status || [];
  const pages = align?.src_page || [];
  // ⚠️ 必须遍历 md 的**全部**行，而不是 min(lines, status)。
  // 后端对超大 md 只比对前 ALIGN_MAX_LINES(6000) 行；若这里跟着截断，
  // 30000 行的 md 就只剩前 6000 行可见 —— 用户会以为文件到 6000 行就结束了，
  // 这是「静默丢数据」，比标错色更严重。
  // 超出比对上限的行标为 nocmp（中性），绝不标 unmatched ——
  // unmatched 的语义是「比对过，源文里确实没有」，这两件事不能混为一谈。
  const n = lines.length;
  const compared = status.length;

  const rows = useMemo(() => {
    const out: { i: number; text: string; st: string; page: number | null }[] = [];
    const q = search.trim().toLowerCase();
    for (let i = 0; i < n; i++) {
      const st = i < compared ? status[i] || "unmatched" : "nocmp";
      if (onlyDiff && (st === "match" || st === "nocmp")) continue;
      if (q && !lines[i].toLowerCase().includes(q)) continue;
      out.push({ i, text: lines[i], st, page: pages[i] ?? null });
    }
    return out;
  }, [n, compared, lines, status, pages, onlyDiff, search]);

  // 只渲染前若干行：md 最大 2.6MB，全量 DOM 会让浏览器卡死
  const CAP = 1200;
  const shown = showAll ? rows : rows.slice(0, CAP);

  useEffect(() => {
    setShowAll(false);
  }, [md.rel, onlyDiff, search]);

  // 当前行滚动到可视区
  useEffect(() => {
    if (curLine != null) rowRefs.current[curLine]?.scrollIntoView({ block: "center" });
  }, [curLine]);

  if (md.missing) {
    return (
      <div className="empty">
        该文件还没有对应的 .md —— 请先运行「批量评测」触发转换，或用「需重新转换」生成。
      </div>
    );
  }

  const counts = align?.by_status || {};

  return (
    <>
      <div className="pane-head">
        <b>入库 .md</b>
        {md.salvage && (
          <span className="badge diff_big" title="原产物是二进制字符串打捞，建议用「需重新转换」重写">
            salvage 无效产物
          </span>
        )}
        <span className="dim num">
          {md.chars.toLocaleString()} 字 · {md.words.toLocaleString()} 词
        </span>
        <div className="spacer" />
        {!!counts.match && (
          <span className="legend">
            <span><i style={{ background: "var(--green-bg)", borderColor: "var(--green-border)" }} />一致 {counts.match}</span>
            <span><i style={{ background: "var(--red-bg)", borderColor: "var(--red-border)" }} />多出 {counts.md_only || 0}</span>
            <span><i style={{ background: "var(--amber-bg)", borderColor: "var(--amber-border)" }} />改写 {counts.changed || 0}</span>
            {align?.truncated && (
              <span><i style={{ background: "var(--surface-2)", borderColor: "var(--border)" }} />未比对</span>
            )}
          </span>
        )}
      </div>

      {align?.truncated && (
        <div className="callout warn" style={{ margin: 0, borderRadius: 0, border: 0, borderBottom: "1px solid var(--amber-border)" }}>
          该 md 共 {align.total_lines.toLocaleString()} 行，一次最多比对前{" "}
          {compared.toLocaleString()} 行；<b>其余 {Math.max(0, lines.length - compared).toLocaleString()} 行仍可正常查看与搜索，但不着色</b>（灰色「未比对」）。
        </div>
      )}
      {align?.not_applicable && (
        <div className="callout warn" style={{ margin: 0, borderRadius: 0, border: 0, borderBottom: "1px solid var(--amber-border)" }}>
          本文件不做逐行比对：{align.reason || "无可比对文本"}。下方为 md 原文（无绿/红标记）。
        </div>
      )}

      <div className="pane-body" ref={bodyRef}>
        {rows.length === 0 && (
          <div className="empty">
            {search.trim()
              ? `没有包含「${search.trim()}」的行`
              : onlyDiff
                ? "没有差异 —— 已比对范围内每一行都能在源文件里找到"
                : "无内容"}
          </div>
        )}
        {shown.map(({ i, text, st, page }) => (
          <div
            key={i}
            ref={(el) => (rowRefs.current[i] = el)}
            className={`mdline ${st} ${curLine === i ? "cur" : ""}`}
            onClick={() => onPickLine(i, page)}
            title={page ? `对应源文件第 ${page} 页（点击跳转）` : undefined}
          >
            <div className="no">{i + 1}</div>
            <div className="tx">{text || " "}</div>
            {page != null && <div className="pg">P{page}</div>}
          </div>
        ))}
        {rows.length > shown.length && (
          <div style={{ padding: 12, textAlign: "center" }}>
            <button onClick={() => setShowAll(true)}>
              显示其余 {(rows.length - shown.length).toLocaleString()} 行
            </button>
          </div>
        )}
      </div>
    </>
  );
}
