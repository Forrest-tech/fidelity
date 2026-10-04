import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { SalvageItem } from "../types";
import { useI18n } from "../i18n";

/**
 * 「原转换无效」清单：这些文件的 .md 是二进制字符串打捞产物
 * （AC1032 / RdAkRdAkRdA …），不是文档内容，自动分必然很低。
 * 现在有了真实提取能力（CAD 文字 / OCR），可以一键重新转换。
 *
 * 安全：写盘前自动备份为 .md.salvage.bak；只处理用户显式点击的文件。
 */
export default function SalvagePanel(props: {
  sid: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [t] = useI18n();
  const [items, setItems] = useState<SalvageItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [log, setLog] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const d = await api.salvage();
      setItems(d.items);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (rels: string[]) => {
    if (!rels.length) return;
    setBusy(true);
    setLog([]);
    try {
      const r = await api.reconvert(rels, props.sid);
      setLog(r.items.slice(0, 10).map((x) => `${x.rel.split("/").pop()} → ${x.msg}`));
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runAll = () => {
    if (!items.length) return;
    if (!confirm(t("salvage.confirmAll", { n: items.length }))) return;
    run(items.map((i) => i.rel));
  };

  return (
    <div className="mask" onClick={props.onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>{t("salvage.title")}</h3>
          <span className="sub">{t("salvage.sub")}</span>
          <div className="spacer" />
          <button onClick={props.onClose}>{t("salvage.close")}</button>
        </header>
        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="callout warn">
            {t("salvage.desc")} <code>AC1032 / RdAkRdAkRdA</code>.{" "}
            <b>{t("salveKey.title")}</b> {t("salvage.descTail")}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 11 }}>
            <span className="dim num">{t("salvage.total", { n: items.length })}</span>
            <div className="spacer" />
            <button className="primary" disabled={busy || !items.length} onClick={runAll}>
              {t("salvage.runAll")}
            </button>
            <button onClick={load} disabled={busy}>
              {t("salvage.refresh")}
            </button>
          </div>

          {busy && (
            <div className="callout">
              <span className="spin" /> {t("salvage.running")}
            </div>
          )}
          {log.length > 0 && (
            <div className="list" style={{ marginBottom: 11 }}>
              {log.map((l, i) => (
                <div className="lrow" key={i}>
                  <div className="info">
                    <div className="st" style={{ color: "var(--text-2)", fontFamily: "var(--mono)" }}>{l}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="list">
            {items.length === 0 && <div className="empty">{t("salvage.empty")}</div>}
            {items.map((it) => (
              <div className="lrow" key={it.rel}>
                <div className="info">
                  <div className="nm">
                    <span className="truncate">{it.rel.split("/").pop()}</span>
                    {it.auto_score != null && <span className="dim num">{t("salvage.current", { n: it.auto_score })}</span>}
                  </div>
                  <div className="pp">{it.rel}</div>
                  <div className="st" style={{ color: "var(--amber)" }}>
                    {it.engine_b ? t("salvage.engine", { e: it.engine_b }) : ""}
                    {(it.fail_reasons || "").slice(0, 140)}
                  </div>
                </div>
                <div className="a">
                  <button className="vbtn ok" disabled={busy} onClick={() => run([it.rel])}>
                    {t("salvage.runOne")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
