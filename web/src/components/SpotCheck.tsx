import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Drawer } from "antd";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Button, ErrorState, Loading, PageHeader, Pill } from "./ui";

export interface SpotItem {
  id: number; n: number; week: string; lib_path: string; page: number; text: string; document: string; source: string;
  verdict: "ok" | "wrong" | null; note: string | null; by_user: string | null;
}
interface Summary {
  weeks: { week: string; size: number; checked: number; wrong: number }[];
  checked: number; wrong: number; target: number; error_upper95: number | null; meets_target: boolean; clean_pages_needed: number;
}
interface SpotWeek { week: string; current: string; items: SpotItem[]; summary: Summary }

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const fileName = (p: string) => p.split("/").pop() ?? p;

/** Requirements v3 H-3: this week's 20 pages, each compared by a person with the same page of the original PDF. */
export function SpotCheck() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const can = me?.role === "admin" || me?.role === "reviewer";
  const [week, setWeek] = useState<string | undefined>();
  const [open, setOpen] = useState<SpotItem | null>(null);
  const q = useQuery({ queryKey: ["spot-check", week ?? ""], queryFn: () => api<SpotWeek>(`/spot-check${week ? `?week=${week}` : ""}`) });
  if (q.isLoading) return <><PageHeader title={t("pages.settings.nav.spot")} desc={t("spot.hint")} /><Loading /><div className="fx-tiny fx-muted">{t("spot.firstDraw")}</div></>;
  if (q.isError) return <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  const d = q.data!;
  const s = d.summary;
  const done = d.items.filter((i) => i.verdict).length;
  const weeks = Array.from(new Set([d.current, ...s.weeks.map((w) => w.week)]));
  return (
    <>
      <PageHeader title={t("pages.settings.nav.spot")} desc={t("spot.hint")}
        extra={weeks.length > 1 ? (
          <label className="fx-tiny">{t("spot.week")}{" "}
            <select className="fx-field sm" value={d.week} onChange={(e) => setWeek(e.target.value)}>
              {weeks.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
          </label>
        ) : undefined} />
      <div className="fx-note" role="status">
        {s.checked === 0 ? t("spot.none") : t("spot.result", {
          checked: s.checked, wrong: s.wrong, upper: pct(s.error_upper95 ?? 1), target: pct(s.target),
        })}{" "}
        {s.checked > 0 && (s.meets_target ? <Pill tone="ok">{t("spot.meets")}</Pill>
          : s.wrong === 0 ? <span className="fx-muted">{t("spot.needMore", { n: s.clean_pages_needed })}</span>
          : <Pill tone="bad">{t("spot.above")}</Pill>)}
      </div>
      <div className="fx-tiny fx-muted">{t("spot.progress", { week: d.week, done, n: d.items.length })}</div>
      <div className="fx-tbox">
      <table className="fx-t" aria-label={t("spot.table")}>
        <thead><tr><th>#</th><th>{t("spot.file")}</th><th>{t("spot.page")}</th><th>{t("spot.verdict")}</th></tr></thead>
        <tbody>
          {d.items.map((it) => (
            <tr key={it.id}>
              <td>{it.n}</td>
              <td><button type="button" className="fx-a" onClick={() => setOpen(it)} title={it.lib_path}>{fileName(it.lib_path)}</button></td>
              <td>p.{it.page}</td>
              <td>{it.verdict === "ok" ? <Pill tone="ok">{t("spot.ok")}</Pill> : it.verdict === "wrong" ? <Pill tone="bad" title={it.note ?? ""}>{t("spot.wrong")}</Pill> : <span className="fx-muted">{t("spot.todo")}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {open && <Compare item={open} can={can} onClose={() => setOpen(null)} onDone={(next) => setOpen(next ? d.items.find((i) => i.n === open.n + 1) ?? null : null)} week={week ?? ""} />}
    </>
  );
}

function Compare({ item, can, onClose, onDone, week }: { item: SpotItem; can: boolean; onClose: () => void; onDone: (next: boolean) => void; week: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [note, setNote] = useState(item.note ?? "");
  const [wrong, setWrong] = useState(item.verdict === "wrong");
  const save = useMutation({
    mutationFn: (verdict: "ok" | "wrong") => api<SpotItem>(`/spot-check/${item.id}`, json({ verdict, note })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["spot-check", week] }); onDone(true); },
  });
  return (
    <Drawer open onClose={onClose} size="large" styles={{ wrapper: { width: "min(1200px, 96vw)" } }} title={`${item.n}. ${fileName(item.lib_path)} · p.${item.page}`} destroyOnHidden>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
        <figure style={{ margin: 0 }}>
          <figcaption className="fx-tiny fx-muted">{t("spot.source", { file: item.source, page: item.page })}</figcaption>
          <img src={`/api/v1/spot-check/${item.id}/page.png`} alt={t("spot.sourceAlt", { page: item.page })} style={{ width: "100%", border: "1px solid var(--line)" }} />
        </figure>
        <div>
          <div className="fx-tiny fx-muted">{t("spot.library")}</div>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.5, margin: 0 }}>{item.text}</pre>
        </div>
      </div>
      {can && (
        <div className="fx-stack" style={{ gap: 8, marginTop: 12 }}>
          <div className="fx-tiny fx-muted">{t("spot.ask")}</div>
          {wrong && (
            <label className="fx-field">
              <span className="sr-only">{t("spot.note")}</span>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("spot.notePh")} rows={2} />
            </label>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <Button onClick={() => save.mutate("ok")} disabled={save.isPending}>{t("spot.markOk")}</Button>
            {!wrong ? <Button variant="danger" onClick={() => setWrong(true)}>{t("spot.markWrong")}</Button>
              : <Button variant="danger" disabled={!note.trim() || save.isPending} onClick={() => save.mutate("wrong")}>{t("spot.saveWrong")}</Button>}
          </div>
          {save.isError && <div className="fx-errnote">{(save.error as Error).message}</div>}
        </div>
      )}
    </Drawer>
  );
}
