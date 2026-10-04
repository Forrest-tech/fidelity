import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MarksResp, PreviewResp } from "../types";

/**
 * 左栏：源文件**常驻**显示（用户 2026-10-05 核心诉求）。
 *
 * 关键设计 —— 高亮直接叠在源文件上，而不是换成「文本对照」视图：
 *   * PDF / 图片 / CAD：在渲染图上按归一化坐标叠加半透明色块。
 *     绿色 = 该处内容在 md 里也找到了（两侧一致）；
 *     红色 = 源文有、md 里没有（转换可能漏了）。
 *     坐标已归一化，缩放/改侧栏宽度都不用重新请求。
 *   * 无页面坐标的格式（docx/xlsx/txt…）：退回 HTML/文本渲染，
 *     并在顶部说明为什么这一栏没有色块 —— 不假装能定位。
 */
export default function SourcePane({
  sid,
  rel,
  page,
  onPage,
  showMarks,
  onPageCount,
}: {
  sid: string;
  rel: string;
  page: number;
  onPage: (p: number) => void;
  showMarks: boolean;
  onPageCount?: (n: number) => void;
}) {
  const [meta, setMeta] = useState<PreviewResp | null>(null);
  const [data, setData] = useState<PreviewResp | null>(null);
  const [marks, setMarks] = useState<MarksResp | null>(null);
  const [sheet, setSheet] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setSheet(0);
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
      .catch((e) => alive && setErr("预览能力探测失败：" + e.message));

    api
      .preview(rel, sid, page, sheet)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setErr("预览失败：" + e.message);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rel, sid, page, sheet]);

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
    [pages, onPage]
  );

  const isImage = data?.kind === "image";
  const stat = marks?.lines.reduce<Record<string, number>>((a, l) => {
    a[l.status] = (a[l.status] || 0) + 1;
    return a;
  }, {});

  return (
    <div className="pv">
      <div className="pane-head">
        <b>源文件</b>
        <span className="badge unreviewed">{(data?.ext || meta?.ext || "").replace(".", "").toUpperCase() || "?"}</span>
        {data?.engine && <span className="dim">{data.engine}</span>}
        <div className="spacer" />
        {stat && showMarks && (
          <span className="legend">
            <span><i style={{ background: "var(--green-bg)", borderColor: "var(--green-border)" }} />一致 {stat.match || 0}</span>
            <span><i style={{ background: "var(--red-bg)", borderColor: "var(--red-border)" }} />md 无 {(stat.src_only || 0) + (stat.changed || 0)}</span>
          </span>
        )}
        {!!data?.sheets?.length && (
          <select value={sheet} onChange={(e) => setSheet(parseInt(e.target.value, 10))} style={{ width: "auto" }} title="工作表">
            {data.sheets!.map((s, i) => (
              <option key={i} value={i}>{s}</option>
            ))}
          </select>
        )}
        {pages > 1 && (
          <div className="row2" style={{ gridTemplateColumns: "auto auto", gap: 4, alignItems: "center" }}>
            <button className="sm" disabled={page <= 1} onClick={() => goto(page - 1)} title="上一页">‹</button>
            <span className="num dim">
              {page} / {pages}
            </span>
            <button className="sm" disabled={page >= pages} onClick={() => goto(page + 1)} title="下一页">›</button>
          </div>
        )}
      </div>

      {err ? (
        <div className="empty">{err}</div>
      ) : (
        <div className="pv-stage" ref={stageRef}>
          {loading && !data && (
            <div className="empty">
              <span className="spin" /> 渲染中…
            </div>
          )}

          {isImage && (
            <div className="pv-canvas">
              <img src={api.previewImg(rel, sid, page, 110)} alt={rel} />
              {/* 命中高亮：绝对定位覆盖在图上，坐标已归一化 → 任意宽度都对齐 */}
              {showMarks &&
                marks?.supported &&
                marks.lines.map((l, i) =>
                  l.status === "unmatched" ? null : (
                    <i
                      key={i}
                      className={`pv-hl ${l.status}`}
                      style={{
                        left: `${l.x * 100}%`,
                        top: `${l.y * 100}%`,
                        width: `${l.w * 100}%`,
                        height: `${l.h * 100}%`,
                      }}
                    />
                  )
                )}
            </div>
          )}

          {data?.kind === "html" && (
            <div className="pv-html" dangerouslySetInnerHTML={{ __html: data.html || "" }} />
          )}
          {data?.kind === "text" && <pre className="pv-pre">{data.text || "（空文件）"}</pre>}
          {(data?.kind === "unsupported" || data?.kind === "missing") && (
            <div className="pv-none">
              <div style={{ fontSize: 26, opacity: 0.3, marginBottom: 8 }}>◍</div>
              <div>{data.note || "该格式暂不支持预览"}</div>
            </div>
          )}
        </div>
      )}

      <div className="pv-note">
        {showMarks && isImage && marks && !marks.supported && marks.reason
          ? marks.reason
          : data?.note || (showMarks && isImage ? "绿色 = md 中已收录该处内容；红色 = 源文有但 md 中没有" : "")}
      </div>
    </div>
  );
}
