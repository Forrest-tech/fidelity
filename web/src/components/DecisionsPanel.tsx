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

/** 入库后可自动重跑识别的扩展名（扫描件/图片/CAD/压缩包）。 */
const REEVALUABLE = [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".dwg", ".dxf", ".zip"];

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

  const reviewer = props.reviewer || "";

  const decide = async (it: DecisionItem, decision: string) => {
    setBusy(it.rel);
    try {
      await api.setDecision(it.rel, decision, reviewer);
      if (decision === "include" && REEVALUABLE.includes(it.ext)) props.onReeval(it.rel);
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const decideAll = async (decision: "include" | "exclude") => {
    if (!items.length) return;
    const label = decision === "include" ? "入库" : "不入库";
    if (
      !confirm(
        `将把当前 ${items.length} 个待决定文件全部标记「${label}」` +
          (decision === "include" ? "，并对扫描件/图片/CAD/压缩包重跑识别评测" : "") +
          "。之后可逐个撤销。继续？"
      )
    )
      return;
    setBusy("__all__");
    try {
      for (const it of items) {
        await api.setDecision(it.rel, decision, reviewer, `批量标记${label}`);
        if (decision === "include" && REEVALUABLE.includes(it.ext)) props.onReeval(it.rel);
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
      await api.setDecision(it.rel, "", reviewer);
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="mask" onClick={props.onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>人工决定队列</h3>
          <span className="sub">无法自动比对的文件，入库与否由人工拍板</span>
          <div className="spacer" />
          <button onClick={props.onClose}>关闭</button>
        </header>
        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="tabs">
            <button className={tab === "pending" ? "on" : ""} onClick={() => setTab("pending")}>
              待决定
            </button>
            <button className={tab === "include" ? "on" : ""} onClick={() => setTab("include")}>
              已入库
            </button>
            <button className={tab === "exclude" ? "on" : ""} onClick={() => setTab("exclude")}>
              已排除
            </button>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 11 }}>
            <span className="dim num">共 {items.length} 个</span>
            <span className="dim">· 审核人 {reviewer || "未选择"}</span>
            <div className="spacer" />
            {tab === "pending" && (
              <>
                <button disabled={busy !== "" || !items.length} onClick={() => decideAll("include")}>
                  全部入库
                </button>
                <button disabled={busy !== "" || !items.length} onClick={() => decideAll("exclude")}>
                  全部不入库
                </button>
              </>
            )}
            <button onClick={load}>刷新</button>
          </div>

          <div className="list">
            {items.length === 0 && <div className="empty">没有文件</div>}
            {items.map((it) => (
              <div className="lrow" key={it.rel}>
                <div className="info">
                  <div className="nm">
                    <span className="badge unreviewed">{EXT_LABEL[it.ext] || it.ext || "未知"}</span>
                    <span className="truncate">{it.rel.split("/").pop()}</span>
                    {it.mb ? <span className="dim num">{it.mb}MB</span> : null}
                  </div>
                  <div className="pp">{it.rel}</div>
                  <div className="st" style={{ color: "var(--amber)" }}>{it.reason || "—"}</div>
                </div>
                <div className="a">
                  {tab === "pending" ? (
                    <>
                      <button
                        className="vbtn ok"
                        disabled={busy !== ""}
                        title="纳入管理：可自动处理的格式会自动重跑识别评测"
                        onClick={() => decide(it, "include")}
                      >
                        入库
                      </button>
                      <button
                        className="vbtn rej"
                        disabled={busy !== ""}
                        title="标记无效材料，不计入失败统计，可随时撤销"
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
                      <button disabled={busy !== ""} onClick={() => undo(it)}>
                        撤销
                      </button>
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
