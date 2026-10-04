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
 * 翻页联动（2026-10-05）：滚到底自动进入下一页并预取相邻页，
 * 右栏据此跟到同一页，用户两边永远看同一段内容。
 */

/** 预取相邻页的距离：1 页足够顺滑，取 2 更稳但多两次渲染开销。 */
const PREFETCH = 1;

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

  useEffect(() => {
    setSheet(0);
    warmed.current = new Set();
  }, [rel]);

  useEffect(() => {
    if (!rel || !sid) return;
    let alive = true;
    setLoading(true);
    setErr(null);
    api
      .previewMeta(rel, sid)
      .then((m) => {
        if (!alive) return;
        setMeta(m);
        onPageCount?.(Math.max(1, m.pages || 1));
      })
      .catch((e) => alive && setErr(t("tree.failed") + "：" + e.message));

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

  const pages = Math.max(1, meta?.pages || data?.pages || 1);
  const goto = useCallback(
    (p: number) => onPage(Math.max(1, Math.min(pages, p))),
    [pages, onPage],
  );

  /** 滚到底 → 翻到下一页；滚到顶 → 上一页。左右两栏因此始终停在同一页。 */
  const onStageScroll = useCallback(() => {
    const el = stageRef.current;
    if (!el || pages <= 1) return;
    // 只在接近边缘时触发，避免连续跳页
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24) {
      if (page < pages) goto(page + 1);
    } else if (el.scrollTop <= 24) {
      if (page > 1) goto(page - 1);
    }
  }, [pages, page, goto]);

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
          <select value={sheet} onChange={(e) => setSheet(parseInt(e.target.value, 10))} style={{ width: "auto" }} title="Sheet">
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
            <span className="num dim">
              {page} / {pages}
            </span>
            <button className="sm" disabled={page >= pages} onClick={() => goto(page + 1)} title={t("pane.next")}>
              ›
            </button>
          </div>
        )}
        <div className="zoomctl" role="group" aria-label="zoom">
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
        <div className="pv-stage" ref={stageRef} onScroll={onStageScroll}>
          {loading && !data && (
            <div className="empty">
              <span className="spin" /> …
            </div>
          )}

          {isImage && (
            <div className="pv-canvas" style={{ width: `${zoom * 100}%` }}>
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
              {data.text || "（空文件）"}
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
