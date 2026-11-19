import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, json } from "../net/client";
import { Button, Card, cx } from "./ui";

interface Params { source_link?: string; dest_link?: string; dry_run?: boolean; force?: boolean; only?: string; rollback?: string }
interface Run { id: string; status: string; progress: number; message: string; created_at: number; params: Params }
interface Doc { source: string; verdict: string }
interface Summary {
  exit_code: number;
  published_run?: string;
  report?: { documents?: Doc[]; unchanged?: string[]; duplicates?: unknown[]; unsupported?: unknown[]; triaged_out?: unknown[]; source_unchanged?: boolean };
}
interface LiveStatus {
  started: number; updated: number; total: number; index: number; file: string; stage: string;
  page: number; pages: number; scan: boolean; counts: Record<string, number>; skipped: number;
}
interface RunDetail extends Run { log: string[]; summary: Summary | null; live?: LiveStatus | null }

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [active]);
  return now;
}

function dur(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${r}s` : `${r}s`;
}

function Bar({ value, label }: { value: number; label: string }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded bg-muted" role="progressbar" aria-label={label}
      aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <div className="fx-stripes h-full rounded bg-primary transition-[width] duration-700" style={{ width: `${Math.max(2, value)}%` }} />
    </div>
  );
}

function LivePanel({ run, canEdit }: { run: RunDetail; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const live = run.live;
  const now = useNow(true);
  const stop = useMutation({
    mutationFn: () => api(`/dropbox/sync/${run.id}/cancel`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dropbox-runs"] }),
  });
  const started = run.created_at;   // one clock for the whole run, so the elapsed time never jumps back
  const quiet = live ? now - live.updated : 0;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" aria-hidden="true" />
        <span className="font-medium">{t(`pages.sources.dropbox.stage.${live?.stage ?? "starting"}`, { defaultValue: live?.stage ?? "" })}</span>
        {live && live.total > 0 && live.index > 0 && (
          <span className="text-fg-muted">{t("pages.sources.dropbox.fileOf", { index: live.index, total: live.total })}</span>
        )}
        <span className="ml-auto text-fg-muted">{t("pages.sources.dropbox.elapsed", { time: dur(now - started) })}</span>
      </div>
      {live?.file && <p className="truncate text-sm" title={live.file}>{live.file}</p>}
      <Bar value={run.progress} label={t("pages.sources.dropbox.progress")} />
      {live?.stage === "ocr" && live.pages > 0 && (
        <div className="grid gap-1">
          <span className="text-xs text-fg-muted">{t("pages.sources.dropbox.ocrPage", { page: live.page, pages: live.pages })}</span>
          <Bar value={(100 * live.page) / live.pages} label={t("pages.sources.dropbox.ocrProgress")} />
        </div>
      )}
      {live?.scan && <p className="text-xs text-warn">{t("pages.sources.dropbox.scanHint")}</p>}
      <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
        <span>{t("pages.sources.dropbox.lastActivity", { time: dur(quiet) })}</span>
        {live && (live.counts.PASS || live.counts.REVIEW || live.counts.FAIL || live.skipped) ? (
          <span>{t("pages.sources.dropbox.soFar", { pass: live.counts.PASS ?? 0, review: live.counts.REVIEW ?? 0, fail: live.counts.FAIL ?? 0, skipped: live.skipped })}</span>
        ) : null}
        {canEdit && (
          <Button variant="ghost" className="ml-auto" disabled={stop.isPending}
            onClick={() => window.confirm(t("pages.sources.dropbox.cancelConfirm")) && stop.mutate()}>
            {t("pages.sources.dropbox.cancel")}
          </Button>
        )}
      </div>
      {quiet > 120 && <p className="text-xs text-fg-muted">{t("pages.sources.dropbox.quiet")}</p>}
      {stop.isError && <p role="alert" className="text-xs text-danger">{(stop.error as Error).message}</p>}
    </div>
  );
}

const KEY = "fidelity.dropboxLinks";
const active = (s: string) => s === "queued" || s === "running";

function loadLinks(): { src: string; dest: string } {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "") as { src: string; dest: string };
  } catch {
    return { src: "", dest: "" };
  }
}

function Counts({ s }: { s: Summary }) {
  const { t } = useTranslation();
  const docs = s.report?.documents ?? [];
  const n = (v: string) => docs.filter((d) => d.verdict === v).length;
  const items: Array<[string, number | string, string?]> = [
    [t("pages.sources.dropbox.pass"), n("PASS") + n("METADATA"), "text-ok"],
    [t("pages.sources.dropbox.review"), n("REVIEW"), "text-warn"],
    [t("pages.sources.dropbox.fail"), n("FAIL"), "text-danger"],
    [t("pages.sources.dropbox.unchanged"), s.report?.unchanged?.length ?? 0],
    [t("pages.sources.dropbox.duplicates"), s.report?.duplicates?.length ?? 0],
    [t("pages.sources.dropbox.unsupported"), (s.report?.unsupported?.length ?? 0) + (s.report?.triaged_out?.length ?? 0)],
  ];
  return (
    <div>
      <dl className="grid grid-cols-3 gap-2 text-sm sm:grid-cols-6">
        {items.map(([k, v, c]) => (
          <div key={k} className="rounded-md bg-muted p-2">
            <dt className="text-xs text-fg-muted">{k}</dt>
            <dd className={cx("text-lg font-semibold", c)}>{v}</dd>
          </div>
        ))}
      </dl>
      {s.report && (
        <p className={cx("mt-2 text-sm", s.report.source_unchanged ? "text-ok" : "text-danger")}>
          {s.report.source_unchanged ? t("pages.sources.dropbox.sourceOk") : t("pages.sources.dropbox.sourceChanged")}
        </p>
      )}
    </div>
  );
}

function RunView({ id, isAdmin, canEdit }: { id: string; isAdmin: boolean; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["dropbox-run", id],
    queryFn: () => api<RunDetail>(`/dropbox/sync/${id}`),
    refetchInterval: (query) => (query.state.data && !active(query.state.data.status) ? false : 3000),
  });
  const undo = useMutation({
    mutationFn: (run: string) =>
      api<{ job: string }>("/dropbox/rollback", json({ source_link: q.data?.params.source_link, dest_link: q.data?.params.dest_link, run })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dropbox-runs"] }),
  });
  if (!q.data) return null;
  const r = q.data;
  return (
    <div className="mt-3 flex flex-col gap-3 border-t border-border pt-3">
      {active(r.status) && <LivePanel run={r} canEdit={canEdit} />}
      {r.summary && <Counts s={r.summary} />}
      {r.summary?.published_run && isAdmin && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>{t("pages.sources.dropbox.published", { run: r.summary.published_run })}</span>
          <Button
            variant="danger"
            disabled={undo.isPending}
            onClick={() => {
              if (window.confirm(t("pages.sources.dropbox.rollbackConfirm", { run: r.summary?.published_run }))) undo.mutate(r.summary!.published_run!);
            }}
          >
            {t("pages.sources.dropbox.rollback")}
          </Button>
          {undo.isError && <span className="text-danger">{(undo.error as Error).message}</span>}
          {undo.isSuccess && <span role="status">{t("pages.sources.dropbox.rollbackStarted")}</span>}
        </div>
      )}
      <details open={active(r.status)}>
        <summary className="cursor-pointer text-sm text-fg-muted">{t("pages.sources.dropbox.log")}</summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-2 text-xs" tabIndex={0}>
          {r.log.join("\n") || "…"}
        </pre>
      </details>
    </div>
  );
}

export function DropboxSync({ canEdit, isAdmin }: { canEdit: boolean; isAdmin: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const saved = loadLinks();
  const [src, setSrc] = useState(saved.src);
  const [dest, setDest] = useState(saved.dest);
  const [dry, setDry] = useState(true);
  const [force, setForce] = useState(false);
  const [only, setOnly] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const status = useQuery({
    queryKey: ["dropbox-status"],
    queryFn: () => api<{ reader: boolean; writer: boolean; google?: { reader: boolean; writer: boolean } }>("/dropbox/status"),
  });
  const runs = useQuery({
    queryKey: ["dropbox-runs"],
    queryFn: () => api<{ runs: Run[] }>("/dropbox/sync"),
    refetchInterval: (query) => ((query.state.data?.runs ?? []).some((r) => active(r.status)) ? 3000 : false),
  });
  const start = useMutation({
    mutationFn: () => api<{ job: string }>("/dropbox/sync", json({ source_link: src, dest_link: dest, dry_run: dry, force, only })),
    onSuccess: (r) => {
      setOpen(r.job);
      void qc.invalidateQueries({ queryKey: ["dropbox-runs"] });
    },
  });
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ src, dest }));
    } catch {
      /* storage may be unavailable */
    }
  }, [src, dest]);
  const isGoogle = (v: string) => /^(https:\/\/drive\.google\.com\/|gdrive:)/.test(v.trim());
  const has = (link: string, role: "reader" | "writer") =>
    isGoogle(link) ? !!status.data?.google?.[role] : !!status.data?.[role];
  const ready = has(src || "/", "reader") && has(dest || "/", "writer");
  const missing = [
    !has(src || "/", "reader") && (isGoogle(src) ? "Google Drive reader" : "Dropbox reader"),
    !has(dest || "/", "writer") && (isGoogle(dest) ? "Google Drive writer" : "Dropbox writer"),
  ].filter(Boolean).join(", ");
  const list = Array.isArray(runs.data?.runs) ? runs.data!.runs : [];
  const busy = list.some((r) => active(r.status));
  const runningId = list.find((r) => active(r.status))?.id;
  useEffect(() => {
    if (runningId) setOpen((o) => o ?? runningId);
  }, [runningId]);

  return (
    <Card className="mb-4 flex flex-col gap-3">
      <div>
        <h2 className="font-medium">{t("pages.sources.dropbox.title")}</h2>
        <p className="text-sm text-fg-muted">{t("pages.sources.dropbox.intro")}</p>
      </div>
      {status.data && typeof status.data.reader === "boolean" && !ready && (
        <p role="alert" className="rounded-md border border-warn p-2 text-sm">
          {t("pages.sources.dropbox.notAuthorised", { roles: missing })}
        </p>
      )}
      {canEdit && (
        <form
          className="grid gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <label className="grid gap-1 text-sm">
            {t("pages.sources.dropbox.source")}
            <input className="rounded-md border border-border bg-surface px-2 py-2" value={src} onChange={(e) => setSrc(e.target.value)}
              placeholder="/Folder · https://www.dropbox.com/… · https://drive.google.com/drive/folders/…" required />
          </label>
          <label className="grid gap-1 text-sm">
            {t("pages.sources.dropbox.dest")}
            <input className="rounded-md border border-border bg-surface px-2 py-2" value={dest} onChange={(e) => setDest(e.target.value)}
              placeholder="/Folder · https://www.dropbox.com/… · https://drive.google.com/drive/folders/…" required />
          </label>
          <label className="grid gap-1 text-sm">
            {t("pages.sources.dropbox.only")}
            <input className="rounded-md border border-border bg-surface px-2 py-2" value={only} onChange={(e) => setOnly(e.target.value)} />
          </label>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} />
              {t("pages.sources.dropbox.dryRun")}
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              {t("pages.sources.dropbox.force")}
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={start.isPending || busy || !ready}>
              {dry ? t("pages.sources.dropbox.startDry") : t("pages.sources.dropbox.startPublish")}
            </Button>
            {busy && <span className="text-sm text-fg-muted">{t("pages.sources.dropbox.busy")}</span>}
            {start.isError && <span role="alert" className="text-sm text-danger">{(start.error as Error).message}</span>}
          </div>
          <p className="text-xs text-fg-muted">{t("pages.sources.dropbox.safety")}</p>
        </form>
      )}
      {list.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-medium">{t("pages.sources.dropbox.recent")}</h3>
          <ul className="flex flex-col gap-2">
            {list.slice(0, 10).map((r) => (
              <li key={r.id} className="rounded-md border border-border p-2">
                <button type="button" className="flex w-full flex-wrap items-center gap-2 text-left text-sm"
                  aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <span className={cx("rounded px-2 py-0.5 text-xs font-medium",
                    r.status === "done" ? "bg-muted text-ok" : r.status === "error" ? "bg-muted text-danger" : "bg-muted text-fg")}>
                    {t(`pages.sources.dropbox.status.${r.status}`, { defaultValue: r.status })}
                  </span>
                  <span>{r.params?.rollback ? t("pages.sources.dropbox.kindRollback") : r.params?.dry_run ? t("pages.sources.dropbox.kindDry") : t("pages.sources.dropbox.kindPublish")}</span>
                  <span className="text-fg-muted">{new Date(r.created_at * 1000).toLocaleString()}</span>
                  {active(r.status) && (
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" aria-hidden="true" />
                  )}
                  {active(r.status) && (
                    <span className="h-2 w-24 overflow-hidden rounded bg-muted" role="progressbar" aria-valuenow={Math.round(r.progress)} aria-valuemin={0} aria-valuemax={100}
                      aria-label={t("pages.sources.dropbox.progress")}>
                      <span className="block h-full bg-primary" style={{ width: `${r.progress}%` }} />
                    </span>
                  )}
                  {r.status !== "done" && <span className="min-w-0 flex-1 truncate text-fg-muted">{r.message}</span>}
                </button>
                {open === r.id && <RunView id={r.id} isAdmin={isAdmin} canEdit={canEdit} />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
