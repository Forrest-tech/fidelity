import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { SalvageItem } from "../types";

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
  const [items, setItems] = useState<SalvageItem[]>([]);
  const [busy, setBusy] = useState("");
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
    setBusy("__run__");
    setLog([]);
    try {
      const r = await api.reconvert(rels, props.sid);
      setLog(
        r.items.slice(0, 8).map((x) => `${x.rel.split("/").pop()} → ${x.msg}`)
      );
      await load();
      props.onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const runAll = () => {
    if (!items.length) return;
    if (
      !confirm(
        `将对 ${items.length} 个文件重新转换：\n` +
          `· 用真实提取结果（CAD 文字 / OCR）重写 .md\n` +
          `· 原文件自动备份为 .md.salvage.bak，可回滚\n` +
          `· 转换后立刻重评打分\n\n继续？`
      )
    )
      return;
    run(items.map((i) => i.rel));
  };

  return (
    <div className="modal-mask" onClick={props.onClose}>
      <div
        className="modal"
        style={{ width: 860, maxHeight: "82vh" }}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h3>重新转换 — 原转换产物无效的文件</h3>
          <div className="spacer" />
          <button onClick={props.onClose}>关闭</button>
        </header>
        <div className="body">
          {err && (
            <div className="notice err" onClick={() => setErr("")}>
              {err}（点击关闭）
            </div>
          )}
          <div className="notice" style={{ marginBottom: 10 }}>
            这些 .md 是原转换管线的「二进制字符串打捞」产物（内容形如
            <code> AC1032 / RdAkRdAkRdA</code>
            ），不是文档内容，所以自动分很低。<b>问题在转换侧，不在源文件侧。</b>
            重写会保留原 front-matter（hash、来源信息不变），正文换成真实提取结果，
            并把原文件备份为 <code>.md.salvage.bak</code>。
          </div>
          <div className="filter-row" style={{ marginBottom: 10 }}>
            <span className="score">共 {items.length} 个</span>
            <div className="spacer" />
            <button disabled={busy !== "" || !items.length} onClick={runAll}>
              全部重新转换
            </button>
            <button onClick={load}>刷新</button>
          </div>
          {log.length > 0 && (
            <div className="dec-list" style={{ marginBottom: 10 }}>
              {log.map((l, i) => (
                <div key={i} className="reason">
                  {l}
                </div>
              ))}
            </div>
          )}
          <div className="dec-list">
            {items.length === 0 && <div className="empty">没有需要重新转换的文件</div>}
            {items.map((it) => (
              <div className="dec-row" key={it.rel}>
                <div className="dec-info">
                  <div className="name">
                    {it.rel.split("/").pop()}
                    {it.auto_score != null ? (
                      <span className="score"> · 当前 {it.auto_score}%</span>
                    ) : null}
                  </div>
                  <div className="path" title={it.rel}>
                    {it.rel}
                  </div>
                  <div className="reason">
                    {it.engine_b ? `引擎 ${it.engine_b} · ` : ""}
                    {(it.fail_reasons || "").slice(0, 120)}
                  </div>
                </div>
                <div className="dec-actions">
                  <button
                    className="vbtn ok"
                    disabled={busy !== ""}
                    onClick={() => run([it.rel])}
                  >
                    重新转换
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
