import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { DecisionItem } from "../types";
import { useI18n } from "../i18n";

/** 扩展名 → i18n key。标签会随语言切换，源文件名本身永远不翻译。 */
const EXT_KEY: Record<string, string> = {
  ".dwg": "ext.cad",
  ".dxf": "ext.cad",
  ".rfa": "ext.rfa",
  ".rvt": "ext.rvt",
  ".pdf": "ext.pdf",
  ".jpg": "ext.img",
  ".jpeg": "ext.img",
  ".png": "ext.img",
  ".tif": "ext.img",
  ".zip": "ext.zip",
  ".mp4": "ext.video",
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
  const [t] = useI18n();
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
    const label = decision === "include" ? t("decide.include") : t("decide.exclude");
    if (
      !confirm(
        t("decide.confirmAll", {
          n: items.length,
          label,
          extra: decision === "include" ? t("decide.confirmAllExtra") : "",
        })
      )
    )
      return;
    setBusy("__all__");
    try {
      for (const it of items) {
        await api.setDecision(it.rel, decision, reviewer, t("decide.batchNote", { label }));
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
          <h3>{t("decide.title")}</h3>
          <span className="sub">{t("decide.sub")}</span>
          <div className="spacer" />
          <button onClick={props.onClose}>{t("decide.close")}</button>
        </header>
        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="tabs">
            <button className={tab === "pending" ? "on" : ""} onClick={() => setTab("pending")}>
              {t("decide.tabPending")}
            </button>
            <button className={tab === "include" ? "on" : ""} onClick={() => setTab("include")}>
              {t("decide.tabInclude")}
            </button>
            <button className={tab === "exclude" ? "on" : ""} onClick={() => setTab("exclude")}>
              {t("decide.tabExclude")}
            </button>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 11 }}>
            <span className="dim num">{t("decide.total", { n: items.length })}</span>
            <span className="dim">{t("decide.reviewerOf", { name: reviewer || t("decide.noReviewer") })}</span>
            <div className="spacer" />
            {tab === "pending" && (
              <>
                <button disabled={busy !== "" || !items.length} onClick={() => decideAll("include")}>
                  {t("decide.allInclude")}
                </button>
                <button disabled={busy !== "" || !items.length} onClick={() => decideAll("exclude")}>
                  {t("decide.allExclude")}
                </button>
              </>
            )}
            <button onClick={load}>{t("decide.refresh")}</button>
          </div>

          <div className="list">
            {items.length === 0 && <div className="empty">{t("decide.empty")}</div>}
            {items.map((it) => (
              <div className="lrow" key={it.rel}>
                <div className="info">
                  <div className="nm">
                    <span className="badge unreviewed">{EXT_KEY[it.ext] ? t(EXT_KEY[it.ext] as never) : it.ext || t("decide.unknown")}</span>
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
                        title={t("decide.includeTip")}
                        onClick={() => decide(it, "include")}
                      >
                        {t("decide.include")}
                      </button>
                      <button
                        className="vbtn rej"
                        disabled={busy !== ""}
                        title={t("decide.excludeTip")}
                        onClick={() => decide(it, "exclude")}
                      >
                        {t("decide.exclude")}
                      </button>
                    </>
                  ) : (
                    <>
                      <span className={`badge ${tab === "include" ? "trusted" : "rejected"}`}>
                        {tab === "include" ? t("decide.included") : t("decide.excluded")}
                      </span>
                      <button disabled={busy !== ""} onClick={() => undo(it)}>
                        {t("decide.undo")}
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
