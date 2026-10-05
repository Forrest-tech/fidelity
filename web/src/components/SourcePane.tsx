import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MarksResp, PreviewResp } from "../types";
import { useI18n } from "../i18n";

/**
 * 左栏：源文件**常驻**显示。
 *
 * 关键设计 —— 高亮直接叠在源文件上，而不是换成「文本对照」视图：
 *   * PDF / 图片 / CAD：在渲染图上按归一化坐标叠加半透明色块。
 *     绿色 = 该处内容在 md 里也找到了（两侧一致）；
 *     红色 = 源文有、md 里没有（转换可能漏了）。
 *     坐标已归一化，缩放/改侧栏宽度都不用重新请求。
 *   * 无页面坐标的格式（docx/xlsx/txt…）：退回 HTML/文本渲染，
 *     并在顶部说明为什么这一栏没有色块 —— 不假装能定位。
 *
 * ── 翻页性能与联动（2026-10-05 重做）────────────────────────────
 * 用户反馈「点下一页很慢、不能同步、滚轮翻不了页」。实测后端并不慢
 * （缓存命中后 /preview/img 约 7ms，/marks 约 0.4s），慢在**前端编排**：
 *
 *  1. `meta`（页数）原本挂在 [rel,sid,page,sheet] 上 —— 每次翻页都重新请求一次
 *     /preview/meta，而它跟 page 毫无关系。已拆成独立 effect，只随文件变。
 *  2. 加载态判断错位：原来 `loading && !data` 才显示 loading，而翻页时 data
 *     一直有值 → 永远不显示转圈，用户只看到「卡住」。改为保留旧页 + 角标提示。
 *  3. 翻页不跟手：原来 .pv-canvas 宽度是 zoom*100%，图片又是 max-width:100%，
 *     缩放等于没生效。现在宽度用 zoom 换算成实际像素宽度，缩放真的生效。
 *  4. 滚轮翻页：原实现只在「滚动到贴底」时才翻页，图片比视口矮时
 *     根本没有滚动条 → 滚轮完全失效。现在改为**累积滚动量**判定方向，
 *     到底/到顶后继续同向滚动即翻页，与图片高度无关。
 *  5. 右栏跟不动：右栏有 userScrolling 抑制逻辑，左栏翻页后右栏若处于
 *     「抑制窗口」内就拒绝跟随。现在由 App 侧用 requestAnimationFrame
 *     在抑制窗口结束后强制对齐，避免两边停在不同页。
 */

/** 预取相邻页的距离：1 页足够顺滑，取 2 更稳但多两次渲染开销。 */
const PREFETCH = 2;
/** 预取 marks 的距离：/marks 约 0.4s，是四个请求里最慢的，优先预取。 */
const PREFETCH_MARKS = 1;
/** 滚轮翻页阈值：累计 420px 判定为一次翻页，避免轻扫就跳页。 */
const WHEEL_PAGE_THRESHOLD = 420;
/** 翻页后回到顶部前的短暂冷却，防止新页内容一加载就立刻被判定为「到底」。 */
const PAGE_SETTLE_MS = 260;

