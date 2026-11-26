import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { Dropdown, Modal } from "antd";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Bar, EmptyState, ErrorState, Loading, PageHeader, Pill, Seg } from "../components/ui";
import { RoomFiles, loadFiles } from "../components/RoomFiles";
import type { FileRow } from "../components/RoomFiles";
import { CompareDrawer } from "../components/CompareDrawer";
import { FixDrawer } from "../components/FixDrawer";
import { DropboxFolderPicker, isUnder } from "../components/DropboxFolderPicker";
import { GettingStarted } from "../components/GettingStarted";
import { LeaveGuard, useUnsaved } from "../components/LeaveGuard";
import { RunPanel, progressOf, type RunLive } from "../components/RunProgress";

interface Loc {
  kind: string;
  link: string;
}
interface Counts {
  total: number;
  pending: number;
  processing: number;
  ok: number;
  below: number;
  unprocessable: number;
  skipped: number;
  publishing: number;
  published: number;
  finished: number;
  rate: number;
}
type Live = RunLive;
interface Job {
  id: string;
  status: string;
  progress: number | null;
  message: string | null;
  position?: number;
  live?: Live;
}
export interface Room {
  id: string;
  name: string;
  source: Loc | null;
  dest: Loc | null;
  mode: "distill" | "upload";
  threshold: number;
  number_guard: boolean;
  priority: number;
  points: number;
  archived: boolean;
  archived_at?: number | null;
  archived_by?: string | null;
  updated_at: number;
  counts: Counts;
  job: Job | null;
  accuracy_avg?: number | null;
}
interface QueueView {
  capacity: number;
  used: number;
  running: { job: string; room: string; name: string; points: number }[];
  queued: { job: string; room: string; name: string; position: number; points: number; priority: number }[];
}
interface Preview {
  ok: number;
  below: number;
  published: number;
  publishing: number;
  has_dest: boolean;
  dest: string | null;
  flagged?: { files: number; places: number; examples: { rel: string; places: number }[] };
}
interface Impact {
  new: number;
  replaces: number;
}

const isActive = (r: Room) => r.job?.status === "queued" || r.job?.status === "running";
const loc = (l: Loc | null) => l?.link ?? "";
const prov = (l: Loc | null) => (l?.kind === "gdrive" ? "Drive" : "Dropbox");

/** A readable name for a location: "/as 3500" and "https://www.dropbox.com/home/AS%203500?..." both read as their folder. */
export function shortLoc(l: Loc | null): string {
  if (!l) return "";
  const v = l.link;
  try {
    if (/^https?:/.test(v)) {
      const u = new URL(v);
      if (u.hostname.includes("dropbox.com") && u.pathname.startsWith("/home")) return decodeURIComponent(u.pathname.slice(5)) || "/";
      if (u.hostname.includes("drive.google.com")) return "Drive";
      return decodeURIComponent(u.pathname.split("/").filter(Boolean).pop() ?? v);
    }
  } catch {
    /* not a URL: shown as it is */
  }
  return v;
}
const lastPart = (l: Loc | null) => shortLoc(l).split("/").filter(Boolean).pop() ?? shortLoc(l);

// ------------------------------------------------------------------ status of a room
function RoomPills({ room }: { room: Room }) {
  const { t } = useTranslation();
  const j = room.job;
  const c = room.counts;
  if (j?.status === "running") {
    const l = j.live;
    // a run that reports file by file shows its count beside this (RunBadge); one number, not two
    if (l?.v) return <Pill tone="run">{t("run.running")}</Pill>;
    return <Pill tone="run">{l?.total ? t("pages.distill.room.runningOf", { i: Math.max(0, (l.index ?? 1) - 1), n: l.total }) : t("pages.distill.room.running", { pct: Math.round(j.progress ?? 0) })}</Pill>;
  }
  if (j?.status === "queued") return <Pill tone="idle">{t("pages.distill.room.queued", { n: j.position ?? 1 })}</Pill>;
  if (j?.status === "interrupted") return <Pill tone="warn">{t("pages.distill.room.interrupted")}</Pill>;
  if (j?.status === "error") return <Pill tone="bad">{t("pages.distill.room.failed")}</Pill>;
  if (!room.source) return <Pill tone="idle">{t("pages.distill.room.notConfigured")}</Pill>;
  if (!c.total) return <Pill tone="idle">{t("pages.distill.room.notRun")}</Pill>;
  return (
    <>
      {c.pending || c.processing ? <Pill tone="idle">{t("pages.distill.room.partial")}</Pill> : <Pill tone="ok">{t("pages.distill.room.done")}</Pill>}
      {c.below > 0 && <Pill tone="warn">{t("pages.distill.room.review", { n: c.below })}</Pill>}
      {c.unprocessable > 0 && <Pill tone="bad">{t("pages.distill.room.cannot", { n: c.unprocessable })}</Pill>}
    </>
  );
}

