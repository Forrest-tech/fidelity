import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api, json } from "../net/client";
import { Pill } from "./ui";

interface Pending {
  rule: string;
  num: number;
  find: string;
  replace: string;
  room: string | null;
  rel: string;
  at: number;
  before: string;
  after: string;
}
interface Checks {
  pending: Pending[];
  total: number;
  right: number;
  wrong: number;
}

/** Fixes the AI adopted on its own (level 3) that were picked for a person to check. "Wrong" undoes the fix in that
 * document and puts the skill back to level 2. */
export function AutoChecks({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["auto-checks"], queryFn: () => api<Checks>("/ai/auto-checks") });
  const check = useMutation({
    mutationFn: (p: { rule: string; right: boolean }) => api<Checks>(`/ai/auto-checks/${p.rule}`, json({ right: p.right })),
    onSuccess: (d) => {
      qc.setQueryData(["auto-checks"], d);
      void qc.invalidateQueries({ queryKey: ["corrections"] });
      void qc.invalidateQueries({ queryKey: ["room-files"] });
      void qc.invalidateQueries({ queryKey: ["ai-settings"] });
    },
  });
  const d = q.data;
  if (!d || !d.total || !Array.isArray(d.pending)) return null; // nothing adopted automatically: nothing to show
  const busy = (rule: string, right: boolean) => check.isPending && check.variables?.rule === rule && check.variables.right === right;
  return (
    <section className="fx-card" aria-labelledby="auto-checks-h" style={{ padding: 14 }}>
      <div className="fx-row">
        <h3 id="auto-checks-h" className="fx-h3" style={{ margin: 0 }}>{t("pages.corrections.auto.title")}</h3>
        {d.pending.length > 0 && <Pill tone="warn">{d.pending.length}</Pill>}
      </div>
      <div className="fx-tiny fx-muted" style={{ marginTop: 4 }}>
        {t("pages.corrections.auto.summary", { total: d.total, right: d.right, wrong: d.wrong })}
      </div>
      {d.pending.length === 0 && <div className="fx-tiny fx-muted" style={{ marginTop: 8 }}>{t("pages.corrections.auto.none")}</div>}
      <div style={{ display: "grid", gap: 0, marginTop: 8 }}>
        {d.pending.map((p) => (
          <div key={p.rule} style={{ display: "grid", gap: 4, padding: "8px 0", borderTop: "1px solid var(--line)", minWidth: 0 }}>
            <span style={{ fontSize: 13, overflowWrap: "anywhere" }}>
              <span className="fx-muted">…{p.before} </span>
              <del>{p.find}</del> <ins>{p.replace}</ins>
              <span className="fx-muted"> {p.after}…</span>
            </span>
            <span className="fx-tiny fx-muted" style={{ overflowWrap: "anywhere" }}>
              <Pill tone="ai">{t("pages.distill.fix2.rule", { num: p.num })}</Pill> {p.room ?? ""} · {p.rel.split("/").pop()}
            </span>
            {canEdit && (
              <div className="fx-row fx-wrap" style={{ gap: 8 }}>
                <button className="fx-btn sm" disabled={check.isPending} aria-busy={busy(p.rule, true)}
                  onClick={() => check.mutate({ rule: p.rule, right: true })}>
                  {t("pages.corrections.auto.right")}
                </button>
                <button className="fx-btn sm" style={{ color: "var(--bad)" }} disabled={check.isPending} aria-busy={busy(p.rule, false)}
                  onClick={() => check.mutate({ rule: p.rule, right: false })}>
                  {t("pages.corrections.auto.wrong")}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {canEdit && d.pending.length > 0 && <div className="fx-tiny fx-muted" style={{ marginTop: 6 }}>{t("pages.corrections.auto.wrongNote")}</div>}
      {check.error && <div className="fx-errnote" role="alert" style={{ marginTop: 8 }}>{(check.error as Error).message}</div>}
    </section>
  );
}
