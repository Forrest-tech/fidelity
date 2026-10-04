import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { PreviewResp } from "../types";

/**
 * 左栏：源文件的原生渲染。
 *
 * 与「源文本」视图互补：这里看的是文件本来的样子（PDF 页面、图片、CAD 图、
 * 表格、幻灯片、邮件正文），用来判断「转换后丢了多少东西」；
 * 逐行比对视图里看的是抽取出的文本行 + 绿/红标记。
 */
export default function SourcePreview({
  sid,
  rel,
  onTextMode,
}: {
  sid: string;
  rel: string;
  onTextMode?: () => void;
}) {
  const [meta, setMeta] = useState<PreviewResp | null>(null);
  const [data, setData] = useState<PreviewResp | null>(null);
  const [page, setPage] = useState(1);
  const [sheet, setSheet] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [zoom, setZoom] = useState(1);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setPage(1);
    setSheet(0);
    setZoom(1);
  }, [rel]);

  useEffect(() => {
    if (!rel || !sid) return;
    let alive = true;
    setLoading(true);
    setErr(null);
    api
      .previewMeta(rel, sid)
      .then((m) => alive && setMeta(m))
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
  }, [rel, sid, page, sheet]);

  const pages = Math.max(1, data?.pages || meta?.pages || 1);
  const goto = useCallback(
    (p: number) => setPage((prev) => Math.max(1, Math.min(pages, p)) || prev),
    [pages]
  );

  // 键盘翻页：左栏聚焦时 ←/→ 直接翻页
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (pages <= 1) return;
      if (e.key === "ArrowLeft") goto(page - 1);
      else if (e.key === "ArrowRight") goto(page + 1);
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [page, pages, goto]);

  return (
    <div className="pv" ref={boxRef} tabIndex={0}>
      <div className="pv-head">
        <span className="pv-title">源文件</span>
        <span className="pv-ext">{(data?.ext || meta?.ext || "").replace(".", "").toUpperCase()}</span>
        {data?.engine && <span className="pv-engine" title="渲染引擎">渲染：{data.engine}</span>}
        {onTextMode && (
          <button className="pv-tab" onClick={onTextMode} title="切换到源文本视图（带绿/红对齐标记）">
            源文本
          </button>
        )}
        <div className="spacer" />
        {pages > 1 && (
          <div className="pv-pager">
            <button disabled={page <= 1} onClick={() => goto(page - 1)}>
              ‹
            </button>
            <input
              value={page}
              onChange={(e) => goto(parseInt(e.target.value || "1", 10))}
              title="页码"
            />
            <span>/ {pages}</span>
            <button disabled={page >= pages} onClick={() => goto(page + 1)}>
              ›
            </button>
          </div>
        )}
        {data?.kind === "image" && (
          <div className="pv-pager">
            <button onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.2).toFixed(1)))} title="缩小">
              －
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button onClick={() => setZoom((z) => Math.min(3, +(z + 0.2).toFixed(1)))} title="放大">
              ＋
            </button>
          </div>
        )}
        {!!(data?.sheets?.length) && (
          <select value={sheet} onChange={(e) => setSheet(parseInt(e.target.value, 10))} title="工作表">
            {data.sheets!.map((s, i) => (
              <option key={i} value={i}>
                {s}
              </option>
            ))}
          </select>
        )}
      </div>

      {err && <div className="pv-body err">{err}</div>}

      {!err && (
        <div className="pv-body">
          {loading && !data && <div className="muted">渲染中…</div>}
          {/* 首次渲染重型格式（DWG 转换 + 矢量渲染约 10–20s）时给出明确预期，
              否则用户会以为页面卡死。命中缓存后是毫秒级。 */}
          {loading && data && data.kind === "image" && (
            <div className="pv-loading-note">首次渲染该文件需要十几秒（结果会缓存，之后翻页/重开都是秒开）…</div>
          )}

          {data?.kind === "image" && (
            <div className="pv-imgwrap">
              <img
                src={api.previewImg(rel, sid, page, 110)}
                alt={rel}
                style={{ width: `${zoom * 100}%` }}
                onClick={() => setZoom((z) => (z >= 2 ? 1 : +(z + 0.5).toFixed(1)))}
              />
            </div>
          )}

          {data?.kind === "html" && (
            <div className="pv-html" dangerouslySetInnerHTML={{ __html: data.html || "" }} />
          )}

          {data?.kind === "text" && <pre className="pv-pre">{data.text || "（空文件）"}</pre>}

          {(data?.kind === "unsupported" || data?.kind === "missing") && (
            <div className="pv-none">
              <div className="pv-none-icon">◍</div>
              <div>{data.note || "该格式暂不支持预览"}</div>
              {onTextMode && (
                <button className="pv-tab" onClick={onTextMode}>
                  看已抽取的文本
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {data?.note && data.kind !== "unsupported" && (
        <div className="pv-foot">{data.note}</div>
      )}
    </div>
  );
}
