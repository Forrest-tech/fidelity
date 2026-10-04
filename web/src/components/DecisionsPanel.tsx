import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { DecisionItem } from "../types";

const EXT_LABEL: Record<string, string> = {
  ".dwg": "CAD 图纸",
  ".dxf": "CAD 图纸",
  ".rfa": "Revit 族",
  ".rvt": "Revit 模型",
  ".pdf": "扫描 PDF",
  ".jpg": "图片",
  ".jpeg": "图片",
  ".png": "图片",
  ".tif": "图片",
  ".zip": "压缩包",
  ".mp4": "视频",
};

/** 人工决定队列：无法自动比对的文件，入库 / 不入库由用户拍板。 */
export default function DecisionsPanel(props: {
  sid: string;
  reviewer: string;
  onClose: () => void;
  onChanged: () => void;
  onReeval: (rel: string) => void;
}) {
  const [items, setItems] = useState<DecisionItem[]>([]);
  const [tab, setTab] = useState<"pending" | "include" | "exclude">("pending");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api.decisions(props.sid, tab === "pending" ? "" : tab);
      setItems(d.items);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    }
  }, [props.sid, tab]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (it: DecisionItem, decision: string) => {
    setBusy(it.rel);
    try {
      await api.setDecision(it.rel, decision, props.reviewer || "local");
      // 入库且该格式有自动处理器（扫描件/图片/CAD）→ 自动重跑评测
      if (decision === "include" && [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".dwg", ".dxf", ".zip"].includes(it.ext)) {
        props.onReeval(it.rel);
      }
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const decideAllExclude = async () => {
    if (!items.length) return;
    if (!confirm(`将把当前 ${items.length} 个待决定文件全部标记「不入库」（之后可逐个撤销）。继续？`)) return;
    setBusy("__all__");
    try {
      for (const it of items) {
        await api.setDecision(it.rel, "exclude", props.reviewer || "local", "批量标记不入库");
      }
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const decideAllInclude = async () => {
    if (!items.length) return;
    if (!confirm(`将把当前 ${items.length} 个待决定文件全部标记「入库」，并对可自动处理的格式重跑评测。继续？`)) return;
    setBusy("__all__");
    try {
      for (const it of items) {
        await api.setDecision(it.rel, "include", props.reviewer || "local", "批量标记入库");
        if ([".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".dwg", ".dxf", ".zip"].includes(it.ext)) {
          props.onReeval(it.rel);
        }
      }
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const undo = async (it: DecisionItem) => {
    setBusy(it.rel);
    try {
      await api.setDecision(it.rel, "", props.reviewer || "local");
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="modal-mask" onClick={props.onClose}>
      <div className="modal" style={{ width: 860, maxHeight: "82vh" }} onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>人工决定队列 — 无法自动比对的文件</h3>
          <div className="spacer" />
          <button onClick={props.onClose}>关闭</button>
        </header>
        <div className="body">
          {err && <div className="notice err" onClick={() => setErr("")}>{err}（点击关闭）</div>}
          <div className="filter-row" style={{ marginBottom: 10 }}>
            <button className={`chip ${tab === "pending" ? "active" : ""}`} onClick={() => setTab("pending")}>待决定</button>
            <button className={`chip ${tab === "include" ? "active" : ""}`} onClick={() => setTab("include")}>已入库</button>
            <button className={`chip ${tab === "exclude" ? "active" : ""}`} onClick={() => setTab("exclude")}>已排除</button>
            <div className="spacer" />
            {tab === "pending" && (
              <>
                <button disabled={busy !== "" || !items.length} onClick={decideAllInclude}>全部入库</button>
                <button disabled={busy !== "" || !items.length} onClick={decideAllExclude}>全部不入库</button>
              </>
            )}
            <button onClick={load}>刷新</button>
          </div>
          <div className="dec-list">
            {items.length === 0 && <div className="empty">没有文件</div>}
            {items.map((it) => (
              <div className="dec-row" key={it.rel}>
                <div className="dec-info">
                  <div className="name">
                    <span className="badge unreviewed">{EXT_LABEL[it.ext] || it.ext || "未知"}</span>{" "}
                    {it.rel.split("/").pop()}
                    {it.mb ? <span className="score"> · {it.mb}MB</span> : null}
                  </div>
                  <div className="path" title={it.rel}>{it.rel}</div>
                  <div className="reason">{it.reason || "—"}</div>
                </div>
                <div className="dec-actions">
                  {tab === "pending" ? (
                    <>
                      <button
                        className="vbtn ok"
                        disabled={busy !== ""}
                        title="纳入管理：可自动处理的格式（扫描件/图片/CAD/压缩包）会自动重跑识别评测"
                        onClick={() => decide(it, "include")}
                      >
                        入库
                      </button>
                      <button
                        className="vbtn rej"
                        disabled={busy !== ""}
                        title="标记无效材料，不计入任何失败统计，可随时撤销"
                        onClick={() => decide(it, "exclude")}
                      >
                        不入库
                      </button>
                    </>
                  ) : (
                    <>
                      <span className={`badge ${tab === "include" ? "trusted" : "rejected"}`}>
                        {tab === "include" ? "已入库" : "已排除"}
                      </span>
                      <button disabled={busy !== ""} onClick={() => undo(it)}>撤销</button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
