import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Bar } from "./ui";
import type { Room } from "../pages/DistillPage";

const HIDE_KEY = "fidelity.gettingStarted.hidden";

function hidden(): boolean {
  try {
    return localStorage.getItem(HIDE_KEY) === "1";
  } catch {
    return false;
  }
}

/** First use in four steps (requirements v2, U-2). Each step ticks itself off from what is really there — storage
 * connected, a room with both folders, a finished run, an accepted file — and has the button that does it. It stays
 * until everything is done or the person hides it. */
export function GettingStarted({ rooms }: { rooms: Room[] }) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const [off, setOff] = useState(hidden);
  const cloud = useQuery({ queryKey: ["cloud-ready"], queryFn: () => api<{ dropbox: boolean; google: boolean }>("/cloud/ready"), staleTime: 60_000 });
  const admin = me?.role === "admin";
  const canEdit = admin || me?.role === "reviewer";
  const set = rooms.find((r) => r.source && r.dest);
  const ran = rooms.find((r) => r.counts.finished > 0);
  const steps = [
    { key: "storage", done: !!(cloud.data?.dropbox || cloud.data?.google),
      to: admin ? "/settings/storage" : undefined, note: admin ? undefined : t("start.askAdmin") },
    { key: "room", done: !!set, to: canEdit ? "/distill?new=1" : undefined },
    { key: "run", done: !!ran, to: set ? `/distill?room=${set.id}` : undefined },
    { key: "accept", done: rooms.some((r) => r.counts.published > 0), to: ran ? `/distill?room=${ran.id}&state=ok` : undefined },
  ];
  const doneN = steps.filter((s) => s.done).length;
  if (off || cloud.isLoading || doneN === steps.length) return null;
  const next = steps.find((s) => !s.done)!;
  const hide = () => {
    try {
      localStorage.setItem(HIDE_KEY, "1");
    } catch {
      /* the guide simply shows again next time */
    }
    setOff(true);
  };
  return (
    <section className="fx-card" style={{ padding: 16 }} aria-labelledby="start-title">
      <div className="fx-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h2 id="start-title" style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{t("start.title")}</h2>
          <p className="fx-muted fx-tiny" style={{ margin: "2px 0 0" }}>{t("start.intro")}</p>
        </div>
        <button className="fx-a fx-tiny" onClick={hide}>{t("start.hide")}</button>
      </div>
      <div className="fx-row" style={{ gap: 8, margin: "10px 0" }}>
        <Bar pct={(100 * doneN) / steps.length} width={140} ok label={t("start.progress", { n: doneN, total: steps.length })} />
        <span className="fx-tiny fx-muted">{t("start.progress", { n: doneN, total: steps.length })}</span>
      </div>
      <ol className="fx-stack" style={{ gap: 6, margin: 0, paddingLeft: 0, listStyle: "none" }}>
        {steps.map((s, i) => (
          <li key={s.key} className="fx-row" style={{ gap: 10, alignItems: "flex-start" }} aria-current={s === next ? "step" : undefined}>
            <span aria-hidden="true" className={`fx-pill ${s.done ? "p-ok" : s === next ? "p-run" : "p-idle"}`} style={{ minWidth: 24, justifyContent: "center" }}>
              {s.done ? "✓" : i + 1}
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: s === next ? 600 : 400, textDecoration: s.done ? "line-through" : undefined }} className={s.done ? "fx-muted" : undefined}>
                {t(`start.step.${s.key}.title`)}
                <span className="sr-only"> — {s.done ? t("start.done") : t("start.todo")}</span>
              </div>
              {!s.done && <div className="fx-tiny fx-muted">{t(`start.step.${s.key}.hint`)}{s.note ? ` ${s.note}` : ""}</div>}
            </div>
            {!s.done && s === next && s.to && <Link className="fx-btn pri sm" to={s.to}>{t(`start.step.${s.key}.go`)}</Link>}
          </li>
        ))}
      </ol>
    </section>
  );
}