// ------------------------------------------------------------------ the queue
function QueueCard({ q, canEdit, rooms }: { q: QueueView; canEdit: boolean; rooms: Room[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["queue"] });
    void qc.invalidateQueries({ queryKey: ["rooms"] });
  };
  const prio = useMutation({ mutationFn: (p: { room: string; priority: number }) => api(`/rooms/${p.room}`, { ...json({ priority: p.priority }), method: "PATCH" }), onSuccess: refresh });
  const front = useMutation({ mutationFn: (room: string) => api(`/rooms/${room}/front`, { method: "POST" }), onSuccess: refresh });
  const full = q.used >= q.capacity;
  const byRoom = Object.fromEntries(rooms.map((r) => [r.id, r]));
  return (
    <div className="fx-card tight">
      <div className="fx-row fx-wrap" style={{ gap: "8px 18px" }}>
        <b>{t("pages.distill.queue")}</b>
        <span className="fx-tiny">
          {t("pages.distill.capacityIs")} <b className="fx-num">{t("pages.distill.points", { count: q.capacity })}</b>
          {t("pages.distill.colon")}
          {t("pages.distill.runningN")} <b className="fx-num">{q.running.length}</b> · {t("pages.distill.waitingN")} <b className="fx-num">{q.queued.length}</b>
        </span>
        <span className="fx-row fx-tiny" aria-label={t("pages.distill.capacity", { used: q.used, cap: q.capacity })} role="img">
          {Array.from({ length: q.capacity }).map((_, i) => (
            <span key={i} style={{ width: 34, height: 8, borderRadius: 4, background: i < q.used ? "var(--accent)" : "var(--idle-soft)" }} />
          ))}
          <span className="fx-muted">{full ? t("pages.distill.full") : t("pages.distill.free", { n: q.capacity - q.used })}</span>
        </span>
        <span className="fx-sp" />
        <button className="fx-a" onClick={() => setOpen(true)}>{t("pages.distill.manageQueue")}</button>
      </div>
      <Modal open={open} onCancel={() => setOpen(false)} footer={null} title={t("pages.distill.queue")} width={420}>
        <div className="fx-stack" style={{ gap: 10 }}>
          {!q.running.length && !q.queued.length && <div className="fx-muted">{t("pages.distill.queueEmpty")}</div>}
          {q.running.map((r) => (
            <div key={r.job} className="fx-row" style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px" }}>
              <Pill tone="run">{t("pages.distill.runningPill")}</Pill>
              <b>{r.name}</b>
              <span className="fx-sp" />
              <span className="fx-muted fx-tiny">{t(r.points >= 2 ? "pages.distill.heavy" : "pages.distill.light", { n: r.points })}</span>
            </div>
          ))}
          {q.queued.map((r) => (
            <div key={r.job} className="fx-row" style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px" }}>
              <Pill tone="idle">{r.position}</Pill>
              <b style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</b>
              <span className="fx-sp" />
              <Seg tiny label={t("pages.distill.priorityOf", { name: r.name })} value={byRoom[r.room]?.priority ?? r.priority} disabled={!canEdit}
                onChange={(v) => prio.mutate({ room: r.room, priority: v })}
                options={[{ value: 0, label: t("pages.distill.prioLow") }, { value: 1, label: t("pages.distill.prioNormal") }, { value: 2, label: t("pages.distill.prioHigh") }]} />
              {canEdit && r.position > 1 && <button className="fx-btn sm" onClick={() => front.mutate(r.room)}>{t("pages.distill.front")}</button>}
            </div>
          ))}
          <div className="fx-note">{t("pages.distill.queueRules")}</div>
          <div className="fx-tiny fx-muted">{t("pages.distill.capacityAuto", { n: q.capacity })}</div>
        </div>
      </Modal>
    </div>
  );
}

// ------------------------------------------------------------------ editions (requirements v2, D-1 to D-5)
interface EditionsView { standards: number; current: number; superseded: number; amendments: number; extra_copies: number; published_twice: number; code?: string; code_note?: string; missing?: { designation: string; title: string; clauses: string[] }[] }

