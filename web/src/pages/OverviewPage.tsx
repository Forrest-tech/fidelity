import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Bar, EmptyState, ErrorState, Loading, PageHeader, Pill } from "../components/ui";
import type { Room } from "./DistillPage";
import type { Notice } from "../layout/AppShell";
import { GettingStarted } from "../components/GettingStarted";

interface Library {
  rules: { hits: number; enabled: boolean }[];
  total: number;
  enabled: number;
}

function Stat({ label, value, sub, to, id }: { label: string; value: number | string; sub?: string; to?: string; id: string }) {
  const body = (
    <>
      <div className="fx-muted fx-tiny">{label}</div>
      <div className="fx-num" style={{ fontSize: 30, fontWeight: 600, lineHeight: 1.15, marginTop: 4 }} data-testid={`stat-${id}`}>{value}</div>
      {sub && <div className="fx-muted fx-tiny" style={{ marginTop: 2 }}>{sub}</div>}
    </>
  );
  return to ? (
    <Link to={to} className="fx-card" style={{ padding: 14, color: "inherit", textDecoration: "none", display: "block" }}>{body}</Link>
  ) : (
    <div className="fx-card" style={{ padding: 14 }}>{body}</div>
  );
}

/** The overview: how all rooms stand, what needs a person, and whether the learning loop is working. */
export function OverviewPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const nav = useNavigate();
  const rooms = useQuery({ queryKey: ["rooms", "active"], queryFn: () => api<{ rooms: Room[] }>("/rooms?archived=false"), refetchInterval: 15000 });
  const archived = useQuery({ queryKey: ["rooms", "archived"], queryFn: () => api<{ rooms: Room[] }>("/rooms?archived=true") });
  const notes = useQuery({ queryKey: ["notifications"], queryFn: () => api<{ items: Notice[]; unread: number }>("/notifications") });
  const lib = useQuery({ queryKey: ["corrections"], queryFn: () => api<Library>("/corrections") });
  if (rooms.isLoading) return <Loading />;
  if (rooms.isError) return <ErrorState message={(rooms.error as Error).message} onRetry={() => void rooms.refetch()} />;
  const list = rooms.data?.rooms ?? [];
  const all = [...list, ...(archived.data?.rooms ?? [])];
  const sum = (k: keyof Room["counts"]) => all.reduce((a, r) => a + (r.counts[k] as number), 0);
  const total = sum("total");
  const finished = sum("finished");
  const running = list.filter((r) => r.job?.status === "running").length;
  const queued = list.filter((r) => r.job?.status === "queued").length;
  const hits = (lib.data?.rules ?? []).reduce((a, r) => a + r.hits, 0);
  const attention = (notes.data?.items ?? []).filter((n) => n.type !== "done" && n.type !== "published").slice(0, 8);
  const canEdit = me?.role === "reviewer" || me?.role === "admin";
  return (
    <div className="fx-stack">
      <PageHeader title={t("pages.overview.title")} desc={t("pages.overview.intro")}
        extra={canEdit && <button className="fx-btn pri" onClick={() => nav("/distill?new=1")}>+ {t("pages.distill.newRoom")}</button>} />
      <GettingStarted rooms={all} />
      {!all.length ? (
        <EmptyState title={t("pages.overview.emptyRooms")} hint={t("pages.overview.emptyRoomsHint")} />
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
            <Stat id="rooms" label={t("pages.overview.rooms")} value={list.length} sub={t("pages.overview.roomsSub", { running, queued, archived: archived.data?.rooms.length ?? 0 })} to="/distill" />
            <Stat id="files" label={t("pages.overview.files")} value={total} sub={t("pages.overview.filesSub", { done: finished, pct: total ? Math.round((100 * finished) / total) : 0 })} />
            <Stat id="review" label={t("pages.overview.toReview")} value={sum("below")} sub={t("pages.overview.toReviewSub")} />
            <Stat id="cannot" label={t("pages.overview.cannot")} value={sum("unprocessable")} sub={t("pages.overview.cannotSub")} />
            <Stat id="accepted" label={t("pages.overview.accepted")} value={sum("published")} sub={t("pages.overview.acceptedSub", { ok: sum("ok") })} />
            <Stat id="rules" label={t("pages.overview.rules")} value={lib.data?.enabled ?? 0} sub={t("pages.overview.rulesSub", { hits })} to="/settings/corrections" />
          </div>
          <section aria-labelledby="attn" className="fx-stack" style={{ gap: 8 }}>
            <h2 id="attn" style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{t("pages.overview.attention")}</h2>
            {!attention.length ? (
              <div className="fx-muted">{t("pages.overview.attentionNone")}</div>
            ) : (
              <div className="fx-tbox">
                <table className="fx-t">
                  <tbody>
                    {attention.map((n) => (
                      <tr key={n.key} style={{ cursor: "pointer" }} onClick={() => nav(n.to)}>
                        <td style={{ width: 110 }}><Pill tone={n.tone === "warn" ? "warn" : n.tone}>{t(`shell.n.${n.type}.pill`)}</Pill></td>
                        <td>
                          <Link to={n.to} onClick={(e) => e.stopPropagation()} style={{ color: "inherit" }}>
                            {t(`shell.n.${n.type}.title`, { room: n.room_name, n: n.n, pct: n.pct, num: n.num, reverts: n.reverts, skill: n.skill ? t(`pages.ai.skill.${n.skill}`) : "" })}
                          </Link>
                          <div className="fx-muted fx-tiny">{t(`shell.n.${n.type}.sub`, { room: n.room_name, message: n.message, skill: n.skill ? t(`pages.ai.skill.${n.skill}`) : "" })}</div>
                        </td>
                        <td className="fx-muted fx-tiny" style={{ textAlign: "right", whiteSpace: "nowrap" }}>{t(`shell.n.${n.type}.to`)} →</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section aria-labelledby="rooms" className="fx-stack" style={{ gap: 8 }}>
            <h2 id="rooms" style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{t("pages.overview.roomsTitle")}</h2>
            <div className="fx-tbox" style={{ overflowX: "auto" }}>
              <table className="fx-t" style={{ minWidth: 640 }}>
                <thead><tr><th>{t("pages.distill.colRoom")}</th><th>{t("pages.distill.colState")}</th><th>{t("pages.distill.files")}</th><th>{t("pages.distill.rate")}</th><th>{t("pages.distill.colAccuracyShort")}</th></tr></thead>
                <tbody>
                  {list.map((r) => (
                    <tr key={r.id}>
                      <td><Link to={`/distill?room=${r.id}`}><b>{r.name}</b></Link></td>
                      <td>
                        {r.job?.status === "running" ? <Pill tone="run">{t("pages.distill.runningPill")}</Pill>
                          : r.job?.status === "queued" ? <Pill tone="idle">{t("pages.distill.room.queued", { n: r.job.position ?? 1 })}</Pill>
                          : r.counts.below ? <Pill tone="warn">{t("pages.distill.room.review", { n: r.counts.below })}</Pill>
                          : r.counts.total ? <Pill tone="ok">{t("pages.distill.room.done")}</Pill>
                          : <Pill tone="idle">{t("pages.distill.room.notRun")}</Pill>}
                      </td>
                      <td className="fx-num">{r.counts.finished} / {r.counts.total}</td>
                      <td><span className="fx-row" style={{ gap: 6 }}><Bar pct={r.counts.rate} width={90} label={t("pages.distill.rate")} /><span className="fx-num fx-tiny">{Math.round(r.counts.rate)}%</span></span></td>
                      <td className="fx-num">{r.accuracy_avg != null ? `${r.accuracy_avg}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
