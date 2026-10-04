import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Reviewer } from "../types";

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
  const [items, setItems] = useState<Reviewer[]>([]);
  const [name, setName] = useState("");
  const [role, setRole] = useState("审核人");
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
      await api.saveReviewer({ name: name.trim(), role: role.trim() || "审核人" });
      setName("");
      setRole("审核人");
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
    if (!confirm(`删除审核人「${r.name}」？\n\n已产生的裁决记录与审计日志会保留（历史可追溯），\n但此人将不再出现在选择列表中。`)) return;
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
          <h3>审核人配置</h3>
          <span className="sub">裁决与入库决定都只能由名单内的人做出，保证审计身份唯一</span>
          <div className="spacer" />
          <button onClick={onClose}>关闭</button>
        </header>

        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="callout">
            当前使用：<b>{current || "未选择"}</b>。在下方点「设为当前」切换，或在底部裁决栏直接下拉选择。
          </div>

          <div className="list">
            {items.length === 0 && <div className="empty">名单为空，请先添加审核人</div>}
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
                      title="点击改名"
                      readOnly={!!r.orphan}
                    />
                    <span className="badge unreviewed">{r.role}</span>
                    {current === r.name && <span className="badge trusted">当前</span>}
                    {!r.enabled && <span className="badge rejected">已停用</span>}
                    {r.orphan && (
                      <span className="badge need_review" title="历史数据中的审核人，未登记进名单">
                        未登记
                      </span>
                    )}
                  </div>
                  <div className="counts" style={{ marginTop: 3 }}>
                    <span>裁决 <b>{r.verdicts}</b></span>
                    <span style={{ color: "var(--green)" }}>一致 {r.ok}</span>
                    <span style={{ color: "var(--red)" }}>差异大 {r.diff_big}</span>
                    <span>不接受 {r.rejected}</span>
                    <span>入库决定 {r.decisions}</span>
                  </div>
                </div>
                <div className="a">
                  {current !== r.name && r.enabled && (
                    <button className="sm" onClick={() => onPick(r.name)}>
                      设为当前
                    </button>
                  )}
                  {!r.orphan && (
                    <button className="sm" disabled={busy} onClick={() => toggle(r)}>
                      {r.enabled ? "停用" : "启用"}
                    </button>
                  )}
                  {!r.orphan && (
                    <button className="sm danger" disabled={busy} onClick={() => remove(r)}>
                      删除
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
            <div className="row3">
              <div className="field" style={{ margin: 0 }}>
                <label>姓名</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && add()}
                  placeholder="真实姓名或工号"
                />
              </div>
              <div className="field" style={{ margin: 0 }}>
                <label>角色</label>
                <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="审核人" />
              </div>
              <div />
              <button className="primary" disabled={busy || !name.trim()} onClick={add}>
                添加
              </button>
            </div>
            <div className="help dim" style={{ fontSize: 11.5, marginTop: 6 }}>
              姓名可点击就地修改；至少保留一位启用中的审核人。
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
