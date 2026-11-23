import { useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { useTheme } from "../layout/ThemeProvider";
import type { Theme } from "../layout/ThemeProvider";
import { EmptyState, ErrorState, Loading, PageHeader, Pill, Seg } from "../components/ui";
import { CloudStorage, GoogleDrive } from "../components/CloudStorage";
import { AiSettings } from "../components/AiSettings";
import { CorrectionsPage } from "./CorrectionsPage";
import { UsersPage } from "./UsersPage";

type Section = "storage" | "ai" | "defaults" | "queue" | "corrections" | "archive" | "users" | "notifications" | "audit" | "system" | "email" | "account" | "appearance";
interface Item {
  key: Section;
  group: "connect" | "distill" | "team" | "personal";
  admin?: boolean;
}
const ITEMS: Item[] = [
  { key: "storage", group: "connect", admin: true },
  { key: "ai", group: "connect", admin: true },
  { key: "email", group: "connect", admin: true },
  { key: "defaults", group: "distill", admin: true },
  { key: "queue", group: "distill" },
  { key: "corrections", group: "distill" },
  { key: "archive", group: "distill" },
  { key: "users", group: "team", admin: true },
  { key: "notifications", group: "team" },
  { key: "audit", group: "team", admin: true },
  { key: "system", group: "team", admin: true },
  { key: "account", group: "personal" },
  { key: "appearance", group: "personal" },
];

// ------------------------------------------------------------------ sections
function Defaults() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["defaults"], queryFn: () => api<{ threshold: number; number_guard: boolean; mode: "distill" | "upload"; ocr_protected?: boolean; weights: Record<string, number> }>("/app-settings/defaults") });
  const [thr, setThr] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (b: Record<string, unknown>) => api("/app-settings/defaults", { ...json(b), method: "PUT" }),
    onSuccess: (d) => {
      qc.setQueryData(["defaults"], d);
      setThr(null);
    },
  });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message} />;
  const d = q.data!;
  const v = thr ?? String(d.threshold);
  return (
    <>
      <PageHeader title={t("pages.settings.nav.defaults")} desc={t("pages.settings.defaultsHint")} />
      <div className="fx-card" style={{ padding: 14 }}>
        <div className="fx-stack" style={{ gap: 12 }}>
          <div className="fx-row fx-wrap">
            <b style={{ width: 160 }}>{t("pages.distill.thresholdShort")}</b>
            <label className="fx-field sm" style={{ width: 90 }}>
              <input className="fx-num" value={v} inputMode="decimal" aria-label={t("pages.distill.thresholdShort")} onChange={(e) => setThr(e.target.value.replace(/[^\d.]/g, ""))} />
              <span className="fx-muted">%</span>
            </label>
            <button className="fx-btn sm pri" disabled={thr === null || !thr.trim() || save.isPending} onClick={() => save.mutate({ threshold: Number(v) })}>{t("pages.distill.save")}</button>
          </div>
          <label className="fx-row">
            <span style={{ width: 160 }}><b>{t("pages.settings.numberGuard")}</b></span>
            <input type="checkbox" className="fx-cb" checked={d.number_guard} onChange={(e) => save.mutate({ number_guard: e.target.checked })} />
            <span className="fx-tiny fx-muted">{t("pages.distill.numberGuardLong")}</span>
          </label>
          <label className="fx-row">
            <span style={{ width: 160 }}><b>{t("pages.settings.ocrProtected")}</b></span>
            <input type="checkbox" className="fx-cb" checked={!!d.ocr_protected} onChange={(e) => save.mutate({ ocr_protected: e.target.checked })} />
            <span className="fx-tiny fx-muted">{t("pages.settings.ocrProtectedLong")}</span>
          </label>
          <div className="fx-row fx-wrap">
            <b style={{ width: 160 }}>{t("pages.distill.afterDistill")}</b>
            <Seg label={t("pages.distill.afterDistill")} value={d.mode} onChange={(m) => save.mutate({ mode: m })}
              options={[{ value: "distill", label: t("pages.distill.modeDistill") }, { value: "upload", label: t("pages.distill.modeUpload") }]} />
          </div>
          {save.error && <div className="fx-errnote">{(save.error as Error).message}</div>}
          <div className="fx-tiny fx-muted">{t("pages.settings.defaultsApply")}</div>
        </div>
      </div>
      <div className="fx-card" style={{ padding: 14 }}>
        <h3 className="fx-h3">{t("pages.settings.accuracyHow")}</h3>
        <div className="fx-tbox">
          <table className="fx-t">
            <thead><tr><th>{t("pages.settings.check")}</th><th>{t("pages.settings.weight")}</th></tr></thead>
            <tbody>{Object.entries(d.weights).map(([k, w]) => <tr key={k}><td>{t(`pages.settings.checks.${k}`, { defaultValue: k })}</td><td className="fx-num">{Math.round(w * 100)}%</td></tr>)}</tbody>
          </table>
        </div>
        <div className="fx-tiny fx-muted" style={{ marginTop: 8 }}>{t("pages.settings.accuracyNote")}</div>
      </div>
    </>
  );
}

