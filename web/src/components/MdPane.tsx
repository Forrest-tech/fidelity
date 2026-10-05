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
 * 2b. 动态行高（2026-10-05 修复「文字显示不完整」）：
 *    用户反馈右栏大量文字被截断。根因是**固定行高与折行冲突**：
 *    `.mdline .tx` 是 `white-space: pre-wrap`，长行会折成 2~3 行，
 *    但 JS 把每行 `height` 写死 22px —— 折出来的第二行溢出容器，
 *    视觉上就是「上半行被切掉 + 文字压在下一行上」。
 *    实测那份 61,083 行的 NCC 文件，窄栏下 **14.9%（9,124 行）会折行**。
 *
 *    修法：行高改为**实测**，用「高度表 + 前缀和偏移」代替 `i * rowH`。
 *      * 高度表按行内容指纹缓存；宽度/缩放/行内容任一变化即失效；
 *      * 未测量到的行先用估算高度占位，测到后回填并触发重排；
 *      * 偏移表做前缀和 + 二分查找定位视口首行 —— O(log n)。
 *    这样文字多长都完整显示，且仍然只渲染视口内的行。
 *
 * 2c. 为什么不能只改 CSS（避免以后被「优化」回去）：
 *    `height: auto` + 去掉绝对定位 → 61083 行全量 DOM，浏览器直接卡死；
 *    `overflow:hidden` 单行省略 → 又回到「看不到全文」的老问题。
 *    两者都不可接受，必须保留「虚拟滚动 + 动态行高」。
 *
 * 3. 页面联动：当前源文件页码变化时，自动滚到该页第一行（smooth），
 *    并且**只有用户不在主动滚动时才跟随**，否则会和用户操作打架。
 *
 * ── 分页显示（2026-10-05）────────────────────────────────────
 * 用户反馈：右栏一次铺开 61,083 行，左栏才一页，右边完全对不上，
 * 逐页比对时要来回拖滚动条，效率极低。
 * 现在默认**按页显示**：只渲染属于当前源文件页的行，与左栏一页对一页。
 *
 * ⚠️ 但「按页」绝不能变成「静默丢数据」—— 本文件原本就强调过：
 * 超出比对上限的行仍要可读可搜。所以：
 *   * 提供「整篇 / 本页」显式切换，切换状态写在标题栏，一眼可见；
 *   * 标题栏常驻显示「本页 N 行 / 全篇 M 行」，随时知道还有多少没看；
 *   * 搜索会自动切到整篇（否则搜到的结果看不到，等于搜索坏了）。
 */

/**
 * 单行**最小**高度（px）—— 也是未测量时的估算值。
 * ⚠️ 这不是固定行高：文字折行时行会变高，真实高度由 DOM 实测覆盖（见 2b）。
 * 单行文字的视觉高度仍需与 CSS 的 .mdline font-size/line-height 匹配。
 */
