import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AlignResp, MdResp } from "../types";
import { useI18n } from "../i18n";

/**
 * 右栏：入库 .md 逐行显示，**绿色 = 该行在源文件里也找到了**。
 *
 * ⚠️ 三个必须守住的正确性约束（都是踩过坑才写下来的）：
 *
 * 1. 索引安全：`status[i]` 与 `lines[i]` 由后端保证同一下标语义（都用 splitlines()），
 *    所以「两侧同色」才成立。status 允许比 md 短（超大文件只比对前 N 行），
 *    但**必须仍渲染全部 md 行** —— 否则 30000 行的 md 只剩前 6000 行可见，
 *    用户会以为文件到 6000 行就结束了。这是「静默丢数据」，比标错色更严重。
 *    超出比对上限的行标为 nocmp（中性），绝不标 unmatched ——
 *    unmatched 的语义是「比对过，源文里确实没有」，两者不能混为一谈。
 *
 * 2. 虚拟滚动：md 最大 2.6MB / 3 万行，全量 DOM 会让浏览器直接卡死。
 *    只渲染视口内 + 上下缓冲区的行，用绝对定位的 spacer 撑出总高度。
 *
 * 3. 页面联动：当前源文件页码变化时，自动滚到该页第一行（smooth），
 *    并且**只有用户不在主动滚动时才跟随**，否则会和用户操作打架。
 */

/** 单行高度（px）。必须与 CSS 里的 .mdline 高度一致，改一处要改两处。 */
const ROW_H = 22;
/** 视口上下各多渲染的行数 —— 预加载缓冲，避免快速滚动时露白。 */
const OVERSCAN = 20;

