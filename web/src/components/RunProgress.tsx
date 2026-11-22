import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

/** One file a run is working on now (see backend distill/pipeline.py). */
export interface ActiveFile {
  stage: "downloading" | "ready" | "reading" | "ocr" | "checking" | "uploading";
  since?: number;
  stage_since?: number;
  bytes?: number;
  size?: number;
  page?: number;
  pages?: number;
  scan?: boolean;
}
export interface RunLive {
  v?: number;
  stage?: string;
  started?: number;
  updated?: number;
  total?: number;
  done?: number;
  skipped?: number;
  workers?: number;
  active?: Record<string, ActiveFile>;
  queued?: string[];
  counts?: Record<string, number>;
  // older runs (one file at a time)
  file?: string;
  index?: number;
  page?: number;
  pages?: number;
}

const name = (rel: string) => rel.split("/").pop() || rel;
const mb = (b?: number) => ((b ?? 0) / 1e6).toFixed(b && b < 1e7 ? 1 : 0);

/** Steps of one file in a distill run. A scanned file reads with OCR, page by page. */
function stepsOf(a: ActiveFile): ("downloading" | "reading" | "checking" | "uploading")[] {
  return a.stage === "uploading" ? ["uploading"] : ["downloading", "reading", "checking"];
}
const stepIndex = (a: ActiveFile) => (a.stage === "ocr" ? 1 : ({ downloading: 0, ready: 1, reading: 1, checking: 2, uploading: 0 } as const)[a.stage] ?? 0);

/** How far one file is in its current step, 0..1, when we can tell. */
export function stepFraction(a: ActiveFile): number | null {
  if (a.stage === "downloading" && a.size) return Math.min(1, (a.bytes ?? 0) / a.size);
  if ((a.stage === "ocr" || a.stage === "reading") && a.pages) return Math.min(1, (a.page ?? 0) / a.pages);
  return null;
}

/** The step's own words: "3.1 / 9.4 MB", "page 12 of 40". */
export function stepDetail(a: ActiveFile, t: TFunction): string {
  if (a.stage === "downloading") return a.size ? t("run.bytes", { got: mb(a.bytes), size: mb(a.size) }) : "";
  if (a.stage === "ocr" && a.pages) return t("run.ocrPage", { page: a.page ?? 0, pages: a.pages });
  return "";
}

/** OCR goes page by page: how long a page takes here, and how long this file still needs. */
export function ocrPace(a: ActiveFile, now: number): { perPage: number; left: number } | null {
  if (a.stage !== "ocr" || !a.pages || !a.page || a.page < 2 || !a.stage_since) return null;
  const perPage = (now - a.stage_since) / (a.page - 1);           // pages finished so far: page - 1
  return { perPage, left: perPage * (a.pages - a.page + 1) };
}

export function stageLabel(a: ActiveFile, t: TFunction) {
  return a.stage === "ocr" || (a.stage === "reading" && a.scan) ? t("run.step.ocr") : t(`run.step.${a.stage}`);
}