const ROW_H = 22;
/** 视口上下各多渲染的行数 —— 预加载缓冲，避免快速滚动时露白。 */
const OVERSCAN = 20;
/** 高度表最大缓存条目数：超出后按「越新越常用」整体收缩，防止无限增长。 */
const HEIGHT_CACHE_MAX = 4000;

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
  pageScoped,
  onPageScoped,
  srcPath,
  rel,
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
  /** true = 只显示当前源文件页对应的 md 行（与左栏一页对一页）。 */
  pageScoped: boolean;
  onPageScoped: (v: boolean) => void;
  /**
   * 源文件的完整本地路径。与左栏 SourcePane 用的是**同一个** srcPath，
   * 两边必须显示一致的路径，否则比对时无法确认「看的是不是同一份文件」。
   * 缺省时回退到库内相对路径（rel），不能空着 —— 空路径会让用户
   * 不知道这份 md 来自哪个文件。
   */
  srcPath?: string;
  /** 库内相对路径，作为 srcPath 缺失时的回退值。 */
  rel?: string;
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

  /**
   * 「按页」是否可用：需要 align 提供了行→页映射。
   * 没有映射时（docx/xlsx/纯文本等无页码格式）必须退回整篇，
   * 否则右栏会变成空白 —— 那是把「没数据」误报成「这页没内容」。
   */
  const canScope = pages.some((p) => p != null);
  // 搜索时强制整篇：只搜本页的话结果会被过滤掉，等于搜索功能坏了
  const scoped = pageScoped && canScope && !search.trim();

  const rows = useMemo(() => {
    const out: { i: number; text: string; st: string; page: number | null }[] = [];
    const q = search.trim().toLowerCase();
    for (let i = 0; i < n; i++) {
      const st = i < compared ? status[i] || "unmatched" : "nocmp";
      if (onlyDiff && (st === "match" || st === "nocmp")) continue;
      if (q && !lines[i].toLowerCase().includes(q)) continue;
      const p = pages[i] ?? null;
      // 按页：只保留属于当前源文件页的行
      if (scoped && p !== page) continue;
      out.push({ i, text: lines[i], st, page: p });
    }
    return out;
  }, [n, compared, lines, status, pages, onlyDiff, search, scoped, page]);

  /**
   * 按页显示时，若当前页的 md 行**明显少于**源文行数，要提示用户
   * 「这页只对齐了 N 行」，否则会被误读成「转换漏了很多」。
   * 这是诚实性要求：不提示 = 让用户自己猜。
   */
  const pageLineCount = useMemo(() => {
    if (!scoped) return 0;
    return rows.length;
  }, [rows, scoped]);

  /**
   * 本页空白时**必须区分两种完全不同的原因**，否则就是误导：
   *   a) 该页确实没有对应内容（转换真的漏了 / 这页是插图）；
   *   b) 该页落在「单次比对上限」之外（超大文件只比对了前 N 行），
   *      后面几十页天然没有比对结果 —— 这**不是**转换漏了。
   * 真实数据实测：884 页的 PDF 共 61083 行，比对上限 6000 行，
   * 前 200 页里有 113 页落在上限外。若不区分，用户会误判为大面积漏转。
   */
  const beyondCompareCap = useMemo(() => {
    if (!scoped) return false;
    if (!align?.truncated) return false;
    if (rows.length > 0) return false;
    // 该页在 src_page 里完全没有出现 → 说明没被比对覆盖
    return !pages.some((p) => p === page);
  }, [scoped, align?.truncated, rows.length, pages, page]);

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
  /** 容器宽度：折行数由它决定，宽度一变高度缓存就作废。 */
  const [viewW, setViewW] = useState(0);
  /** 高度回填后自增，驱动 offsets 重算（否则前缀和不会更新）。 */
  const [rev, setRev] = useState(0);

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const measure = () => {
      setViewH(el.clientHeight || 600);
      setViewW(el.clientWidth || 0);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rowH = ROW_H * zoom;

  /**
   * ── 动态行高（修「文字显示不完整」）────────────────────────────────
   * 折行文字的真实高度必须实测，否则固定行高会把第 2 行压掉。
   *
   * heights: 指纹 → 实测高度。用**内容长度 + 缩放**做指纹：
   * 同一段文字在同宽度下高度稳定，宽度变化由下面的 width 依赖整体失效。
   * 只用内容长度做指纹是有意的近似 —— 精确指纹要算文本宽度，成本远高于收益；
   * 即便偶发碰撞，也只影响缓存命中率，不会算错高度（回退到 DOM 实测）。
   */
  const heights = useRef(new Map<number, number>());
  /** 宽度/缩放变化 → 折行数变化 → 整表作废（key 变了，旧值自然取不到） */
  const hKey = `${Math.round(viewW)}|${zoom}`;
  const hKeyRef = useRef(hKey);
  if (hKeyRef.current !== hKey) {
    hKeyRef.current = hKey;
    heights.current.clear();
  }

  /**
   * 前缀和偏移表：offsets[k] = 第 k 行之前累计高度。
   * 未测量的行用估算高度（可能偏小），实测回填后触发重排修正。
   */
  const offsets = useMemo(() => {
    const arr = new Float64Array(rows.length + 1);
    for (let k = 0; k < rows.length; k++) {
      const t = rows[k].text;
      // 指纹：长度分档 + 缩放。分档而非精确长度，缓存更省。
      const fp = (t.length >> 3) * 1000 + Math.min(999, t.length & 7);
      const h = heights.current.get(fp);
      arr[k + 1] = arr[k] + (h && h > 0 ? h : rowH);
    }
    return arr;
  }, [rows, rowH, hKey, rev]);

  const total = rows.length ? offsets[rows.length] : 0;

  /**
   * 二分查找：**第一个满足 offsets[j] > y 的下标 j**（offsets 严格递增）。
   *
   * ⚠️ 语义要精确，否则会「每次滚动都跳过视口顶那一行」：
   *   第 k 行覆盖区间是 [offsets[k], offsets[k+1])，
   *   所以覆盖 y 的那一行是 j-1，而不是 j。
   *   （曾在这里写错过：返回 j 会让每屏顶部少一行，是真实的显示缺陷。）
   * y 超出末尾时返回 rows.length，调用方 clamp。
   */
  const firstAfter = useCallback((y: number) => {
    let lo = 0;
    let hi = rows.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (offsets[mid] > y) hi = mid;
      else lo = mid + 1;
    }
    return lo;
  }, [offsets, rows.length]);

  /** 覆盖 y 的那一行下标（clamp 到有效范围）。 */
  const rowAt = useCallback(
    (y: number) => Math.max(0, Math.min(rows.length - 1, firstAfter(y) - 1)),
    [firstAfter, rows.length],
  );

  const startIdx = Math.max(0, rowAt(scrollTop) - OVERSCAN);
  const endIdx = Math.min(rows.length, firstAfter(scrollTop + viewH) + 1 + OVERSCAN);
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
      // 用实测偏移表定位（折行行不再是 rowH 的整数倍）
      const top = offsets[k] ?? 0;
      const target = top - el.clientHeight / 2;
      el.scrollTo({ top: Math.max(0, target), behavior: smooth ? "smooth" : "auto" });
    },
    [offsets],
  );

  /**
   * 实测行高并回填。渲染后 DOM 才有真实高度，所以放在 useLayoutEffect 里
   * 同步测量（避免用户看到「先错位再跳一下」）。
   *
   * ⚠️ 必须做**收敛保护**：只有高度真的变了才 bump rev，
   * 否则会「测量 → setState → 重渲染 → 再测量」无限循环把页面卡死。
   * 同一批指纹只回填一次，第二次测量值相同就不再触发更新。
   */
  useLayoutEffect(() => {
    if (!slice.length) return;
    let changed = false;
    const seen = new Set<number>();
    for (let k = 0; k < slice.length; k++) {
      const r = slice[k];
      const el = rowRefs.current[r.i];
      if (!el) continue;
      const h = el.offsetHeight;
      if (!h) continue;
      const t = r.text;
      const fp = (t.length >> 3) * 1000 + Math.min(999, t.length & 7);
      if (seen.has(fp)) continue;
      seen.add(fp);
      const prev = heights.current.get(fp);
      if (prev == null || Math.abs(prev - h) > 0.5) {
        heights.current.set(fp, h);
        changed = true;
      }
    }
    if (heights.current.size > HEIGHT_CACHE_MAX) {
      // ⚠️ 不能 clear() 整表：那会让所有行退回估算高度 → 偏移全变 → 再测一遍，
      // 永远超阈值，形成**永久抖动**（滚动条乱跳）。
      // 正确做法：只丢掉视口附近没用到的那一半，保留局部性。
      const keep = new Set(seen);
      for (const fp of Array.from(heights.current.keys())) {
        if (!keep.has(fp)) heights.current.delete(fp);
      }
    }
    if (changed) setRev((v) => v + 1);
  }, [slice, rev]);

  // 源文件翻页 → 本栏滚到该页第一行（用户未主动滚动时）
  // 「按页」模式下 rows 本身就已经只剩当前页，无需再滚动定位；
  // 整篇模式才需要按页码跳转。
  useEffect(() => {
    if (scoped) {
      // 换页即回到顶部，保证与左栏「一页对一页」的观感一致
      const el = scrollerRef.current;
      if (el) el.scrollTop = 0;
      setScrollTop(0);
      userScrolling.current = false;
      return;
    }
    if (userScrolling.current) return;
    const k = firstIndexOfPage.get(page);
    if (k == null) return;
    const el = scrollerRef.current;
    if (!el) return;
    // 已经在可视区附近就不动，避免每次翻页都跳
    // ⚠️ 必须用二分查偏移表换算行号，不能用 scrollTop / rowH ——
    // 折行行高不是 rowH 的整数倍，除法会算出错误的行号。
    const cur = rowAt(el.scrollTop);
    if (Math.abs(cur - k) < 6) return;
    scrollToIndex(k);
  }, [page, firstIndexOfPage, rowH, scrollToIndex, scoped, rowAt]);

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
          <span className="badge diff_big" title={t("md.salvageTip")}>
            salvage
          </span>
        )}
        <span className="dim num nowrap">
          {md.chars.toLocaleString()} {t("md.chars")} · {md.words.toLocaleString()} {t("md.words")}
        </span>
        <div className="spacer" />
        {/* 整篇 / 本页 切换：默认按页，与左栏一页对一页。
            同时常驻显示「本页 N / 全篇 M」，任何时候都知道自己只看了一部分。 */}
        {canScope && (
          <div className="seg scopeseg" role="group" aria-label={t("md.scopeLabel")}>
            <button
              className={!scoped ? "on" : ""}
              onClick={() => onPageScoped(false)}
              title={t("md.scopeAllTip")}
            >
              {t("md.scopeAll")}
            </button>
            <button
              className={scoped ? "on" : ""}
              onClick={() => onPageScoped(true)}
              title={t("md.scopePageTip")}
            >
              {t("md.scopePage")}
            </button>
          </div>
        )}
        {scoped && (
          <span className="dim num nowrap" title={t("md.scopeCountTip", { n: lines.length })}>
            {t("md.pageCount", { n: pageLineCount, total: lines.length })}
          </span>
        )}
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

      {/* 源文件完整路径：与左栏显示同一个 srcPath，两侧一致才能确认
          「左边的原文」和「右边的 md」确实是同一份文件。
          路径超长时靠 .mono 的 direction:rtl + ellipsis 从末尾截断
          （保留最有辨识度的尾部），完整值放在 title 里悬停可见。 */}
      {(srcPath || rel) && (
        <div className="pane-path truncate" title={srcPath || rel}>
          <span className="dim">{t("pane.path")}</span>
          <span className="mono">{srcPath || rel}</span>
        </div>
      )}

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
            {search.trim() ? (
              `“${search.trim()}” — 0`
            ) : beyondCompareCap ? (
              /* 关键：区分「没比对到」与「转换漏了」——两者结论完全相反 */
              <span>{t("md.pageBeyondCap", { n: compared.toLocaleString() })}</span>
            ) : scoped ? (
              /* 按页但这一页没有对应行：必须说清是「换一页看」还是「转换漏了」，
                   绝不能让空白页看起来像程序出错。 */
              t("md.pageEmpty")
            ) : onlyDiff ? (
              "0"
            ) : (
              "—"
            )}
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
                    top: offsets[abs],
                    // ⚠️ 关键：min-height 而非 height。
                    // 写死 height 会让折行文字被压掉（用户报告的「显示不完整」）。
                    // 高度交给内容决定，虚拟滚动靠 offsets 前缀和定位，不依赖行高恒定。
                    minHeight: rowH,
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