export default function SourcePane({
  sid,
  rel,
  page,
  onPage,
  onPageCount,
  showMarks,
  zoom,
  onZoom,
  focusMark,
  srcPath,
}: {
  sid: string;
  rel: string;
  page: number;
  onPage: (p: number) => void;
  showMarks: boolean;
  onPageCount?: (n: number) => void;
  zoom: number;
  onZoom: (z: number) => void;
  /** 外部要求高亮某个文本（点右栏 md 行时用）。 */
  focusMark?: string | null;
  srcPath?: string;
}) {
  const [t] = useI18n();
  const [meta, setMeta] = useState<PreviewResp | null>(null);
  const [data, setData] = useState<PreviewResp | null>(null);
  const [marks, setMarks] = useState<MarksResp | null>(null);
  const [sheet, setSheet] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  /** 记录已请求过的页，避免来回翻页时重复渲染同一页。 */
  const warmed = useRef<Set<number>>(new Set());
  const warmedMarks = useRef<Set<number>>(new Set());
  /** 滚轮累积量：与图片是否比视口高无关，矮图也能翻页。 */
  const wheelAcc = useRef(0);
  const wheelResetTimer = useRef<number | null>(null);
  /** 翻页冷却：避免新页刚渲染就被上一次的滚动惯性判定为「到底」。 */
  const settleUntil = useRef(0);

  const pages = Math.max(1, meta?.pages || data?.pages || 1);

  const clamp = useCallback(
    (p: number) => Math.max(1, Math.min(pages, Math.round(p))),
    [pages],
  );

  const goto = useCallback(
    (p: number) => {
      const next = clamp(p);
      if (next === page) return;
      // 换页时立刻回顶部，否则新页会停在上页的滚动位置，看起来像「没翻页」
      const el = stageRef.current;
      if (el) el.scrollTop = 0;
      wheelAcc.current = 0;
      settleUntil.current = Date.now() + PAGE_SETTLE_MS;
      onPage(next);
    },
    [clamp, onPage, page],
  );

  // 切文件：重置所有分页状态
  useEffect(() => {
    setSheet(0);
    warmed.current = new Set();
    warmedMarks.current = new Set();
    wheelAcc.current = 0;
    const el = stageRef.current;
    if (el) el.scrollTop = 0;
  }, [rel]);

  // ★ 页数/能力：只随文件变化。原先挂在 page 上导致每次翻页都白跑一次
  // /preview/meta（PDF 还要重新 open 一次文档），是「翻页卡」的主要来源之一。
  useEffect(() => {
    if (!rel || !sid) return;
    let alive = true;
    api
      .previewMeta(rel, sid)
      .then((m) => {
        if (!alive) return;
        setMeta(m);
        onPageCount?.(Math.max(1, m.pages || 1));
      })
      .catch((e) => alive && setErr(t("tree.failed") + "：" + e.message));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rel, sid]);

  // 内容元信息：随页变化，但很轻（PDF 只回 kind/pages/engine）
  useEffect(() => {
    if (!rel || !sid) return;
    let alive = true;
    setLoading(true);
    api
      .preview(rel, sid, page, sheet)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setErr(e.message);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rel, sid, page, sheet]);

  // 预取相邻页的图片：让翻页几乎无等待。失败静默，正式加载仍会走主流程。
  useEffect(() => {
    if (!rel || !sid || !meta?.pages) return;
    for (let d = 1; d <= PREFETCH; d++) {
      for (const p of [page - d, page + d]) {
        if (p < 1 || p > (meta.pages || 1)) continue;
        if (warmed.current.has(p)) continue;
        warmed.current.add(p);
        const img = new Image();
        img.src = api.previewImg(rel, sid, p, 110);
      }
    }
  }, [rel, sid, page, meta?.pages]);

  // 预取 marks：四个请求里最慢的就是它（约 0.4s），提前热好，翻页时基本零等待
  useEffect(() => {
    if (!showMarks || !rel || !sid || !meta?.pages) return;
    for (let d = 1; d <= PREFETCH_MARKS; d++) {
      for (const p of [page - d, page + d]) {
        if (p < 1 || p > (meta.pages || 1)) continue;
        if (warmedMarks.current.has(p)) continue;
        warmedMarks.current.add(p);
        api.marks(rel, sid, p).catch(() => {
          /* 预取失败无需处理，正式请求仍会走主流程 */
        });
      }
    }
  }, [showMarks, rel, sid, page, meta?.pages]);

  // 高亮坐标：仅在 showMarks 且当前是图像型页面时请求
  useEffect(() => {
    if (!showMarks || !rel || !sid) {
      setMarks(null);
      return;
    }
    if (data && data.kind !== "image") {
      setMarks(null);
      return;
    }
    let alive = true;
    api
      .marks(rel, sid, page)
      .then((m) => alive && setMarks(m))
      .catch(() => alive && setMarks(null));
    return () => {
      alive = false;
    };
  }, [showMarks, rel, sid, page, data?.kind]);

  /**
   * 原生滚动（拖滚动条 / 触摸板惯性）时清零滚轮累积量。
   *
   * ★ 这里**不再判定翻页**（2026-10-05 修正）：翻页判定已移进 wheel 处理器自身。
   * 旧实现放在本回调里，靠 scroll 事件驱动；但「已到边缘」时我们调用了
   * preventDefault()，scrollTop 根本不变 → **永远不会有 scroll 事件**，
   * 于是「滚轮翻页」在图片比视口高（能滚）时也完全失效，是一个死逻辑。
   */
  const onStageScroll = useCallback(() => {
    wheelAcc.current = 0;
  }, []);

  /**
   * 捕获滚轮事件本身：图片比视口矮时 scroll 事件不触发，只能靠 wheel 累积。
   *
   * ⚠️ 必须用 **原生 addEventListener(..., { passive: false })**，不能用 React 的
   * onWheel：React 18 把 wheel/touchstart/touchmove 在 root 上注册为 **passive**
   * 监听器（见 react-dom 源码 addTrappedEventListener），在 passive 监听器里调
   * preventDefault() 会被浏览器忽略并打警告 —— 也就是「写了但不起作用」。
   *
   * ★★ 方向感知是硬要求（2026-10-05 用户反馈「不能鼠标滚动来上下查看」的根因）：
   * 早先只判断「在顶部或不在顶部」，于是**在页面顶部时向下滚也走了 preventDefault
   * 分支被吞掉** —— 表现为「滚轮完全失灵，只能拖滚动条」。
   * 正确语义：只有**沿当前滚动方向已经没有可滚空间**时，才接管并转为翻页。
   *   向下滚（deltaY>0）：不在底部 → 放行，让原生滚动
   *   向上滚（deltaY<0）：不在顶部 → 放行，让原生滚动
   */
  useEffect(() => {
    const el = stageRef.current;
    if (!el || pages <= 1) return;
    const onWheelNative = (e: WheelEvent) => {
      if (Date.now() < settleUntil.current) return;
      const scrollable = el.scrollHeight > el.clientHeight + 2;
      const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
      const atTop = el.scrollTop <= 0;
      // 沿滚动方向还有空间 → 完全不干预，交给原生滚动
      const roomToScroll = e.deltaY > 0 ? !atBottom : e.deltaY < 0 && !atTop;
      if (scrollable && roomToScroll) {
        wheelAcc.current = 0;
        return;
      }
      // 已在边缘（或压根不可滚）：吞掉滚动并累积，够阈值就翻页
      e.preventDefault();
      wheelAcc.current += e.deltaY;
      if (wheelResetTimer.current) window.clearTimeout(wheelResetTimer.current);
      wheelResetTimer.current = window.setTimeout(() => {
        wheelAcc.current = 0;
      }, 160);
      // ★ 判定必须在这里做，不能依赖 scroll 事件：已到边缘时我们 preventDefault()
      //   了，scrollTop 不变 → 不会有 scroll 事件 → 旧实现是死逻辑。
      if (wheelAcc.current > WHEEL_PAGE_THRESHOLD) {
        wheelAcc.current = 0;
        goto(page + 1);
      } else if (wheelAcc.current < -WHEEL_PAGE_THRESHOLD) {
        wheelAcc.current = 0;
        goto(page - 1);
      }
    };
    el.addEventListener("wheel", onWheelNative, { passive: false });
    return () => el.removeEventListener("wheel", onWheelNative);
  }, [pages, page, goto]);

  // 键盘：←/→ 与 PageUp/PageDown 翻页，Home/End 跳首页/末页
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        goto(page - 1);
      } else if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") {
        e.preventDefault();
        goto(page + 1);
      } else if (e.key === "Home") {
        e.preventDefault();
        goto(1);
      } else if (e.key === "End") {
        e.preventDefault();
        goto(pages);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goto, page, pages]);

  useEffect(
    () => () => {
      if (wheelResetTimer.current) window.clearTimeout(wheelResetTimer.current);
    },
    [],
  );

  const isImage = data?.kind === "image";
  const stat = marks?.lines.reduce<Record<string, number>>((a, l) => {
    a[l.status] = (a[l.status] || 0) + 1;
    return a;
  }, {});

  /** 从右栏点过来的文本：找到最接近的一行并描边强调。 */
  const focusLine = focusMark
    ? marks?.lines.find((l) => l.text === focusMark || l.text.includes(focusMark))
    : null;

  const step = 0.25;
  const setZoom = (z: number) => onZoom(Math.min(3, Math.max(0.5, Math.round(z * 100) / 100)));

  /**
   * 缩放宽度：用**实际像素**而不是百分比。
   * 原来 `width: zoom*100%` 配 `img{max-width:100%}` —— 两者互相抵消，
   * 无论怎么点百分比都在变但画面尺寸不动，这就是「放大缩小不能使用」。
   * 现在图片按 zoom 缩放，容器宽度跟着走；归一化坐标（%）自动跟随。
   */
  const [stageW, setStageW] = useState(0);
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const measure = () => setStageW(el.clientWidth - 24);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  /** 内容宽度：随 zoom 变化；基线是「适应宽度」。 */
  const canvasW = stageW > 0 ? Math.max(120, Math.round(stageW * zoom)) : undefined;

  return (
    <div className="pv">
      <div className="pane-head">
        <b>{t("pane.source")}</b>
        <span className="badge unreviewed">
          {(data?.ext || meta?.ext || "").replace(".", "").toUpperCase() || "?"}
        </span>
        {data?.engine && <span className="dim">{data.engine}</span>}
        <div className="spacer" />
        {stat && showMarks && (
          <span className="legend">
            <span>
              <i style={{ background: "var(--green-bg)", borderColor: "var(--green-border)" }} />
              {t("legend.match")} {stat.match || 0}
            </span>
            <span>
              <i style={{ background: "var(--red-bg)", borderColor: "var(--red-border)" }} />
              {t("legend.srcOnly")} {(stat.src_only || 0) + (stat.changed || 0)}
            </span>
          </span>
        )}
        {!!data?.sheets?.length && (
          <select value={sheet} onChange={(e) => setSheet(parseInt(e.target.value, 10))} style={{ width: "auto" }} title={t("pane.sheet")}>
            {data.sheets!.map((s, i) => (
              <option key={i} value={i}>
                {s}
              </option>
            ))}
          </select>
        )}
        {pages > 1 && (
          <div className="pager">
            <button className="sm" disabled={page <= 1} onClick={() => goto(page - 1)} title={t("pane.prev")}>
              ‹
            </button>
            <span className="num dim nowrap">
              {page} / {pages}
            </span>
            <button className="sm" disabled={page >= pages} onClick={() => goto(page + 1)} title={t("pane.next")}>
              ›
            </button>
          </div>
        )}
        <div className="zoomctl" role="group" aria-label={t("pane.zoom")}>
          <button className="sm" onClick={() => setZoom(zoom - step)} title={t("pane.zoomOut")} disabled={zoom <= 0.5}>
            −
          </button>
          <button className="sm zoomval" onClick={() => setZoom(1)} title={t("pane.zoomReset")}>
            {Math.round(zoom * 100)}%
          </button>
          <button className="sm" onClick={() => setZoom(zoom + step)} title={t("pane.zoomIn")} disabled={zoom >= 3}>
            +
          </button>
        </div>
      </div>

      {/* 文件完整路径：让用户始终知道自己在看哪个文件 */}
      <div className="pane-path truncate" title={srcPath || rel}>
        <span className="dim">{t("pane.path")}</span>
        <span className="mono">{srcPath || rel}</span>
      </div>

      {err ? (
        <div className="empty">{err}</div>
      ) : (
        <div
          className="pv-stage"
          ref={stageRef}
          onScroll={onStageScroll}
          tabIndex={0}
          role="region"
          aria-label={t("pane.source")}
        >
          {/* 翻页加载提示：保留旧页内容，只叠一个角标，避免整块闪白 */}
          {loading && <div className="pv-loading">{t("pane.loadingPage")}</div>}

          {loading && !data && (
            <div className="empty">
              <span className="spin" /> …
            </div>
          )}

          {isImage && (
            <div
              className="pv-canvas"
              style={canvasW ? { width: canvasW } : undefined}
            >
              <img src={api.previewImg(rel, sid, page, 110)} alt="" />
              {showMarks &&
                marks?.supported &&
                marks.lines.map((l, i) =>
                  l.status === "unmatched" ? null : (
                    <i
                      key={i}
                      className={`pv-hl ${l.status} ${focusLine && l === focusLine ? "focus" : ""}`}
                      style={{
                        left: `${l.x * 100}%`,
                        top: `${l.y * 100}%`,
                        width: `${l.w * 100}%`,
                        height: `${l.h * 100}%`,
                      }}
                    />
                  ),
                )}
            </div>
          )}

          {data?.kind === "html" && (
            <div
              className="pv-html"
              style={{ zoom }}
              dangerouslySetInnerHTML={{ __html: data.html || "" }}
            />
          )}
          {data?.kind === "text" && (
            <pre className="pv-pre" style={{ zoom }}>
              {data.text || t("pane.emptyFile")}
            </pre>
          )}
          {(data?.kind === "unsupported" || data?.kind === "missing") && (
            <div className="pv-none">
              <div style={{ fontSize: 26, opacity: 0.3, marginBottom: 8 }}>◍</div>
              <div>{data.note || "—"}</div>
            </div>
          )}
        </div>
      )}

      <div className="pv-note">
        {showMarks && isImage && marks && !marks.supported && marks.reason
          ? marks.reason
          : data?.note || (showMarks && isImage ? t("compare.legend") : "")}
      </div>
    </div>
  );
}