function Queue() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api<{ capacity: number; used: number; running: { name: string; points: number }[]; queued: { name: string; position: number }[] }>("/queue"), refetchInterval: 5000 });
  if (q.isLoading) return <Loading />;
  const d = q.data;
  return (
    <>
      <PageHeader title={t("pages.settings.nav.queue")} desc={t("pages.settings.queueHint")} />
      {d && (
        <div className="fx-card" style={{ padding: 14 }}>
          <div className="fx-stack" style={{ gap: 10 }}>
            <div className="fx-row fx-wrap" style={{ gap: 18 }}>
              <span>{t("pages.distill.capacityIs")} <b className="fx-num">{t("pages.distill.points", { count: d.capacity })}</b></span>
              <span>{t("pages.distill.runningN")} <b className="fx-num">{d.running.length}</b></span>
              <span>{t("pages.distill.waitingN")} <b className="fx-num">{d.queued.length}</b></span>
            </div>
            <div className="fx-tiny fx-muted">{t("pages.distill.capacityAuto", { n: d.capacity })}</div>
            <div className="fx-note">{t("pages.distill.queueRules")}</div>
            <Link to="/distill" className="fx-a">{t("pages.settings.toDistill")}</Link>
          </div>
        </div>
      )}
    </>
  );
}

function Archive() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["rooms", "archived"], queryFn: () => api<{ rooms: { id: string; name: string; counts: { total: number }; archived_at?: number }[] }>("/rooms?archived=true") });
  return (
    <>
      <PageHeader title={t("pages.settings.nav.archive")} desc={t("pages.settings.archiveHint")} />
      <div className="fx-card" style={{ padding: 14 }}>
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
          <li>{t("pages.settings.archiveWhen")}</li>
          <li>{t("pages.settings.archiveAfter")}</li>
          <li>{t("pages.settings.archiveRollback")}</li>
        </ul>
      </div>
      {q.data && !q.data.rooms.length && <EmptyState title={t("pages.distill.emptyArchived")} />}
      {q.data && q.data.rooms.length > 0 && (
        <div className="fx-tbox">
          <table className="fx-t">
            <thead><tr><th>{t("pages.distill.colRoom")}</th><th>{t("pages.distill.colContent")}</th><th>{t("pages.distill.colArchived")}</th></tr></thead>
            <tbody>{q.data.rooms.map((r) => (
              <tr key={r.id}><td><Link to={`/distill?room=${r.id}`}><b>{r.name}</b></Link></td><td className="fx-num">{t("pages.distill.fileCount", { count: r.counts.total })}</td>
                <td className="fx-muted fx-tiny">{r.archived_at ? new Date(r.archived_at * 1000).toLocaleDateString() : ""}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </>
  );
}

const NOTE_TYPES = ["done", "failed", "unprocessable", "review", "ai_budget", "rule_undone"] as const;
function Notifications() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const read = useMutation({ mutationFn: () => api("/notifications/read", json({ all: true })), onSuccess: (d) => qc.setQueryData(["notifications"], d) });
  const pref = useQuery({ queryKey: ["notify-mail"], queryFn: () => api<{ email: boolean; eligible: boolean; mail_ready: boolean }>("/notifications/email") });
  const setPref = useMutation({
    mutationFn: (email: boolean) => api("/notifications/email", { ...json({ email }), method: "PUT" }),
    onSuccess: (d) => qc.setQueryData(["notify-mail"], d),
  });
  return (
    <>
      <PageHeader title={t("pages.settings.nav.notifications")} desc={t("pages.settings.notificationsHint")} />
      {pref.data?.eligible && (
        <div className="fx-row">
          <label className="fx-row" style={{ gap: 8 }}>
            <input type="checkbox" className="fx-cb" checked={pref.data.email} disabled={setPref.isPending}
              onChange={(e) => setPref.mutate(e.target.checked)} />
            {t("pages.settings.mailMe")}
          </label>
          {!pref.data.mail_ready && <span className="fx-tiny fx-muted">{t("pages.settings.mailNotReady")}</span>}
        </div>
      )}
      <div className="fx-tbox">
        <table className="fx-t">
          <thead><tr><th>{t("pages.settings.event")}</th><th>{t("pages.settings.leadsTo")}</th></tr></thead>
          <tbody>{NOTE_TYPES.map((k) => (
            <tr key={k}><td><Pill tone={k === "done" ? "ok" : k === "review" || k === "rule_undone" ? "warn" : k === "ai_budget" ? "ai" : "bad"}>{t(`shell.n.${k}.pill`)}</Pill> {t(`pages.settings.events.${k}`)}</td>
              <td className="fx-muted">{t(`shell.n.${k}.to`)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="fx-row">
        <button className="fx-btn" onClick={() => read.mutate()}>{t("shell.markAllRead")}</button>
        <span className="fx-tiny fx-muted">{t("pages.settings.notificationsKeep")}</span>
      </div>
    </>
  );
}

interface Event { at: number; who: string; what: string; detail: string }
function Audit() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api<{ events: Event[] }>("/audit") });
  return (
    <>
      <PageHeader title={t("pages.settings.nav.audit")} desc={t("pages.settings.auditHint")} />
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} />}
      {q.data && !q.data.events.length && <EmptyState title={t("pages.settings.auditEmpty")} />}
      {q.data && q.data.events.length > 0 && (
        <div className="fx-tbox" style={{ maxHeight: 520, overflowY: "auto" }}>
          <table className="fx-t">
            <thead><tr><th>{t("pages.settings.when")}</th><th>{t("pages.settings.who")}</th><th>{t("pages.settings.what")}</th><th>{t("pages.settings.detail")}</th></tr></thead>
            <tbody>{q.data.events.map((e, i) => (
              <tr key={i}><td className="fx-num fx-tiny fx-muted" style={{ whiteSpace: "nowrap" }}>{new Date(e.at * 1000).toLocaleString()}</td><td>{e.who}</td>
                <td>{t(`pages.settings.audit.${e.what}`, { defaultValue: e.what })}</td><td className="fx-tiny" style={{ wordBreak: "break-word" }}>{e.detail}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ system health (requirements v2, phase D)
interface Alert { key: string; level: "bad" | "warn"; kind: string; free?: number; available?: number; failed?: number; total?: number; rate?: number; problem?: string }
interface Health {
  version: string; uptime_s: number; cpus: number;
  disk: { free: number; total: number }; memory: { available: number | null };
  runs: { days: number; done: number; failed: number; interrupted: number; total: number; failure_rate: number; queued: number; running: number; last_failure: { message: string; updated_at: number } | null };
  backup: { path: string; created: string; at: number; size: number; files: number; ok: boolean; problems: string[]; copied_to?: string } | null;
  alerts: Alert[];
}
const GB = (b: number) => (b / 1024 ** 3).toFixed(1);

function SystemHealth() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["system-health"], queryFn: () => api<Health>("/system/health"), refetchInterval: 30000 });
  const backup = useMutation({ mutationFn: () => api("/system/backup", { method: "POST" }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["system-health"] }) });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message} />;
  const h = q.data!;
  const since = (s: number) => (s >= 86400 ? t("pages.settings.sys.days", { n: Math.floor(s / 86400) })
    : s >= 3600 ? t("pages.settings.sys.hours", { n: Math.floor(s / 3600) }) : t("pages.settings.sys.minutes", { n: Math.max(1, Math.floor(s / 60)) }));
  const diskPct = Math.round((100 * (h.disk.total - h.disk.free)) / (h.disk.total || 1));
  return (
    <>
      <PageHeader title={t("pages.settings.nav.system")} desc={t("pages.settings.sys.hint")} />
      <div className="fx-stack" style={{ gap: 6 }} role="status" aria-live="polite">
        {h.alerts.length === 0 && <div className="fx-note">{t("pages.settings.sys.allWell")}</div>}
        {h.alerts.map((a) => (
          <div key={a.key} className={a.level === "bad" ? "fx-errnote" : "fx-note"}>
            <Pill tone={a.level === "bad" ? "bad" : "warn"}>{t(`pages.settings.sys.level.${a.level}`)}</Pill>{" "}
            {t(`shell.n.system.k.${a.kind}`, { gb: GB(a.free ?? 0), mb: Math.round((a.available ?? 0) / 1024 ** 2), failed: a.failed, total: a.total, pct: Math.round((a.rate ?? 0) * 100) })}
            {" — "}{t(`pages.settings.sys.do.${a.kind}`)}
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        <section className="fx-card" style={{ padding: 14 }} aria-label={t("pages.settings.sys.server")}>
          <h3 className="fx-h3">{t("pages.settings.sys.server")}</h3>
          <div className="fx-tiny fx-stack" style={{ gap: 4 }}>
            <div>{t("pages.settings.sys.version")} <b className="fx-num">{h.version}</b></div>
            <div>{t("pages.settings.sys.uptime")} <b>{since(h.uptime_s)}</b></div>
            <div>{t("pages.settings.sys.cpus")} <b className="fx-num">{h.cpus}</b></div>
            <div>{t("pages.settings.sys.memory")} <b className="fx-num">{h.memory.available == null ? "—" : `${GB(h.memory.available)} GB`}</b></div>
          </div>
        </section>
        <section className="fx-card" style={{ padding: 14 }} aria-label={t("pages.settings.sys.disk")}>
          <h3 className="fx-h3">{t("pages.settings.sys.disk")}</h3>
          <div className="fx-tiny">{t("pages.settings.sys.diskFree", { free: GB(h.disk.free), total: GB(h.disk.total) })}</div>
          <div role="progressbar" aria-valuenow={diskPct} aria-valuemin={0} aria-valuemax={100} aria-label={t("pages.settings.sys.diskUsed", { pct: diskPct })}
            style={{ marginTop: 8, height: 8, borderRadius: 4, background: "var(--sunken)", overflow: "hidden" }}>
            <div style={{ width: `${diskPct}%`, height: "100%", background: diskPct >= 90 ? "var(--bad)" : "var(--accent)" }} />
          </div>
        </section>
        <section className="fx-card" style={{ padding: 14 }} aria-label={t("pages.settings.sys.runs")}>
          <h3 className="fx-h3">{t("pages.settings.sys.runs")}</h3>
          <div className="fx-tiny fx-stack" style={{ gap: 4 }}>
            <div>{t("pages.settings.sys.runsLine", { done: h.runs.done, failed: h.runs.failed, interrupted: h.runs.interrupted, days: h.runs.days })}</div>
            <div>{t("pages.settings.sys.queueLine", { running: h.runs.running, queued: h.runs.queued })}</div>
            {h.runs.last_failure && <div className="fx-muted" style={{ wordBreak: "break-word" }}>{t("pages.settings.sys.lastFailure")}: {h.runs.last_failure.message}</div>}
          </div>
        </section>
        <section className="fx-card" style={{ padding: 14 }} aria-label={t("pages.settings.sys.backup")}>
          <h3 className="fx-h3">{t("pages.settings.sys.backup")}</h3>
          <div className="fx-tiny fx-stack" style={{ gap: 4 }}>
            {h.backup ? (
              <>
                <div>{t("pages.settings.sys.backupLast", { when: new Date(h.backup.at * 1000).toLocaleString() })}</div>
                <div>{h.backup.ok ? <Pill tone="ok">{t("pages.settings.sys.verified")}</Pill> : <Pill tone="bad">{t("pages.settings.sys.notVerified")}</Pill>}{" "}
                  <span className="fx-num">{t("pages.settings.sys.backupSize", { mb: (h.backup.size / 1e6).toFixed(1), count: h.backup.files })}</span></div>
                <div className="fx-muted">{h.backup.copied_to ? t("pages.settings.sys.copied", { to: h.backup.copied_to }) : t("pages.settings.sys.notCopied")}</div>
              </>
            ) : <div>{t("pages.settings.sys.noBackup")}</div>}
            <div><button className="fx-btn sm" disabled={backup.isPending} onClick={() => backup.mutate()}>{backup.isPending ? t("pages.settings.sys.backingUp") : t("pages.settings.sys.backupNow")}</button></div>
            {backup.error && <div className="fx-errnote" role="alert">{(backup.error as Error).message}</div>}
          </div>
        </section>
      </div>
      <div className="fx-tiny fx-muted">{t("pages.settings.sys.metrics")}</div>
    </>
  );
}

// ------------------------------------------------------------------ e-mail (requirements v2, U-1)
interface MailSettings { host: string; port: number; security: "starttls" | "ssl" | "none"; username: string; from_address: string; from_name: string; site_url: string; approval: "domains" | "all" | "none"; password_set: boolean; configured: boolean }

function EmailSettings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["mail-settings"], queryFn: () => api<MailSettings>("/admin/email") });
  const [draft, setDraft] = useState<Partial<MailSettings> & { password?: string }>({});
  const save = useMutation({
    mutationFn: () => api<MailSettings>("/admin/email", { ...json(draft), method: "PUT" }),
    onSuccess: (d) => {
      qc.setQueryData(["mail-settings"], d);
      setDraft({});
      void qc.invalidateQueries({ queryKey: ["auth-options"] });
    },
  });
  const test = useMutation({ mutationFn: () => api<{ sent_to: string }>("/admin/email/test", { method: "POST" }) });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message} />;
  const s = { ...q.data!, ...draft };
  const set = (k: string, v: unknown) => setDraft((d) => ({ ...d, [k]: v }));
  const field = (k: keyof MailSettings | "password", label: string, props: Record<string, unknown> = {}) => (
    <div className="fx-row fx-wrap" style={{ gap: 8 }}>
      <label className="fx-lab" htmlFor={`mail-${k}`} style={{ width: 200 }}>{label}</label>
      <div className="fx-field sm" style={{ flex: 1, minWidth: 220 }}>
        <input id={`mail-${k}`} value={k === "password" ? draft.password ?? "" : String((s as Record<string, unknown>)[k] ?? "")}
          onChange={(e) => set(k, k === "port" ? Number(e.target.value.replace(/\D/g, "")) : e.target.value)} {...props} />
      </div>
    </div>
  );
  return (
    <>
      <PageHeader title={t("pages.settings.nav.email")} desc={t("email.settings.hint")} />
      <div className={q.data!.configured ? "fx-note" : "fx-note"} role="status">
        <Pill tone={q.data!.configured ? "ok" : "warn"}>{q.data!.configured ? "✓" : "!"}</Pill> {q.data!.configured ? t("email.settings.on") : t("email.settings.off")}
      </div>
      <form className="fx-card fx-stack" style={{ padding: 14, gap: 10 }} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {field("host", t("email.settings.host"), { placeholder: "smtp.example.com", autoComplete: "off" })}
        {field("port", t("email.settings.port"), { inputMode: "numeric" })}
        <div className="fx-row fx-wrap" style={{ gap: 8 }}>
          <span className="fx-lab" style={{ width: 200 }}>{t("email.settings.security")}</span>
          <Seg label={t("email.settings.security")} value={s.security} onChange={(v) => set("security", v)}
            options={[{ value: "starttls", label: "STARTTLS" }, { value: "ssl", label: "SSL/TLS" }, { value: "none", label: "—" }]} />
        </div>
        {field("username", t("email.settings.username"), { autoComplete: "off" })}
        {field("password", `${t("email.settings.password")} (${q.data!.password_set ? t("email.settings.passwordSet") : t("email.settings.passwordNotSet")})`, { type: "password", autoComplete: "new-password" })}
        {field("from_address", t("email.settings.from"), { type: "email", placeholder: "fidelity@company.com" })}
        {field("from_name", t("email.settings.fromName"))}
        {field("site_url", t("email.settings.siteUrl"), { placeholder: t("email.settings.siteUrlHint") })}
        <div className="fx-row fx-wrap" style={{ gap: 8 }}>
          <label className="fx-lab" htmlFor="mail-approval" style={{ width: 200 }}>{t("email.settings.approval")}</label>
          <select id="mail-approval" className="fx-field sm" value={s.approval} onChange={(e) => set("approval", e.target.value)} style={{ flex: 1, minWidth: 220 }}>
            {(["domains", "all", "none"] as const).map((a) => <option key={a} value={a}>{t(`email.settings.ap.${a}`)}</option>)}
          </select>
        </div>
        {save.error && <div className="fx-errnote" role="alert">{(save.error as Error).message}</div>}
        {save.isSuccess && !Object.keys(draft).length && <div className="fx-note" role="status">{t("email.settings.saved")}</div>}
        <div className="fx-row" style={{ gap: 8 }}>
          <button className="fx-btn pri" type="submit" disabled={!Object.keys(draft).length || save.isPending}>{t("email.settings.save")}</button>
          <button className="fx-btn" type="button" disabled={!q.data!.configured || test.isPending} onClick={() => test.mutate()}>{t("email.settings.test")}</button>
        </div>
        {test.error && <div className="fx-errnote" role="alert">{(test.error as Error).message}</div>}
        {test.data && <div className="fx-note" role="status">{t("email.settings.tested", { email: test.data.sent_to || me?.email })}</div>}
      </form>
    </>
  );
}


function Account() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const change = useMutation({
    mutationFn: () => api("/account/password", json({ current: cur, new: next })),
    onSuccess: () => {
      setCur("");
      setNext("");
      setAgain("");
    },
  });
  const mismatch = again.length > 0 && next !== again;
  return (
    <>
      <PageHeader title={t("pages.settings.nav.account")} />
      <div className="fx-card" style={{ padding: 14 }}>
        <div className="fx-stack" style={{ gap: 6 }}>
          <div className="fx-row"><span className="fx-muted" style={{ width: 120 }}>{t("login.email")}</span><b>{me?.email}</b></div>
          <div className="fx-row"><span className="fx-muted" style={{ width: 120 }}>{t("pages.users.role")}</span><span>{me ? t(`roles.${me.role}`) : ""}</span></div>
        </div>
      </div>
      <form className="fx-card" style={{ padding: 14 }} onSubmit={(e) => { e.preventDefault(); if (!mismatch && next) change.mutate(); }}>
        <h3 className="fx-h3">{t("pages.settings.password")}</h3>
        <div className="fx-stack" style={{ gap: 10, maxWidth: 360 }}>
          {([["cur", t("pages.settings.pwCurrent"), cur, setCur, "current-password"], ["new", t("pages.settings.pwNew"), next, setNext, "new-password"], ["again", t("pages.settings.pwAgain"), again, setAgain, "new-password"]] as const).map(([id, label, v, set, ac]) => (
            <div key={id}>
              <label className="fx-lab" htmlFor={`pw-${id}`}>{label}</label>
              <div className="fx-field"><input id={`pw-${id}`} type="password" value={v} autoComplete={ac} onChange={(e) => set(e.target.value)} /></div>
            </div>
          ))}
          <div className="fx-tiny fx-muted">{t("pages.settings.pwRule")}</div>
          {mismatch && <div className="fx-errnote">{t("pages.settings.pwMismatch")}</div>}
          {change.error && <div className="fx-errnote" role="alert">{(change.error as Error).message}</div>}
          {change.isSuccess && <div className="fx-note" role="status">{t("pages.settings.pwChanged")}</div>}
          <div><button className="fx-btn pri" type="submit" disabled={!cur || next.length < 10 || mismatch || change.isPending}>{t("pages.settings.pwChange")}</button></div>
        </div>
      </form>
    </>
  );
}

function Appearance() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  return (
    <>
      <PageHeader title={t("pages.settings.nav.appearance")} />
      <div className="fx-card" style={{ padding: 14 }}>
        <div className="fx-stack" style={{ gap: 12 }}>
          <div className="fx-row fx-wrap"><b style={{ width: 120 }}>{t("shell.appearance")}</b>
            <Seg<Theme> label={t("shell.appearance")} value={theme} onChange={setTheme} options={(["system", "light", "dark"] as Theme[]).map((x) => ({ value: x, label: t(`shell.theme.${x}`) }))} />
          </div>
          <div className="fx-row fx-wrap"><b style={{ width: 120 }}>{t("header.language")}</b>
            <Seg label={t("header.language")} value={i18n.language.startsWith("zh") ? "zh" : "en"} onChange={(l) => void i18n.changeLanguage(l)} options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]} />
          </div>
        </div>
      </div>
    </>
  );
}