/** Seconds since, as "0:42" or "12:05" — redrawn every second while a run is going. */
function useNow(on: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [on]);
  return now;
}
const clock = (s: number) => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`;
};

/** Files done, counting the part of each file in hand (download 10%, reading 80%, checking 10%). */
export function progressOf(l: RunLive): { done: number; of: number; pct: number } {
  const of = Math.max(0, (l.total ?? 0) - (l.skipped ?? 0));
  let part = 0;
  for (const a of Object.values(l.active ?? {})) {
    const f = stepFraction(a);
    part += a.stage === "downloading" ? 0.1 * (f ?? 0) : a.stage === "ready" ? 0.1 : a.stage === "checking" ? 0.9 : a.stage === "uploading" ? 0.5 : 0.1 + 0.8 * (f ?? 0.2);
  }
  const done = (l.done ?? 0) + part;
  return { done, of, pct: of ? Math.min(100, (100 * done) / of) : 0 };
}

/** "about 12 minutes", "about 2 hours" */
export function humanDuration(sec: number, t: TFunction) {
  if (sec < 90) return t("pages.distill.etaMin", { n: 1 });
  if (sec < 5400) return t("pages.distill.etaMin", { n: Math.round(sec / 60) });
  return t("pages.distill.etaHour", { n: Math.round(sec / 3600) });
}

export function etaOf(l: RunLive, now: number): number | null {
  const { done, of } = progressOf(l);
  if (!l.started || done < 0.5 || of <= done) return null;
  const per = (now - l.started) / done;
  return per * (of - done);
}

function Steps({ a }: { a: ActiveFile }) {
  const { t } = useTranslation();
  const steps = stepsOf(a);
  const cur = a.stage === "uploading" ? 0 : stepIndex(a);
  return (
    <ol className="fx-steps" aria-label={t("run.stepsOf")}>
      {steps.map((s, i) => {
        // downloaded and waiting for a free reader: the read step is next, not under way
        const st = i < cur ? "done" : i === cur ? (a.stage === "ready" ? "wait" : "now") : "next";
        const label = i === cur ? (a.stage === "ready" ? t("run.waitRead") : stageLabel(a, t)) : s === "reading" && a.scan ? t("run.step.ocr") : t(`run.step.${s}`);
        return (
          <li key={s} className={st} aria-current={st === "now" ? "step" : undefined}>
            <i aria-hidden>{st === "done" ? "✓" : i + 1}</i>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** The run of a room: what it is doing now, file by file, and how much is left. */
export function RunPanel({ live, onCancel, canCancel }: { live: RunLive; onCancel?: () => void; canCancel?: boolean }) {
  const { t } = useTranslation();
  const now = useNow(true);
  const active = Object.entries(live.active ?? {});
  const queued = live.queued ?? [];
  const { of, pct } = progressOf(live);      // the bar counts the part of each file in hand; "done" only finished ones
  const eta = etaOf(live, now);
  const listing = live.stage === "listing" || live.stage === "starting";
  const reading = active.filter(([, a]) => a.stage === "reading" || a.stage === "ocr" || a.stage === "checking").length;
  return (
    <section className="fx-run" aria-label={t("run.title")}>
      <div className="fx-row fx-wrap" style={{ rowGap: 4 }}>
        <span className="fx-live-dot" aria-hidden />
        <b>{listing ? t("run.listing") : live.stage === "publishing" ? t("run.publishing") : t("run.running")}</b>
        {!listing && of > 0 && <span className="fx-tiny">{t("run.doneOf", { done: live.done ?? 0, of })}</span>}
        {(live.skipped ?? 0) > 0 && <span className="fx-tiny fx-muted">{t("run.skipped", { count: live.skipped })}</span>}
        {reading > 1 && <span className="fx-tiny fx-muted">{t("run.workers", { n: reading })}</span>}
        {live.started ? <span className="fx-tiny fx-muted">{t("run.elapsed", { t: clock(now - live.started) })}</span> : null}
        {eta != null && <span className="fx-tiny fx-muted">{t("pages.distill.eta", { d: humanDuration(eta, t) })}</span>}
        <span className="fx-sp" />
        {canCancel && onCancel && <button className="fx-a" onClick={onCancel}>{t("pages.distill.cancelRun")}</button>}
      </div>
      <div className={`fx-bar fx-bar-run${listing ? " indet" : ""}`} role="progressbar" aria-label={t("run.title")}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={listing ? undefined : Math.round(pct)} style={{ width: "100%", height: 8, marginTop: 8 }}>
        <i style={{ width: listing ? "35%" : `${Math.max(2, pct)}%` }} />
      </div>
      {active.length > 0 && (
        <ul className="fx-active" aria-label={t("run.activeTitle", { count: active.length })}>
          {active.map(([rel, a]) => {
            const f = stepFraction(a);
            const pace = ocrPace(a, now);
            const d = [stepDetail(a, t), pace ? t("run.pace", { s: Math.round(pace.perPage), left: humanDuration(pace.left, t) }) : ""].filter(Boolean).join(" · ");
            return (
              <li key={rel}>
                <span className="fx-active-name" title={rel}>{name(rel)}</span>
                <Steps a={a} />
                <span className="fx-active-detail">
                  {d && <span className="fx-tiny fx-num">{d}</span>}
                  {f != null && (
                    <span className="fx-bar fx-bar-run" style={{ width: 90 }} role="progressbar" aria-label={stageLabel(a, t)}
                      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(f * 100)}>
                      <i style={{ width: `${Math.max(3, f * 100)}%` }} />
                    </span>
                  )}
                  {f == null && a.stage !== "ready" && <span className="fx-bar fx-bar-run indet" style={{ width: 90 }} aria-hidden><i /></span>}
                  {/* a file waiting for a free reader has not started: no clock, it would read as time spent on it */}
                  {a.stage !== "ready" && <span className="fx-tiny fx-muted fx-num" title={t("run.inStep")}>{clock(now - (a.stage_since ?? a.since ?? now))}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {queued.length > 0 && (
        <div className="fx-tiny fx-muted" style={{ marginTop: 6 }}>
          {t("run.queued", { count: queued.length })}
          {": "}
          {queued.slice(0, 3).map(name).join(" · ")}
          {queued.length > 3 ? ` · +${queued.length - 3}` : ""}
        </div>
      )}
    </section>
  );
}

/** A file's cell in the file list while a run works on it, or waits for it. */
export function StageCell({ a, queuedAt }: { a?: ActiveFile; queuedAt?: number }) {
  const { t } = useTranslation();
  if (a?.stage === "ready") return <span className="fx-pill p-idle">{stageLabel(a, t)}</span>;
  if (a) {
    const d = stepDetail(a, t);
    return (
      <span className="fx-pill p-run fx-pill-live">
        {stageLabel(a, t)}
        {d ? ` · ${d}` : ""}
      </span>
    );
  }
  if (queuedAt != null) return <span className="fx-pill p-idle">{t("run.queuedAt", { n: queuedAt + 1 })}</span>;
  return null;
}