export default function MdPane({
  md,
  align,
  onlyDiff,
  search,
  curLine,
  onPickLine,
  zoom,
  page,
  focusLine,
  onUserScroll,
}: {
  md: MdResp;
  align: AlignResp | null;
  onlyDiff: boolean;
  search: string;
  curLine: number | null;
  onPickLine: (i: number, page: number | null) => void;
  zoom: number;
  page: number;
  /** 外部要求滚动到某一行（点左栏高亮时用）。null = 不动。 */
  focusLine?: number | null;
  onUserScroll?: () => void;
}) {
  const [t] = useI18n();
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const rowRefs = useRef<Record<number, HTMLDivElement | null>>({});
  /** 用户正在主动滚动：此时不跟随页码，避免抢滚动条。 */
  const userScrolling = useRef(false);
  const suppressTimer = useRef<number | null>(null);

  const lines = md.lines || [];
  const status = align?.status || [];
  const pages = align?.src_page || [];
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

  // 行下标 → 在 rows 中的位置（用于页码联动定位首个属于该页的行）
  const firstIndexOfPage = useMemo(() => {
    const m = new Map<number, number>();
    rows.forEach((r, k) => {
      if (r.page != null && !m.has(r.page)) m.set(r.page, k);
    });
    return m;
  }, [rows]);

  // ---------- 虚拟滚动窗口 ----------
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(600);

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const measure = () => setViewH(el.clientHeight || 600);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rowH = ROW_H * zoom;
  const total = rows.length * rowH;
  const startIdx = Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN);
  const endIdx = Math.min(rows.length, Math.ceil((scrollTop + viewH) / rowH) + OVERSCAN);
  const slice = rows.slice(startIdx, endIdx);

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setScrollTop(el.scrollTop);
    // 标记「用户正在滚动」，暂停页码跟随 400ms
    userScrolling.current = true;
    if (suppressTimer.current) window.clearTimeout(suppressTimer.current);
    suppressTimer.current = window.setTimeout(() => {
      userScrolling.current = false;
    }, 400);
    onUserScroll?.();
  }, [onUserScroll]);

  useEffect(
    () => () => {
      if (suppressTimer.current) window.clearTimeout(suppressTimer.current);
    },
    [],
  );

  const scrollToIndex = useCallback(
    (k: number, smooth = true) => {
      const el = scrollerRef.current;
      if (!el || k < 0) return;
      const target = k * rowH - el.clientHeight / 2 + rowH / 2;
      el.scrollTo({ top: Math.max(0, target), behavior: smooth ? "smooth" : "auto" });
    },
    [rowH],
  );

  // 源文件翻页 → 本栏滚到该页第一行（用户未主动滚动时）
  useEffect(() => {
    if (userScrolling.current) return;
    const k = firstIndexOfPage.get(page);
    if (k == null) return;
    const el = scrollerRef.current;
    if (!el) return;
    // 已经在可视区附近就不动，避免每次翻页都跳
    const cur = el.scrollTop / rowH;
    if (Math.abs(cur - k) < 6) return;
    scrollToIndex(k);
  }, [page, firstIndexOfPage, rowH, scrollToIndex]);

  // 外部指定行（左栏点击 → 右栏定位并高亮）
  useEffect(() => {
    if (focusLine == null) return;
    const k = rows.findIndex((r) => r.i === focusLine);
    if (k >= 0) {
      userScrolling.current = false;
      scrollToIndex(k);
    }
  }, [focusLine, rows, scrollToIndex]);

  if (md.missing) {
    return <div className="empty">{t("compare.noMd")}</div>;
  }

  const counts = align?.by_status || {};
  const totalLines = rows.length;

  return (
    <>
      <div className="pane-head">
        <b>{t("pane.md")}</b>
        {md.salvage && (
          <span className="badge diff_big" title="salvage">
            salvage
          </span>
        )}
        <span className="dim num">
          {md.chars.toLocaleString()} 字 · {md.words.toLocaleString()} 词
        </span>
        <div className="spacer" />
        {!!counts.match && (
          <span className="legend">
            <span>
              <i style={{ background: "var(--green-bg)", borderColor: "var(--green-border)" }} />
              {t("legend.match")} {counts.match}
            </span>
            <span>
              <i style={{ background: "var(--red-bg)", borderColor: "var(--red-border)" }} />
              {t("legend.mdOnly")} {counts.md_only || 0}
            </span>
            <span>
              <i style={{ background: "var(--amber-bg)", borderColor: "var(--amber-border)" }} />
              {t("legend.changed")} {counts.changed || 0}
            </span>
            {align?.truncated && (
              <span>
                <i style={{ background: "var(--surface-2)", borderColor: "var(--border)" }} />
                {t("legend.nocmp")}
              </span>
            )}
          </span>
        )}
      </div>

      {align?.truncated && (
        <div className="callout warn edge">
          {t("compare.truncated", {
            total: align.total_lines.toLocaleString(),
            n: compared.toLocaleString(),
            rest: Math.max(0, lines.length - compared).toLocaleString(),
          })}
        </div>
      )}
      {align?.not_applicable && (
        <div className="callout warn edge">
          {t("compare.notApplicable", { r: align.reason || "—" })}
        </div>
      )}

      <div className="pane-body virtual" ref={scrollerRef} onScroll={onScroll}>
        {totalLines === 0 ? (
          <div className="empty">
            {search.trim() ? `“${search.trim()}” — 0` : onlyDiff ? "0" : "—"}
          </div>
        ) : (
          <div style={{ height: total, position: "relative" }}>
            {slice.map((r, k) => {
              const abs = startIdx + k;
              return (
                <div
                  key={r.i}
                  ref={(el) => (rowRefs.current[r.i] = el)}
                  className={`mdline ${r.st} ${curLine === r.i ? "cur" : ""}`}
                  style={{
                    position: "absolute",
                    top: abs * rowH,
                    height: rowH,
                    lineHeight: `${rowH}px`,
                  }}
                  onClick={() => onPickLine(r.i, r.page)}
                  title={r.page ? `${t("pane.page", { cur: r.page, total: page })}` : undefined}
                >
                  <div className="no">{r.i + 1}</div>
                  <div className="tx">{r.text || " "}</div>
                  {r.page != null && <div className="pg">P{r.page}</div>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
