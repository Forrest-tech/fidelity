import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { Modal } from "antd";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorState, Loading, PageHeader, Pill } from "../components/ui";
import { RuleSuggestions } from "../components/RuleSuggestions";

interface Rule {
  id: string;
  num: number;
  find: string;
  replace: string;
  before: string;
  after: string;
  kind: "text" | "number" | "pattern";
  scope: "document" | "series" | "all";
  series: string | null;
  doc: string | null;
  enabled: boolean;
  reverts: number;
  hits: number;
  documents: number;
  often_undone: boolean;
  source_name: string;
  created_by: string;
  created_at: number;
}
interface Library {
  rules: Rule[];
  total: number;
  enabled: number;
  disabled: number;
  often_undone: number;
}
interface Doc {
  room_id: string;
  room: string;
  rel: string;
  places: number;
}
type Filter = "all" | "on" | "off" | "undone";

/** The correction library (screen 3 of the design): every confirmed fix, where it applies, how often it is used and
 * undone; switching one shows the documents it touches and updates them in one step. */
export function CorrectionsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const focus = params.get("rule");
  const canEdit = me?.role === "reviewer" || me?.role === "admin";
  const [filter, setFilter] = useState<Filter>("all");
  const [changed, setChanged] = useState<{ rule: Rule; docs: Doc[] } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const lib = useQuery({ queryKey: ["corrections"], queryFn: () => api<Library>("/corrections") });
  const refresh = () => {
    for (const k of ["corrections", "room-files", "rooms", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
  };
  const toggle = useMutation({
    mutationFn: (p: { id: string; enabled: boolean }) => api<{ rule: Rule; affected: Doc[] }>(`/corrections/${p.id}`, { ...json({ enabled: p.enabled }), method: "PATCH" }),
    onSuccess: (r) => {
      refresh();
      if (r.affected.length) setChanged({ rule: r.rule, docs: r.affected });
    },
  });
  const apply = useMutation({
    mutationFn: (id: string) => api<{ documents: number; changed: number }>(`/corrections/${id}/apply`, { method: "POST" }),
    onSuccess: (r) => {
      setChanged(null);
      setDone(t("pages.corrections.appliedDone", { count: r.changed }));
      refresh();
    },
  });
  const check = useMutation({
    mutationFn: (rule: Rule) => api<{ documents: Doc[] }>(`/corrections/${rule.id}/affected`),
    onSuccess: (r, rule) => setChanged({ rule, docs: r.documents }),
  });
  useEffect(() => {
    if (focus) setTimeout(() => document.getElementById(`rule-${focus}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" }), 300);
  }, [focus, lib.data]);
  const err = (toggle.error || apply.error || check.error) as Error | null;
  const d = lib.data;
  const rows = (d?.rules ?? []).filter((r) => (filter === "on" ? r.enabled : filter === "off" ? !r.enabled : filter === "undone" ? r.often_undone : true));

  const exportRules = () => {
    const blob = new Blob([JSON.stringify(d?.rules ?? [], null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "correction-rules.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const scopeText = (r: Rule) => (r.scope === "all" ? t("pages.corrections.scopeAll") : r.scope === "series" ? t("pages.corrections.scopeSeries", { series: r.series }) : r.doc ?? "");

  return (
    <>
      <PageHeader title={t("pages.corrections.title")} desc={t("pages.corrections.intro")}
        extra={<button className="fx-btn" disabled={!d?.total} onClick={exportRules}>{t("pages.corrections.export")}</button>} />
      {err && <div className="fx-errnote" role="alert">{err.message}</div>}
      {done && <div className="fx-note" role="status">{done} <button className="fx-a" onClick={() => setDone(null)}>{t("pages.distill.dismiss")}</button></div>}
      <RuleSuggestions canEdit={canEdit} onApproved={(a) => { refresh(); if (a.affected.length) setChanged({ rule: a.rule as unknown as Rule, docs: a.affected }); }} />
      {lib.isLoading && <Loading />}
      {lib.isError && <ErrorState message={(lib.error as Error).message} onRetry={() => void lib.refetch()} />}
      {d && d.total === 0 && <EmptyState title={t("pages.corrections.empty")} hint={t("pages.corrections.emptyHint")} />}
      {d && d.total > 0 && (
        <>
          <div className="fx-chips" role="group" aria-label={t("pages.corrections.filter")}>
            {([["all", `${t("pages.corrections.all")} ${d.total}`], ["on", `${t("pages.corrections.on")} ${d.enabled}`], ["off", `${t("pages.corrections.off")} ${d.disabled}`], ["undone", `${t("pages.corrections.undone")} ${d.often_undone}`]] as [Filter, string][]).map(([k, label]) => (
              <button key={k} className={`fx-chip${filter === k ? " on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
            ))}
          </div>
          <div className="fx-tbox" style={{ overflowX: "auto" }}>
            <table className="fx-t" style={{ minWidth: 760 }}>
              <thead><tr><th>{t("pages.corrections.colFix")}</th><th>{t("pages.corrections.colScope")}</th><th>{t("pages.corrections.colSource")}</th><th>{t("pages.corrections.colHits")}</th><th>{t("pages.corrections.colUndone")}</th><th><span className="sr-only">{t("pages.distill.colActions")}</span></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} id={`rule-${r.id}`} className={r.often_undone || r.id === focus ? "sel" : undefined} style={r.enabled ? undefined : { opacity: 0.65 }}>
                    <td>
                      <span className="fx-muted fx-tiny">#{r.num} </span>
                      <code>{r.find}</code> → <code>{r.replace}</code>
                      {r.kind === "pattern" && <> <Pill tone="run">{t("pages.corrections.pattern")}</Pill></>}
                      {!r.enabled && <> <Pill tone="idle">{t("pages.corrections.off")}</Pill></>}
                      {r.kind === "number" && (
                        <div className="fx-tiny fx-muted">{t("pages.corrections.onlyIn")} <code>{r.before}<mark>{r.find}</mark>{r.after}</code></div>
                      )}
                    </td>
                    <td>{scopeText(r)}</td>
                    <td className="fx-tiny">{r.source_name || t("pages.corrections.fromSuggestion")} · {r.created_by}<div className="fx-muted">{new Date(r.created_at * 1000).toLocaleDateString()}</div></td>
                    <td className="fx-num">{r.hits} <span className="fx-muted fx-tiny">{t("pages.corrections.inDocs", { count: r.documents })}</span></td>
                    <td className="fx-num">{r.often_undone ? <Pill tone="warn">{r.reverts}</Pill> : r.reverts}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {canEdit && (r.often_undone
                        ? <button className="fx-a" onClick={() => check.mutate(r)}>{t("pages.corrections.check")}</button>
                        : <button className="fx-a" aria-label={t("pages.corrections.toggle", { num: r.num })} onClick={() => toggle.mutate({ id: r.id, enabled: !r.enabled })}>
                            {r.enabled ? t("pages.corrections.disable") : t("pages.corrections.enable")}
                          </button>)}
                      {canEdit && r.often_undone && <> · <button className="fx-a" onClick={() => toggle.mutate({ id: r.id, enabled: !r.enabled })}>{r.enabled ? t("pages.corrections.disable") : t("pages.corrections.enable")}</button></>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <Modal open={!!changed} onCancel={() => setChanged(null)} width={400}
        title={changed ? t("pages.corrections.rerunTitle") : ""}
        footer={changed ? [
          <button key="c" className="fx-btn" onClick={() => setChanged(null)}>{t("pages.corrections.later")}</button>,
          <button key="a" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={apply.isPending || !canEdit} onClick={() => apply.mutate(changed.rule.id)}>
            {t("pages.corrections.applyTo", { count: changed.docs.length })}
          </button>,
        ] : null}>
        {changed && (
          <div className="fx-stack" style={{ gap: 8 }}>
            <div className="fx-tiny fx-muted">
              {t(changed.rule.enabled ? "pages.corrections.changedOn" : "pages.corrections.changedOff", { count: changed.docs.length, num: changed.rule.num })}
            </div>
            <div className="fx-tbox" style={{ maxHeight: 260, overflowY: "auto" }}>
              <table className="fx-t"><tbody>
                {changed.docs.map((x) => <tr key={x.room_id + x.rel}><td>{x.rel.split("/").pop()}<div className="fx-tiny fx-muted">{x.room}</div></td><td className="fx-num">{x.places ? t("pages.corrections.places", { count: x.places }) : "—"}</td></tr>)}
              </tbody></table>
            </div>
            <div className="fx-tiny fx-muted">{t("pages.corrections.keepsUndone")}</div>
          </div>
        )}
      </Modal>
    </>
  );
}
