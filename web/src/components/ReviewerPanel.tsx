import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Reviewer } from "../types";
import { useI18n } from "../i18n";

/**
 * 审核人配置（用户 2026-10-05：不能自由输入，要能管理）。
 *
 * 存在的理由：自由输入会让同一个人的拼写变体（Forrest / forrest / Forrest Lin）
 * 在审计日志里裂成多个身份，统计与追溯全部失真 —— 受监管场景不可接受。
 * 这里集中维护名单，裁决时只能从名单里选。
 */
export default function ReviewerPanel({
  current,
  onPick,
  onClose,
}: {
  current: string;
  onPick: (name: string) => void;
  onClose: () => void;
}) {
  const [t] = useI18n();
  const [items, setItems] = useState<Reviewer[]>([]);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.reviewers();
      setItems(r.items);
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.saveReviewer({ name: name.trim(), role: role.trim() || t("reviewer.roleDefault") });
      setName("");
      setRole("");
      await load();
      setErr("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (r: Reviewer) => {
    setBusy(true);
    try {
      await api.saveReviewer({ id: r.id, name: r.name, role: r.role, enabled: !r.enabled });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const rename = async (r: Reviewer, newName: string) => {
    const v = newName.trim();
    if (!v || v === r.name) return;
    setBusy(true);
    try {
      await api.saveReviewer({ id: r.id, name: v, role: r.role, enabled: r.enabled });
      await load();
    } catch (e: any) {
      setErr(e.message);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const remove = async (r: Reviewer) => {
    if (!confirm(t("reviewer.confirmRemove", { name: r.name }))) return;
    setBusy(true);
    try {
      await api.deleteReviewer(r.id);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>{t("reviewer.title")}</h3>
          <span className="sub">{t("reviewer.sub")}</span>
          <div className="spacer" />
          <button onClick={onClose}>{t("src.close")}</button>
        </header>

        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="callout">
            {t("reviewer.currentUsing", { name: current || "—" })}
          </div>

          <div className="list">
            {items.length === 0 && <div className="empty">{t("reviewer.emptyList")}</div>}
            {items.map((r) => (
              <div className="lrow" key={r.id || r.name}>
                <div className="info">
                  <div className="nm">
                    <input
                      defaultValue={r.name}
                      onBlur={(e) => rename(r, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                      }}
                      style={{ width: 150, fontWeight: 600, padding: "3px 7px" }}
                      title={t("reviewer.renameTip")}
                      readOnly={!!r.orphan}
                    />
                    <span className="badge unreviewed">{r.role}</span>
                    {current === r.name && <span className="badge trusted">{t("reviewer.current")}</span>}
                    {!r.enabled && <span className="badge rejected">{t("reviewer.disabled")}</span>}
                    {r.orphan && (
                      <span className="badge need_review" title={t("reviewer.unregisteredTip")}>
                        {t("reviewer.unregistered")}
                      </span>
                    )}
                  </div>
                  <div className="counts" style={{ marginTop: 3 }}>
                    {t("reviewer.counts", {
                      v: r.verdicts,
                      ok: r.ok,
                      diff: r.diff_big,
                      rej: r.rejected,
                      dec: r.decisions,
                    })}
                  </div>
                </div>
                <div className="a">
                  {current !== r.name && r.enabled && (
                    <button className="sm" onClick={() => onPick(r.name)}>
                      {t("reviewer.setCurrent")}
                    </button>
                  )}
                  {!r.orphan && (
                    <button className="sm" disabled={busy} onClick={() => toggle(r)}>
                      {r.enabled ? t("reviewer.disable") : t("reviewer.enable")}
                    </button>
                  )}
                  {!r.orphan && (
                    <button className="sm danger" disabled={busy} onClick={() => remove(r)}>
                      {t("reviewer.remove")}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
            <div className="row3">
              <div className="field" style={{ margin: 0 }}>
                <label>{t("reviewer.name")}</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && add()}
                  placeholder={t("reviewer.namePh")}
                />
              </div>
              <div className="field" style={{ margin: 0 }}>
                <label>{t("reviewer.role")}</label>
                <input value={role} onChange={(e) => setRole(e.target.value)} placeholder={t("reviewer.rolePh")} />
              </div>
              <div />
              <button className="primary" disabled={busy || !name.trim()} onClick={add}>
                {t("reviewer.add")}
              </button>
            </div>
            <div className="help dim" style={{ fontSize: 11.5, marginTop: 6 }}>
              {t("reviewer.footNote")}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