function Storage() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t("pages.settings.nav.storage")} desc={t("pages.settings.storageHint")} />
      <CloudStorage />
      <GoogleDrive />
    </>
  );
}

const BODY: Record<Section, () => ReactNode> = {
  storage: () => <Storage />,
  ai: () => <AiSettings />,
  defaults: () => <Defaults />,
  queue: () => <Queue />,
  corrections: () => <CorrectionsPage />,
  archive: () => <Archive />,
  users: () => <UsersPage />,
  notifications: () => <Notifications />,
  audit: () => <Audit />,
  system: () => <SystemHealth />,
  email: () => <EmailSettings />,
  account: () => <Account />,
  appearance: () => <Appearance />,
};

/** Settings: grouped sections on the left, one section on the right, each with its own address. Sections a person may
 * not change are not shown at all. */
export function SettingsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const nav = useNavigate();
  const { section } = useParams<{ section?: Section }>();
  const [q, setQ] = useState("");
  const admin = me?.role === "admin";
  const items = ITEMS.filter((i) => !i.admin || admin);
  const current = (section ?? "account") as Section;
  if (!items.some((i) => i.key === current)) return <Navigate to="/settings" replace />;
  const shown = items.filter((i) => !q || t(`pages.settings.nav.${i.key}`).toLowerCase().includes(q.toLowerCase()));
  const groups = (["connect", "distill", "team", "personal"] as const).filter((g) => shown.some((i) => i.group === g));
  const go = (k: string) => nav(k === "account" ? "/settings" : `/settings/${k}`);
  return (
    <div className="fx-setgrid">
      <nav className="fx-setnav" aria-label={t("pages.settings.nav.sections")}>
        <label className="fx-field sm" style={{ marginBottom: 6 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("pages.settings.search")} aria-label={t("pages.settings.search")} />
          <span className="fx-kbd">/</span>
        </label>
        {groups.map((g) => (
          <div key={g} style={{ display: "grid", gap: 2 }}>
            <div className="g">{t(`pages.settings.groups.${g}`)}</div>
            {shown.filter((i) => i.group === g).map((i) => (
              <Link key={i.key} to={i.key === "account" ? "/settings" : `/settings/${i.key}`} className={i.key === current ? "on" : undefined} aria-current={i.key === current ? "page" : undefined}>
                {t(`pages.settings.nav.${i.key}`)}
              </Link>
            ))}
          </div>
        ))}
        {!groups.length && <div className="fx-tiny fx-muted" style={{ padding: "6px 10px" }}>{t("shell.nothingFound")}</div>}
      </nav>
      <div className="fx-setbody">
        <label className="fx-setselect">
          <span className="sr-only">{t("pages.settings.nav.sections")}</span>
          <select value={current} onChange={(e) => go(e.target.value)} className="fx-field" style={{ width: "100%" }}>
            {items.map((i) => <option key={i.key} value={i.key}>{t(`pages.settings.nav.${i.key}`)}</option>)}
          </select>
        </label>
        {BODY[current]()}
      </div>
    </div>
  );
}