function EditionsLine({ room, canEdit, published }: { room: Room; canEdit: boolean; published: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const v = useQuery({ queryKey: ["room-editions", room.id], queryFn: () => api<EditionsView>(`/rooms/${room.id}/editions`) });
  const stamp = useMutation({
    mutationFn: () => api<{ job: string; count: number }>(`/rooms/${room.id}/restamp`, { method: "POST" }),
    onSuccess: () => {
      for (const k of ["rooms", "queue", "room-files", "accept-preview", "room-editions"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
  if (!v.data || !v.data.standards) return null;
  return (
    <div className="fx-row fx-wrap fx-tiny" style={{ gap: 10 }}>
      <b>{t("pages.distill.edition.title")}</b>
      <span className="fx-muted">{t("pages.distill.edition.summary", { standards: v.data.standards, current: v.data.current, superseded: v.data.superseded, amendments: v.data.amendments, copies: v.data.extra_copies })}</span>
      {v.data.published_twice > 0 && <span className="fx-pill warn" title={t("pages.distill.edition.twiceHint")}>{t("pages.distill.edition.twice", { count: v.data.published_twice })}</span>}
      {!!v.data.missing?.length && (
        <span className="fx-pill warn" title={[...v.data.missing.map((m) => `${m.designation} ${m.title}`), v.data.code_note ?? ""].filter(Boolean).join("\n")}>
          {t("pages.distill.edition.missing", { code: v.data.code, count: v.data.missing.length, list: v.data.missing.map((m) => m.designation).join(", ") })}
        </span>
      )}
      {canEdit && published > 0 && (
        <button className="fx-btn sm" title={t("pages.distill.edition.restampHint")} disabled={stamp.isPending || isActive(room)} onClick={() => stamp.mutate()}>
          {t("pages.distill.edition.restamp")}
        </button>
      )}
      {stamp.data && <span role="status">{t("pages.distill.edition.restampDone", { count: stamp.data.count })}</span>}
      {stamp.error && <span className="fx-errnote" role="alert">{(stamp.error as Error).message}</span>}
    </div>
  );
}

// ------------------------------------------------------------------ accept into the knowledge base (screen 1d)
function AcceptPanel({ room, canEdit, onReview }: { room: Room; canEdit: boolean; onReview: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [thr, setThr] = useState(String(room.threshold));
  const [confirm, setConfirm] = useState(false);
  const [checked, setChecked] = useState(false);          // v3 H-2: flagged places were looked at
  useEffect(() => setThr(String(room.threshold)), [room.threshold]);
  useEffect(() => {
    if (!confirm) setChecked(false);
  }, [confirm]);
  const files = useQuery({ queryKey: ["room-files", room.id, "", ""], queryFn: () => loadFiles(room.id, "", "") });
  const preview = useQuery({ queryKey: ["accept-preview", room.id], queryFn: () => api<Preview>(`/rooms/${room.id}/accept-preview`) });
  const impact = useQuery({ queryKey: ["accept-impact", room.id], queryFn: () => api<Impact>(`/rooms/${room.id}/accept-impact`), enabled: confirm, retry: false, staleTime: 30000 });
  const refresh = () => {
    for (const k of ["rooms", "room-files", "accept-preview", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
  };
  const save = useMutation({ mutationFn: (f: Record<string, unknown>) => api(`/rooms/${room.id}`, { ...json(f), method: "PATCH" }), onSuccess: refresh });
  const accept = useMutation({
    mutationFn: () => api(`/rooms/${room.id}/accept`, json({ all_ok: true, checked_flagged: checked })),
    onSuccess: () => {
      setConfirm(false);
      refresh();
    },
  });
  const rows: FileRow[] = files.data ?? [];
  const accs = rows.filter((f) => f.accuracy != null).map((f) => f.accuracy as number);
  const lo = Math.min(90, ...(accs.length ? accs.map((a) => Math.floor(a)) : [90]));
  const bins = 10;
  const step = (100 - lo) / bins;
  const hist = Array.from({ length: bins }, (_, i) => accs.filter((a) => (i === bins - 1 ? a >= lo + i * step : a >= lo + i * step && a < lo + (i + 1) * step)).length);
  const peak = Math.max(1, ...hist);
  const c = room.counts;
  const held = rows.filter((f) => f.state === "below" && f.accuracy != null && f.accuracy >= room.threshold).length;
  const okN = preview.data?.ok ?? c.ok;
  const thrPct = Math.min(100, Math.max(0, ((room.threshold - lo) / (100 - lo)) * 100));
  const commit = () => {
    const v = Number(thr);
    if (!thr.trim() || !Number.isFinite(v) || v < 50 || v > 100) {
      setThr(String(room.threshold));
      return;
    }
    if (v !== room.threshold) save.mutate({ threshold: v });
  };
  if (!c.total) return null;
  const err = (save.error || accept.error) as Error | null;
  return (
    <section className="fx-card" aria-label={t("pages.distill.acceptTitleShort")} style={{ padding: 16 }}>
      <div className="fx-stack" style={{ gap: 12 }}>
        <div className="fx-head">
          <div>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{t("pages.distill.acceptTitleShort")}</h2>
            <p>{t("pages.distill.acceptIntro")}</p>
          </div>
        </div>
        <div className="fx-row fx-wrap">
          <b>{t("pages.distill.thresholdShort")}</b>
          <label className="fx-field sm" style={{ width: 90 }}>
            <input className="fx-num" value={thr} inputMode="decimal" aria-label={t("pages.distill.threshold")} disabled={!canEdit}
              onChange={(e) => setThr(e.target.value.replace(/[^\d.]/g, ""))} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
            <span className="fx-muted">%</span>
          </label>
          <span className="fx-muted fx-tiny">{t("pages.distill.thresholdLive")}</span>
        </div>
        {accs.length > 0 && (
          <div>
            <div className="fx-lab">{t("pages.distill.histTitle", { n: accs.length })}</div>
            <div className="fx-hist" role="img" aria-label={t("pages.distill.histLabel", { thr: room.threshold })}>
              {hist.map((h, i) => (
                <i key={i} className={lo + (i + 1) * step <= room.threshold ? "lo" : undefined} style={{ height: `${(h / peak) * 100}%` }} title={`${(lo + i * step).toFixed(1)}–${(lo + (i + 1) * step).toFixed(1)}%: ${h}`} />
              ))}
              <span className="fx-thr" style={{ left: `${thrPct}%` }}><span>{room.threshold}%</span></span>
            </div>
            <div className="fx-row fx-tiny fx-muted" style={{ justifyContent: "space-between" }}>
              <span>{lo}%</span><span>{Math.round((lo + 100) / 2)}%</span><span>100%</span>
            </div>
          </div>
        )}
        <div className="fx-row fx-wrap" style={{ gap: 18 }}>
          <Pill tone="ok">{t("pages.distill.state.ok")} <b className="fx-num">{c.ok}</b></Pill>
          <Pill tone="warn">{t("pages.distill.state.below")} <b className="fx-num">{c.below}</b></Pill>
          <Pill tone="bad">{t("pages.distill.state.unprocessable")} <b className="fx-num">{c.unprocessable}</b></Pill>
          {c.skipped > 0 && <Pill tone="idle">{t("pages.distill.state.skipped")} <b className="fx-num">{c.skipped}</b></Pill>}
          <Pill tone="idle">{t("pages.distill.state.pending")} <b className="fx-num">{c.pending}</b></Pill>
          {c.published > 0 && <Pill tone="ok">{t("pages.distill.state.published")} <b className="fx-num">{c.published}</b></Pill>}
        </div>
        <EditionsLine room={room} canEdit={canEdit} published={c.published} />
        <label className="fx-row fx-tiny">
          <input type="checkbox" className="fx-cb" checked={room.number_guard} disabled={!canEdit} onChange={(e) => save.mutate({ number_guard: e.target.checked })} />
          <span>{t("pages.distill.numberGuardLong")}</span>
        </label>
        {canEdit && (
          <div className="fx-row fx-wrap">
            <button className="fx-btn pri big" disabled={!okN || isActive(room) || !preview.data?.has_dest} onClick={() => setConfirm(true)}>
              {t("pages.distill.accept", { count: okN })}
            </button>
            <button className="fx-btn big" onClick={onReview}>{t("pages.distill.reviewOneByOne")}</button>
            {!preview.data?.has_dest && <span className="fx-muted fx-tiny">{t("pages.distill.needOutput")}</span>}
          </div>
        )}
        <div className="fx-note" role="status" aria-live="polite">
          {t("pages.distill.thresholdNote", { thr: room.threshold })}
          {held > 0 ? ` ${t("pages.distill.heldForNumbers", { count: held })}` : ""}
        </div>
        {err && <div className="fx-errnote" role="alert">{err.message}</div>}
      </div>
      <Modal
        open={confirm}
        onCancel={() => setConfirm(false)}
        title={t("pages.distill.acceptTitle", { count: okN })}
        width={420}
        footer={[
          <button key="c" className="fx-btn" onClick={() => setConfirm(false)}>{t("pages.distill.cancel")}</button>,
          <button key="ok" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={accept.isPending || (!!preview.data?.flagged?.files && !checked)} onClick={() => accept.mutate()}>{t("pages.distill.acceptConfirm")}</button>,
        ]}
      >
        <div className="fx-stack" style={{ gap: 10 }}>
          <div className="fx-tiny fx-muted">{t("pages.distill.acceptBody2", { dest: preview.data?.dest ?? "" })}</div>
          <div className="fx-card" style={{ padding: 10 }}>
            <div className="fx-tiny">{t("pages.distill.compareLive")}</div>
            <div className="fx-row fx-tiny" style={{ marginTop: 4, gap: 14 }}>
              {impact.data ? (
                <>
                  <span>{t("pages.distill.newN")} <b className="fx-num">{impact.data.new}</b></span>
                  <span>{t("pages.distill.updateN")} <b className="fx-num">{impact.data.replaces}</b></span>
                </>
              ) : (
                <span className="fx-muted">{impact.isError ? t("pages.distill.impactUnknown") : t("pages.distill.impactLoading")}</span>
              )}
            </div>
            <span className="fx-tiny fx-muted">{t("pages.distill.compareHint")}</span>
          </div>
          {!!preview.data?.flagged?.files && (
            <div className="fx-errnote" role="alert" style={{ display: "grid", gap: 6 }}>
              <b>{t("pages.distill.flaggedTitle", { files: preview.data.flagged.files, places: preview.data.flagged.places })}</b>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {preview.data.flagged.examples.map((x) => (
                  <li key={x.rel} className="fx-tiny">{x.rel.split("/").pop()} — {t("pages.distill.flaggedPlaces", { count: x.places })}</li>
                ))}
              </ul>
              <label className="fx-row fx-tiny" style={{ gap: 6 }}>
                <input type="checkbox" className="fx-cb" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
                <span>{t("pages.distill.flaggedChecked")}</span>
              </label>
            </div>
          )}
          <div className="fx-tiny fx-muted">{t("pages.distill.rollbackHint")}</div>
        </div>
      </Modal>
    </section>
  );
}

// ------------------------------------------------------------------ one room
/** On the room's title line while it runs: a moving dot, files done of all, and a striped bar. */
function RunBadge({ live, fallback }: { live?: Live; fallback: number }) {
  const { t } = useTranslation();
  const p = live?.v ? progressOf(live) : null;
  const pct = p ? p.pct : fallback;
  return (
    <span className="fx-row" style={{ gap: 6 }}>
      <span className="fx-live-dot" aria-hidden />
      {p && p.of > 0 && <span className="fx-tiny fx-num">{t("run.doneOf", { done: live?.done ?? 0, of: p.of })}</span>}
      <span className="fx-bar fx-bar-run" style={{ width: 110 }} role="progressbar" aria-label={t("run.title")}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <i style={{ width: `${Math.max(3, pct)}%` }} />
      </span>
    </span>
  );
}

function Field({ id, label, loc: l, value, onChange, onPick, disabled, placeholder, invalid }: {
  id: string; label: string; loc: Loc | null; value: string; onChange: (v: string) => void; onPick: () => void; disabled: boolean; placeholder: string; invalid?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div style={{ minWidth: 0 }}>
      <label className="fx-lab" htmlFor={id}>{label}</label>
      <div className="fx-field" style={invalid ? { borderColor: "var(--bad)" } : undefined}>
        <span className="fx-src">{value.includes("drive.google.com") ? "Drive" : prov(l)}</span>
        <input id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} placeholder={placeholder} autoComplete="off" spellCheck={false} aria-invalid={invalid || undefined} />
        {!disabled && <button type="button" className="fx-iconbtn" aria-label={t("pages.distill.browseFor", { what: label })} onClick={onPick}>▾</button>}
      </div>
    </div>
  );
}

function RoomBody({ room, canEdit, focusFile, focusState }: { room: Room; canEdit: boolean; focusFile?: string | null; focusState?: string | null }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [source, setSource] = useState(loc(room.source));
  const [dest, setDest] = useState(loc(room.dest));
  const [picking, setPicking] = useState<"source" | "dest" | null>(null);
  const [comparing, setComparing] = useState<string | null>(null);
  const [fixing, setFixing] = useState<string | null>(focusFile ?? null);
  const [filter, setFilter] = useState<string>(focusState ?? "");
  useEffect(() => {
    setSource(loc(room.source));
    setDest(loc(room.dest));
  }, [room.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (focusState) setFilter(focusState); }, [focusState]);
  useEffect(() => { if (focusFile) setFixing(focusFile); }, [focusFile]);
  const active = isActive(room);
  const dirty = source !== loc(room.source) || dest !== loc(room.dest);
  const refresh = () => {
    for (const k of ["rooms", "queue", "room-files", "accept-preview", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
  };
  const save = useMutation({ mutationFn: (f: Record<string, unknown>) => api(`/rooms/${room.id}`, { ...json(f), method: "PATCH" }), onSuccess: refresh });
  const run = useMutation({ mutationFn: () => api(`/rooms/${room.id}/run`, json({})), onSuccess: refresh });
  // edited folders that are not saved yet: leaving the page asks first
  useUnsaved(`room-${room.id}`, canEdit && (source !== loc(room.source) || dest !== loc(room.dest))
    ? () => save.mutateAsync({ source, dest: dest || null }) : null);
  const cancel = useMutation({ mutationFn: () => api(`/rooms/${room.id}/cancel`, { method: "POST" }), onSuccess: refresh });
  const isPath = (v: string) => v.trim().startsWith("/");
  const overlap = isPath(source) && isPath(dest) && (isUnder(dest, source) || isUnder(source, dest));
  const err = (save.error || run.error || cancel.error) as Error | null;
  const j = room.job;
  const live = j?.status === "running" ? j.live : undefined;
  return (
    <div className="fx-room-b">
      <div className="fx-roomgrid">
        <Field id={`src-${room.id}`} label={t("pages.distill.inputRO")} loc={room.source} value={source} onChange={setSource} onPick={() => setPicking("source")} disabled={!canEdit || active} placeholder="/as 3500" />
        <div className="fx-muted fx-arrow" aria-hidden>→</div>
        <Field id={`dst-${room.id}`} label={t("pages.distill.outputPlace")} loc={room.dest} value={dest} onChange={setDest} onPick={() => setPicking("dest")} disabled={!canEdit || active} placeholder="/Library_Installation/Md_Library" invalid={overlap} />
        <div />
        <div>
          <span className="fx-lab">{t("pages.distill.afterDistill")}</span>
          <Seg label={t("pages.distill.afterDistill")} value={room.mode} disabled={!canEdit || active} onChange={(v) => save.mutate({ mode: v })}
            options={[{ value: "distill", label: t("pages.distill.modeDistill") }, { value: "upload", label: t("pages.distill.modeUpload") }]} />
        </div>
        {canEdit && (
          <div className="fx-row">
            {dirty ? (
              <button className="fx-btn pri" disabled={overlap || save.isPending} onClick={() => save.mutate({ source, dest: dest || null })}>{t("pages.distill.save")}</button>
            ) : active ? (
              <button className="fx-btn" disabled>{j?.status === "queued" ? t("pages.distill.waiting") : t("pages.distill.runningBtn")}</button>
            ) : (
              <button className="fx-btn pri" disabled={!room.source || run.isPending} onClick={() => run.mutate()}>
                {j?.status === "interrupted" ? t("pages.distill.resume") : j?.status === "error" ? t("pages.distill.retry") : room.counts.total ? t("pages.distill.runAgain") : t("pages.distill.start")}
              </button>
            )}
          </div>
        )}
      </div>
      {overlap && <div className="fx-errnote" role="alert">{t("pages.distill.overlap")}</div>}
      {err && <div className="fx-errnote" role="alert">{err.message}</div>}
      {j?.status === "interrupted" && <div className="fx-warnnote">{t("pages.distill.interruptedNote")}</div>}
      {j?.status === "error" && j.message && <div className="fx-errnote">{j.message}</div>}
      {live && <RunPanel live={live} canCancel={canEdit} onCancel={() => cancel.mutate()} />}
      {j?.status === "queued" && canEdit && (
        <div className="fx-row fx-muted fx-tiny">
          <span>{t("pages.distill.room.queued", { n: j.position ?? 1 })}</span>
          <button className="fx-a" onClick={() => cancel.mutate()}>{t("pages.distill.cancelQueue")}</button>
        </div>
      )}
      <RoomFiles roomId={room.id} live={active || room.counts.publishing > 0} counts={room.counts} filter={filter} onFilter={setFilter}
        progress={live}
        focusFile={focusFile} onCompare={room.dest ? setComparing : undefined} onFix={setFixing} canEdit={canEdit}
        onRetry={canEdit && !active ? () => run.mutate() : undefined} />
      <AcceptPanel room={room} canEdit={canEdit} onReview={() => setFilter("ok")} />
      <CompareDrawer roomId={room.id} rel={comparing} onClose={() => setComparing(null)} />
      <FixDrawer roomId={room.id} rel={fixing} canEdit={canEdit} threshold={room.threshold} onClose={() => setFixing(null)} />
      <DropboxFolderPicker
        open={picking !== null}
        title={t(picking === "dest" ? "pages.distill.chooseOutput" : "pages.distill.chooseInput")}
        value={picking === "dest" ? dest : source}
        allowLink={picking === "source"}
        allowNew={picking === "dest"}
        warn={(p) => {
          const other = picking === "dest" ? source : dest;
          return isPath(other) && (isUnder(p, other) || isUnder(other, p)) ? t("pages.distill.overlap") : null;
        }}
        onPick={(p) => {
          if (picking === "dest") setDest(p);
          else setSource(p);
          setPicking(null);
        }}
        onClose={() => setPicking(null)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ a new room, not saved yet
interface Draft { name: string; source: string; dest: string; mode: "distill" | "upload" }
const DRAFT_KEY = "fidelity.draftRoom";
function readDraft(): Draft | null {
  try {
    const v = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
    return v && typeof v === "object" ? { name: "", source: "", dest: "", mode: "distill", ...v } : null;
  } catch {
    return null;
  }
}
function keepDraft(d: Draft | null) {
  try {
    if (d) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(d));
    else sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    /* private window: the draft just is not kept over a reload */
  }
}

/** A room that exists only on this page until Save: nothing is made on the server before that, so a reload or a
 * closed tab never leaves a half-made "not set up" room behind. */
/** A room reads from Dropbox or Google Drive: say so before the room is filled in, not after (in a slow
 *  folder dialog), and tell each person what they can do about it. */
function NoCloudNotice() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["cloud-ready"], queryFn: () => api<{ dropbox: boolean; google: boolean }>("/cloud/ready"), staleTime: 60_000 });
  if (!q.data || q.data.dropbox || q.data.google) return null;
  return (
    <div className="fx-note warn" role="alert">
      {t("pages.distill.noCloud")}{" "}
      {me?.role === "admin" ? <Link to="/settings/storage">{t("pages.distill.noCloudAdmin")}</Link> : t("pages.distill.noCloudAsk")}
    </div>
  );
}

function DraftRoom({ initial, restored, onSaved, onDiscard }: {
  initial: Draft; restored: boolean; onSaved: (r: Room) => void; onDiscard: () => void;
}) {
  const { t } = useTranslation();
  const [d, setD] = useState<Draft>(initial);
  const [picking, setPicking] = useState<"source" | "dest" | null>(null);
  const isPath = (v: string) => v.trim().startsWith("/");
  const overlap = isPath(d.source) && isPath(d.dest) && (isUnder(d.dest, d.source) || isUnder(d.source, d.dest));
  const touched = !!(d.name.trim() || d.source.trim() || d.dest.trim());
  const create = useMutation({
    mutationFn: () => api<Room>("/rooms", json({ name: d.name.trim() || undefined, prefix: t("pages.distill.defaultName"),
      source: d.source.trim(), dest: d.dest.trim() || undefined, mode: d.mode })),
    onSuccess: (r) => {
      keepDraft(null);
      onSaved(r);
    },
  });
  const canSave = !!d.source.trim() && !overlap && !create.isPending;
  useEffect(() => keepDraft(touched ? d : null), [d, touched]);
  // leaving with something typed asks first; Save there needs the input folder like the button here
  useUnsaved("draft-room", touched ? () => {
    if (!d.source.trim()) return Promise.reject(new Error(t("pages.distill.draftNeedsInput")));
    if (overlap) return Promise.reject(new Error(t("pages.distill.overlap")));
    return create.mutateAsync();
  } : null);
  return (
    <section className="fx-room open fx-draft" aria-label={t("pages.distill.draftTitle")}>
      <div className="fx-room-h">
        <div className="fx-row fx-wrap" style={{ rowGap: 6 }}>
          <input autoFocus className="fx-field sm" style={{ width: 240 }} value={d.name} maxLength={80}
            placeholder={t("pages.distill.draftNamePh")} aria-label={t("pages.distill.roomName")}
            onChange={(e) => setD({ ...d, name: e.target.value })} />
          <Pill tone="warn">{t("pages.distill.draftPill")}</Pill>
          <span className="fx-sp" />
          <span className="fx-muted fx-tiny">{t("pages.distill.draftHint")}</span>
        </div>
      </div>
      <div className="fx-room-b">
        {restored && <div className="fx-note" role="status">{t("pages.distill.draftRestored")}</div>}
        <NoCloudNotice />
        <div className="fx-roomgrid">
          <Field id="src-draft" label={t("pages.distill.inputRO")} loc={null} value={d.source} onChange={(v) => setD({ ...d, source: v })}
            onPick={() => setPicking("source")} disabled={false} placeholder={t("pages.distill.eg", { p: "/as 3500" })} />
          <div className="fx-muted fx-arrow" aria-hidden>→</div>
          <Field id="dst-draft" label={t("pages.distill.outputPlace")} loc={null} value={d.dest} onChange={(v) => setD({ ...d, dest: v })}
            onPick={() => setPicking("dest")} disabled={false} placeholder={t("pages.distill.egOut", { p: "/Library_Installation/Md_Library" })} invalid={overlap} />
          <div />
          <div>
            <span className="fx-lab">{t("pages.distill.afterDistill")}</span>
            <Seg label={t("pages.distill.afterDistill")} value={d.mode} onChange={(v) => setD({ ...d, mode: v })}
              options={[{ value: "distill", label: t("pages.distill.modeDistill") }, { value: "upload", label: t("pages.distill.modeUpload") }]} />
          </div>
          <div className="fx-row">
            <button className="fx-btn" onClick={() => { keepDraft(null); onDiscard(); }}>{t("pages.distill.discard")}</button>
            <button className="fx-btn pri" disabled={!canSave} onClick={() => create.mutate()}>{create.isPending ? t("leave.saving") : t("pages.distill.saveRoom")}</button>
          </div>
        </div>
        {!d.source.trim() && <div className="fx-tiny fx-muted">{t("pages.distill.draftNeedsInput")}</div>}
        {overlap && <div className="fx-errnote" role="alert">{t("pages.distill.overlap")}</div>}
        {create.error && <div className="fx-errnote" role="alert">{(create.error as Error).message}</div>}
      </div>
      <DropboxFolderPicker
        open={picking !== null}
        title={t(picking === "dest" ? "pages.distill.chooseOutput" : "pages.distill.chooseInput")}
        value={picking === "dest" ? d.dest : d.source}
        allowLink={picking === "source"}
        allowNew={picking === "dest"}
        warn={(p) => {
          const other = picking === "dest" ? d.source : d.dest;
          return isPath(other) && (isUnder(p, other) || isUnder(other, p)) ? t("pages.distill.overlap") : null;
        }}
        onPick={(p) => {
          setD(picking === "dest" ? { ...d, dest: p } : { ...d, source: p });
          setPicking(null);
        }}
        onClose={() => setPicking(null)}
      />
    </section>
  );
}

function RoomCard({ room, open, onToggle, canEdit, focusFile, focusState }: {
  room: Room; open: boolean; onToggle: () => void; canEdit: boolean; focusFile?: string | null; focusState?: string | null;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(room.name);
  const [note, setNote] = useState<string | null>(null);
  const [askDelete, setAskDelete] = useState(false);
  useEffect(() => setName(room.name), [room.name]);
  const refresh = () => {
    for (const k of ["rooms", "queue", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
  };
  const rename = useMutation({ mutationFn: (n: string) => api(`/rooms/${room.id}`, { ...json({ name: n }), method: "PATCH" }), onSuccess: () => { setEditing(false); refresh(); }, onError: (e: Error) => setNote(e.message) });
  const archive = useMutation({ mutationFn: () => api(`/rooms/${room.id}/${room.archived ? "unarchive" : "archive"}`, { method: "POST" }), onSuccess: () => { setNote(null); refresh(); }, onError: (e: Error) => setNote(e.message) });
  const remove = useMutation({ mutationFn: () => api(`/rooms/${room.id}`, { method: "DELETE" }), onSuccess: () => { setAskDelete(false); refresh(); }, onError: (e: Error) => { setAskDelete(false); setNote(e.message); } });
  const run = useMutation({ mutationFn: () => api(`/rooms/${room.id}/run`, json({})), onSuccess: refresh, onError: (e: Error) => setNote(e.message) });
  const front = useMutation({ mutationFn: () => api(`/rooms/${room.id}/front`, { method: "POST" }), onSuccess: refresh, onError: (e: Error) => setNote(e.message) });
  const cancel = useMutation({ mutationFn: () => api(`/rooms/${room.id}/cancel`, { method: "POST" }), onSuccess: refresh, onError: (e: Error) => setNote(e.message) });
  const c = room.counts;
  const j = room.job;
  const empty = !room.source && !c.total;
  const weight = t(room.points >= 2 ? "pages.distill.heavy" : "pages.distill.light", { n: room.points || 1 });
  const menu = [
    ...(canEdit ? [{ key: "rename", label: t("pages.distill.rename"), onClick: () => setEditing(true) }] : []),
    ...(canEdit && isActive(room) ? [{ key: "cancel", label: j?.status === "queued" ? t("pages.distill.cancelQueue") : t("pages.distill.cancelRun"), onClick: () => cancel.mutate() }] : []),
    { key: "jobs", label: <Link to={`/jobs?room=${room.id}`}>{t("pages.distill.runHistory")}</Link> },
    ...(canEdit ? [{ key: "archive", label: room.archived ? t("pages.distill.unarchive") : t("pages.distill.archive"), onClick: () => archive.mutate() }] : []),
    ...(canEdit && !room.archived ? [{ key: "delete", danger: true, label: t("pages.distill.delete"), onClick: () => setAskDelete(true) }] : []),
  ];
  let action = null;
  if (!open && canEdit && room.source && !room.archived) {
    if (j?.status === "queued") action = <button className="fx-btn" onClick={() => front.mutate()}>{t("pages.distill.prioritize")}</button>;
    else if (j?.status === "interrupted") action = <button className="fx-btn" onClick={() => run.mutate()}>{t("pages.distill.resume")}</button>;
    else if (!isActive(room)) action = <button className="fx-btn" onClick={() => run.mutate()}>{t("pages.distill.runNow")}</button>;
  }
  return (
    <div className={`fx-room${open ? " open" : ""}${empty && !open ? " empty" : ""}`} id={`room-${room.id}`}>
      <div className="fx-room-h">
        <div className="fx-row fx-wrap" style={{ rowGap: 6 }}>
          <button className="fx-caret" aria-expanded={open} aria-label={t(open ? "pages.distill.collapseRoom" : "pages.distill.expandRoom", { name: room.name })} onClick={onToggle}>
            {open ? "▾" : "▸"}
          </button>
          {editing ? (
            <input autoFocus className="fx-field sm" style={{ width: 220 }} value={name} maxLength={80} aria-label={t("pages.distill.rename")}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) rename.mutate(name); if (e.key === "Escape") { setName(room.name); setEditing(false); } }}
              onBlur={() => (name.trim() && name !== room.name ? rename.mutate(name) : setEditing(false))} />
          ) : (
            <b style={{ fontSize: 14, cursor: canEdit ? "text" : undefined }} onDoubleClick={() => canEdit && setEditing(true)}>{room.name}</b>
          )}
          {canEdit && !editing && <button className="fx-iconbtn" aria-label={t("pages.distill.rename")} onClick={() => setEditing(true)}>✎</button>}
          {open && room.source && <span className="fx-src">{lastPart(room.source)}</span>}
          <RoomPills room={room} />
          {j?.status === "running" && <RunBadge live={j.live} fallback={j.progress ?? 0} />}
          {open && room.source && <span className="fx-muted fx-tiny">{weight}</span>}
          <span className="fx-sp" />
          {!open && empty && (
            // a room with no input and no files (made by an older version, which created a room at once on
            // "+ New room"): set it up, or delete it here without opening it
            <>
              <span className="fx-muted fx-tiny">{t("pages.distill.emptyRoomHint")}</span>
              {canEdit && <button className="fx-btn sm pri" onClick={onToggle}>{t("pages.distill.setUp")}</button>}
              {canEdit && !room.archived && <button className="fx-btn sm" onClick={() => setAskDelete(true)}>{t("pages.distill.delete")}</button>}
            </>
          )}
          {!open && !empty && (
            <>
              <span className="fx-tiny"><span className="fx-muted">{t("pages.distill.files")}</span> <b className="fx-num">{c.total}</b></span>
              <span className="fx-tiny"><span className="fx-muted">{t("pages.distill.finished")}</span> <b className="fx-num">{c.finished}</b></span>
              <span className="fx-tiny"><span className="fx-muted">{t("pages.distill.rate")}</span> <b className="fx-num">{Math.round(c.rate)}%</b></span>
              <Bar pct={c.rate} width={90} label={t("pages.distill.rate")} />
              {action}
            </>
          )}
          <Dropdown trigger={["click"]} menu={{ items: menu }}>
            <button className="fx-iconbtn" aria-label={t("pages.distill.more")} style={{ fontSize: 16 }}>⋯</button>
          </Dropdown>
        </div>
        {!open && !empty && (
          <div className="fx-muted fx-tiny" style={{ paddingLeft: 24 }}>
            {room.source ? `${prov(room.source)} ${shortLoc(room.source)}` : t("pages.distill.noInput")} → {room.dest ? `${prov(room.dest)} ${shortLoc(room.dest)}` : t("pages.distill.keepLocal")}
            {room.source ? ` · ${weight}` : ""}
          </div>
        )}
      </div>
      {note && <div className="fx-warnnote" role="alert" style={{ margin: open ? "10px 20px 0" : "0 14px 10px" }}>{note} <button className="fx-a" onClick={() => setNote(null)}>{t("pages.distill.dismiss")}</button></div>}
      {open && <RoomBody room={room} canEdit={canEdit} focusFile={focusFile} focusState={focusState} />}
      <Modal open={askDelete} onCancel={() => setAskDelete(false)} title={t("pages.distill.deleteTitle", { name: room.name })} width={420}
        footer={[
          <button key="c" className="fx-btn" onClick={() => setAskDelete(false)}>{t("pages.distill.cancel")}</button>,
          <button key="d" className="fx-btn danger" style={{ marginLeft: 8 }} disabled={remove.isPending} onClick={() => remove.mutate()}>{t("pages.distill.delete")}</button>,
        ]}>
        <div className="fx-tiny">{t("pages.distill.deleteBody")}</div>
      </Modal>
    </div>
  );
}

// ------------------------------------------------------------------ archived rooms (screen 1c)
function Archived({ rooms, canEdit }: { rooms: Room[]; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const unarchive = useMutation({
    mutationFn: (id: string) => api(`/rooms/${id}/unarchive`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["rooms"] }),
  });
  const list = rooms.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()));
  const opened = rooms.find((r) => r.id === openId);
  return (
    <div className="fx-stack">
      <div className="fx-row">
        <span className="fx-sp" />
        <label className="fx-field sm" style={{ minWidth: 220 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("pages.distill.searchNames")} aria-label={t("pages.distill.searchNames")} />
        </label>
      </div>
      {!list.length ? (
        <EmptyState title={t("pages.distill.emptyArchived")} />
      ) : (
        <div className="fx-tbox">
          <table className="fx-t">
            <thead><tr><th>{t("pages.distill.colRoom")}</th><th>{t("pages.distill.colContent")}</th><th>{t("pages.distill.colAccuracyShort")}</th><th>{t("pages.distill.colPublished")}</th><th>{t("pages.distill.colArchived")}</th><th><span className="sr-only">{t("pages.distill.colActions")}</span></th></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id} className={openId === r.id ? "sel" : undefined}>
                  <td><b>{r.name}</b></td>
                  <td className="fx-num">{t("pages.distill.fileCount", { count: r.counts.total })}</td>
                  <td className="fx-num"><b>{r.accuracy_avg != null ? `${r.accuracy_avg}%` : "—"}</b></td>
                  <td className="fx-muted">{r.dest ? `${prov(r.dest)} ${shortLoc(r.dest)}` : t("pages.distill.keepLocal")}</td>
                  <td className="fx-muted fx-tiny">{r.archived_at ? new Date(r.archived_at * 1000).toLocaleDateString() : ""}{r.archived_by ? ` · ${r.archived_by}` : ""}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="fx-a" onClick={() => setOpenId(openId === r.id ? null : r.id)}>{openId === r.id ? t("pages.distill.hide") : t("pages.distill.view")}</button>
                    {canEdit && <> · <button className="fx-a" onClick={() => unarchive.mutate(r.id)}>{t("pages.distill.unarchiveRerun")}</button></>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {opened && <RoomCard room={opened} open onToggle={() => setOpenId(null)} canEdit={false} />}
      {unarchive.error && <div className="fx-errnote">{(unarchive.error as Error).message}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ the page
export function DistillPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const canEdit = me?.role === "reviewer" || me?.role === "admin";
  const [tab, setTab] = useState<"active" | "archived">("active");
  const [open, setOpen] = useState<Set<string> | null>(null);
  const focusRoom = params.get("room");
  const focusFile = params.get("file");
  const focusState = params.get("state");
  const active = useQuery({
    queryKey: ["rooms", "active"],
    queryFn: () => api<{ rooms: Room[] }>("/rooms?archived=false"),
    refetchInterval: (q) => (q.state.data?.rooms.some(isActive) ? 3000 : 15000),
  });
  const archived = useQuery({ queryKey: ["rooms", "archived"], queryFn: () => api<{ rooms: Room[] }>("/rooms?archived=true") });
  const queue = useQuery({ queryKey: ["queue"], queryFn: () => api<QueueView>("/queue"), refetchInterval: 5000 });
  // a new room is a draft on this page until Save (kept in this tab, so a reload brings it back)
  const [draft, setDraft] = useState<{ d: Draft; restored: boolean } | null>(() => {
    const d = readDraft();
    return d ? { d, restored: true } : null;
  });
  const newDraft = () => {
    setTab("active");
    if (!draft) setDraft({ d: { name: "", source: "", dest: "", mode: "distill" }, restored: false });
    setTimeout(() => document.querySelector<HTMLInputElement>(".fx-draft input")?.focus(), 50);
  };
  const onSaved = (r: Room) => {
    setDraft(null);
    setOpen((p) => new Set([...(p ?? []), r.id]));
    void qc.invalidateQueries({ queryKey: ["rooms"] });
    void qc.invalidateQueries({ queryKey: ["queue"] });
  };
  const list = useMemo(() => active.data?.rooms ?? [], [active.data]);
  // a link to a room (a notification, the search) opens it and brings it into view
  useEffect(() => {
    if (!focusRoom || !list.length) return;
    if (!list.some((r) => r.id === focusRoom) && archived.data?.rooms.some((r) => r.id === focusRoom)) setTab("archived");
    setOpen((p) => new Set([...(p ?? (list[0] ? [list[0].id] : [])), focusRoom]));
    setTimeout(() => document.getElementById(`room-${focusRoom}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 200);
  }, [focusRoom, list.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (params.get("new") === "1" && canEdit) {
      newDraft();
      params.delete("new");
      setParams(params, { replace: true });
    }
  }, [params.get("new")]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = open ?? new Set(list[0] ? [list[0].id] : []);
  const toggle = (id: string) =>
    setOpen(() => {
      const n = new Set(shown);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const q = queue.data;
  const archivedRooms = archived.data?.rooms ?? [];
  return (
    <LeaveGuard>
    <div className="fx-stack">
      <PageHeader
        title={t("pages.distill.title")}
        desc={t("pages.distill.intro2")}
        extra={canEdit && tab === "active" && (
          <button className="fx-btn pri" onClick={newDraft}>+ {t("pages.distill.newRoom")}</button>
        )}
      />
      {q && <QueueCard q={q} canEdit={canEdit} rooms={list} />}
      <div className="fx-row">
        <div className="fx-chips" role="tablist" aria-label={t("pages.distill.title")}>
          <button role="tab" aria-selected={tab === "active"} className={`fx-chip${tab === "active" ? " on" : ""}`} onClick={() => setTab("active")}>
            {t("pages.distill.tabActive")} {list.length}
          </button>
          <button role="tab" aria-selected={tab === "archived"} className={`fx-chip${tab === "archived" ? " on" : ""}`} onClick={() => setTab("archived")}>
            {t("pages.distill.tabArchived")} {archivedRooms.length}
          </button>
        </div>
      </div>
      {tab === "active" && (
        <>
          {active.isLoading && <Loading />}
          {active.isError && <ErrorState message={(active.error as Error).message} onRetry={() => void active.refetch()} />}
          {!active.isLoading && !active.isError && list.length === 0 && !draft && (
            <>
              <GettingStarted rooms={list} />
              <EmptyState title={t("pages.distill.emptyTitle")} hint={t("pages.distill.emptyHint")} />
            </>
          )}
          <div className="fx-stack" style={{ gap: 10 }}>
            {draft && canEdit && <DraftRoom initial={draft.d} restored={draft.restored} onSaved={onSaved} onDiscard={() => setDraft(null)} />}
            {list.map((r) => (
              <RoomCard key={r.id} room={r} open={shown.has(r.id)} onToggle={() => toggle(r.id)} canEdit={canEdit}
                focusFile={r.id === focusRoom ? focusFile : null} focusState={r.id === focusRoom ? focusState : null} />
            ))}
          </div>
        </>
      )}
      {tab === "archived" && <Archived rooms={archivedRooms} canEdit={canEdit} />}
      <div className="fx-tiny fx-muted">
        <Link to="/jobs">{t("pages.distill.runHistoryAll")}</Link>
      </div>
    </div>
    </LeaveGuard>
  );
}
