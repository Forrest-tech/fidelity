import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { Select } from "antd";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorState, Loading, PageHeader, Pill } from "../components/ui";
import { FixDrawer, reason } from "../components/FixDrawer";
import { loadFiles, type FileRow } from "../components/RoomFiles";

/** 对比复核 — the source page beside its distilled text, one page at a time, with every place the check found marked on
 * both (2026-11-26: the owner could not tell from "missing: 2, 0, 5" or a whole-file green diff where a difference
 * was). A number difference is settled here: confirm "the source says so", or fix it; a file whose number
 * differences are all settled is no longer held back by the number guard. */

interface RoomLite { id: string; name: string; threshold: number; number_guard: boolean; archived: boolean }
interface Value { value: string; in_result: boolean; boxes: number[][] }
interface PageItem { i: number; kind: string; detail: string; known: boolean; values: Value[] }
interface PageView {
  rel: string; page: number; pages: number; has_source: boolean; distilled: string; source_text: string;
  items: PageItem[]; pages_with_findings: number[];
}
interface Place { i: number; kind: string; page: number | null; detail: string; known?: boolean }

const ORDER: Record<string, number> = { below: 0, ok: 1, published: 2 };
const TONE: Record<string, "warn" | "ok" | "idle"> = { below: "warn", ok: "ok", published: "ok" };

function esc(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The distilled text with the values of the chosen place marked (numbers as whole numbers only). */
function Marked({ text, values }: { text: string; values: string[] }) {
  const vs = values.filter(Boolean);
  if (!vs.length || !text) return <>{text}</>;
  const rx = new RegExp(`(${vs.map((v) => (/^[\d.,]+$/.test(v) ? `(?<![\\d.])${esc(v)}(?![\\d])` : esc(v))).join("|")})`, "g");
  const parts = text.split(rx);
  return <>{parts.map((p, k) => (vs.includes(p) ? <mark key={k}>{p}</mark> : p))}</>;
}

export function ReviewPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const canEdit = me?.role !== "viewer";
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const roomId = params.get("room") || "";
  const rel = params.get("rel") || "";
  const pageN = Math.max(0, Math.floor(Number(params.get("page") || 0) || 0));
  const [sel, setSel] = useState<number | null>(null);
  const [fixing, setFixing] = useState(false);
  const [zoom, setZoom] = useState(false);
  const set = (k: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [a, b] of Object.entries(k)) (b == null || b === "" ? next.delete(a) : next.set(a, b));
    setParams(next, { replace: true });
  };

  const rooms = useQuery({
    queryKey: ["rooms", "review-list"],
    queryFn: async () => {
      const [a, b] = await Promise.all([api<{ rooms: RoomLite[] }>("/rooms?archived=false"), api<{ rooms: RoomLite[] }>("/rooms?archived=true")]);
      return [...a.rooms, ...b.rooms];
    },
  });
  const room = rooms.data?.find((r) => r.id === roomId) ?? null;
  useEffect(() => {
    if (!roomId && rooms.data?.length) set({ room: rooms.data[0].id, rel: null, page: null });
  }, [rooms.data, roomId]); // eslint-disable-line react-hooks/exhaustive-deps

  const files = useQuery({ queryKey: ["room-files", roomId, "review"], queryFn: () => loadFiles(roomId, "", ""), enabled: !!roomId });
  const reviewable = useMemo(
    () => (files.data ?? []).filter((f) => f.state in ORDER).sort((a, b) => ORDER[a.state] - ORDER[b.state] || (a.accuracy ?? 0) - (b.accuracy ?? 0)),
    [files.data],
  );
  const file: FileRow | undefined = reviewable.find((f) => f.rel === rel);
  useEffect(() => {
    if (files.data && (!rel || !reviewable.some((f) => f.rel === rel)) && reviewable.length) set({ rel: reviewable[0].rel, page: null });
  }, [files.data, rel]); // eslint-disable-line react-hooks/exhaustive-deps

  const places = useQuery({
    queryKey: ["review", roomId, rel],
    queryFn: () => api<{ items: Place[] }>(`/rooms/${roomId}/review?rel=${encodeURIComponent(rel)}`),
    enabled: !!roomId && !!rel && !!file,
    retry: false,
  });
  const items = places.data?.items ?? [];
  const firstPage = items.find((p) => p.page != null && !p.known)?.page ?? items.find((p) => p.page != null)?.page ?? 1;
  const n = pageN || firstPage;
  const view = useQuery({
    queryKey: ["review-page", roomId, rel, n],
    queryFn: async () => {
      const d = await api<Partial<PageView>>(`/rooms/${roomId}/pages/${n}?rel=${encodeURIComponent(rel)}`);
      return { rel, page: n, pages: 0, has_source: false, distilled: "", source_text: "", pages_with_findings: [], ...d,
        items: (d.items ?? []).map((x) => ({ ...x, values: x.values ?? [] })) } as PageView;
    },
    enabled: !!roomId && !!rel && !!file,
    retry: false,
  });
  const v = view.data;
  useEffect(() => setSel(v?.items?.[0]?.i ?? null), [v?.page, v?.rel]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = v?.items?.find((x) => x.i === sel) ?? null;

  const known = useMutation({
    mutationFn: (b: { item: number; known: boolean }) => api(`/rooms/${roomId}/places/known`, json({ rel, ...b })),
    onSuccess: () => {
      for (const k of ["review", "review-page", "room-files", "rooms", "accept-preview"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });

  const go = (p: number) => set({ page: String(Math.max(1, Math.min(v?.pages || p, p))) });
  const withPlaces = v?.pages_with_findings ?? [];
  const nextPlace = withPlaces.find((p) => p > n);
  const prevPlace = [...withPlaces].reverse().find((p) => p < n);
  const open = items.filter((p) => !p.known);
  const numbersOpen = file?.numbers_open ?? 0;

  if (rooms.isLoading) return <Loading />;
  if (rooms.error) return <ErrorState message={(rooms.error as Error).message} onRetry={() => void rooms.refetch()} />;
  if (!rooms.data?.length) return <><PageHeader title={t("pages.review2.title")} desc={t("pages.review2.desc")} /><EmptyState title={t("pages.review2.noRooms")} /></>;

  return (
    <div className="fx-review2">
      <PageHeader title={t("pages.review2.title")} desc={t("pages.review2.desc")}
        extra={<Link className="fx-a fx-tiny" to="/review/legacy">{t("pages.review2.legacy")}</Link>} />
      <div className="fx-card tight fx-row fx-wrap" style={{ gap: 10 }}>
        <label className="fx-row" style={{ gap: 6 }}>
          <span className="fx-lab" style={{ margin: 0 }}>{t("pages.review2.room")}</span>
          <Select style={{ minWidth: 200 }} value={roomId || undefined} onChange={(id) => set({ room: id, rel: null, page: null })}
            aria-label={t("pages.review2.room")}
            options={rooms.data.map((r) => ({ value: r.id, label: r.archived ? `${r.name} (${t("pages.review2.archived")})` : r.name }))} />
        </label>
        <label className="fx-row" style={{ gap: 6, flex: 1, minWidth: 260 }}>
          <span className="fx-lab" style={{ margin: 0 }}>{t("pages.review2.file")}</span>
          <Select showSearch style={{ flex: 1, minWidth: 220 }} value={rel || undefined} onChange={(r) => set({ rel: r, page: null })}
            aria-label={t("pages.review2.file")} loading={files.isLoading} optionFilterProp="label"
            options={reviewable.map((f) => ({
              value: f.rel,
              label: `${f.name} · ${t(`pages.distill.state.${f.state}`)}${f.accuracy != null ? ` · ${f.accuracy}%` : ""}${(f.numbers_open ?? 0) > 0 ? ` · ${t("pages.review2.numbersOpen", { count: f.numbers_open })}` : ""}`,
            }))} />
        </label>
        <Link className="fx-a fx-tiny" to={`/distill?room=${roomId}`}>{t("pages.review2.backToRoom")}</Link>
      </div>

      {files.data && !reviewable.length && <EmptyState title={t("pages.review2.noFiles")} />}

      {file && room && (
        <>
          <div className="fx-card tight fx-row fx-wrap" style={{ gap: "6px 14px", marginTop: 10 }}>
            <b>{file.name}</b>
            <Pill tone={TONE[file.state] ?? "idle"}>{t(`pages.distill.state.${file.state}`)}</Pill>
            <span className="fx-tiny">{t("pages.review2.accuracy", { acc: file.accuracy ?? "—", thr: room.threshold })}</span>
            <span className="fx-tiny fx-muted">{t("pages.review2.placesSummary", { total: items.length, open: open.length })}</span>
            <span className="fx-sp" />
            <button className="fx-btn sm" onClick={() => setFixing(true)}>{canEdit ? t("pages.review2.fixText") : t("pages.review2.openText")}</button>
          </div>
          {file.state === "below" && (
            <div className="fx-note warn" style={{ marginTop: 8 }} role="status">
              {room.number_guard && numbersOpen > 0 && (file.accuracy ?? 0) >= room.threshold
                ? t("pages.review2.whyNumbers", { count: numbersOpen, acc: file.accuracy, thr: room.threshold })
                : t("pages.review2.whyThreshold", { acc: file.accuracy ?? "—", thr: room.threshold })}
            </div>
          )}

          <div className="fx-rv-grid">
            <aside className="fx-card tight fx-rv-list" aria-label={t("pages.review2.places")}>
              <div className="fx-row"><b>{t("pages.review2.places")}</b><span className="fx-sp" /><span className="fx-tiny fx-muted">{open.length}/{items.length}</span></div>
              {places.isLoading && <Loading />}
              {!places.isLoading && !items.length && <div className="fx-tiny fx-muted">{t("pages.review2.noPlaces")}</div>}
              <ul>
                {items.map((p) => (
                  <li key={p.i}>
                    <button className={`fx-rv-place${p.page === n && p.i === sel ? " on" : ""}${p.known ? " done" : ""}`}
                      onClick={() => { if (p.page) set({ page: String(p.page) }); setSel(p.i); }}>
                      <span className="fx-tiny fx-muted">{p.page != null ? t("pages.review2.pageN", { n: p.page }) : "—"}</span>{" "}
                      <b className="fx-tiny">{t(`pages.distill.places.kind.${p.kind}`, { defaultValue: p.kind })}</b>
                      <span className="fx-rv-detail">{reason(t, p.detail)}</span>
                      {p.known && <span className="fx-tiny" style={{ color: "var(--ok)" }}>✓ {t("pages.review2.confirmed")}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </aside>

            <section className="fx-card tight fx-rv-main">
              <div className="fx-row fx-wrap" style={{ gap: 8 }}>
                <button className="fx-btn sm" disabled={n <= 1} onClick={() => go(n - 1)} aria-label={t("pages.review2.prevPage")}>‹</button>
                <span className="fx-num">{t("pages.review2.pageOf", { n, total: v?.pages || "?" })}</span>
                <button className="fx-btn sm" disabled={!!v && n >= v.pages} onClick={() => go(n + 1)} aria-label={t("pages.review2.nextPage")}>›</button>
                <button className="fx-btn sm" disabled={prevPlace == null} onClick={() => prevPlace != null && go(prevPlace)}>{t("pages.review2.prevPlace")}</button>
                <button className="fx-btn sm" disabled={nextPlace == null} onClick={() => nextPlace != null && go(nextPlace)}>{t("pages.review2.nextPlace")}</button>
                <span className="fx-sp" />
                <label className="fx-tiny fx-row" style={{ gap: 4 }}><input type="checkbox" checked={zoom} onChange={(e) => setZoom(e.target.checked)} />{t("pages.review2.zoom")}</label>
              </div>

              {chosen && (
                <div className="fx-rv-chosen">
                  <div>
                    <b>{t(`pages.distill.places.kind.${chosen.kind}`, { defaultValue: chosen.kind })}</b> · {reason(t, chosen.detail)}
                  </div>
                  {chosen.values.length > 0 && (
                    <div className="fx-tiny" style={{ marginTop: 4 }}>
                      {chosen.values.map((x) => (
                        <span key={x.value} className="fx-rv-val">
                          <code>{x.value}</code> {t("pages.review2.onSource", { count: x.boxes.length })} ·{" "}
                          {x.in_result ? <span style={{ color: "var(--ok)" }}>{t("pages.review2.inResult")}</span> : <span style={{ color: "var(--bad)" }}>{t("pages.review2.notInResult")}</span>}
                        </span>
                      ))}
                    </div>
                  )}
                  {canEdit && (
                    <div className="fx-row" style={{ gap: 8, marginTop: 6 }}>
                      {chosen.known ? (
                        <button className="fx-btn sm" disabled={known.isPending} onClick={() => known.mutate({ item: chosen.i, known: false })}>{t("pages.review2.unconfirm")}</button>
                      ) : (
                        <button className="fx-btn sm pri" disabled={known.isPending} onClick={() => known.mutate({ item: chosen.i, known: true })}>{t("pages.review2.confirm")}</button>
                      )}
                      <button className="fx-btn sm" onClick={() => setFixing(true)}>{t("pages.review2.fix")}</button>
                      <span className="fx-tiny fx-muted">{t("pages.review2.confirmHint")}</span>
                    </div>
                  )}
                  {known.error && <div className="fx-errnote">{(known.error as Error).message}</div>}
                </div>
              )}
              {v && v.items.length > 1 && (
                <div className="fx-row fx-wrap fx-tiny" style={{ gap: 6, marginTop: 6 }}>
                  {v.items.map((x, k) => (
                    <button key={x.i} className={`fx-chip${x.i === sel ? " on" : ""}`} onClick={() => setSel(x.i)}>
                      {k + 1}. {t(`pages.distill.places.kind.${x.kind}`, { defaultValue: x.kind })}{x.known ? " ✓" : ""}
                    </button>
                  ))}
                </div>
              )}

              {view.isLoading && <Loading />}
              {view.error && <ErrorState message={(view.error as Error).message} onRetry={() => void view.refetch()} />}
              {v && (
                <div className={`fx-rv-panes${zoom ? " zoom" : ""}`}>
                  <figure className="fx-rv-pane">
                    <figcaption className="fx-tiny fx-muted">{t("pages.review2.original", { n })}</figcaption>
                    {v.has_source ? (
                      <div className="fx-rv-img">
                        <img src={`/api/v1/rooms/${roomId}/pages/${n}/image?rel=${encodeURIComponent(rel)}&dpi=${zoom ? 160 : 110}`}
                          alt={t("pages.review2.original", { n })} />
                        {v.items.flatMap((x) => x.values.flatMap((val) => val.boxes.map((b, k) => (
                          <span key={`${x.i}-${val.value}-${k}`} className={`fx-rv-box${x.i === sel ? " on" : ""}${val.in_result ? "" : " miss"}`}
                            style={{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%` }}
                            title={val.value} />
                        ))))}
                      </div>
                    ) : (
                      <div className="fx-warnnote">{t("pages.review2.noSource")}</div>
                    )}
                  </figure>
                  <figure className="fx-rv-pane">
                    <figcaption className="fx-tiny fx-muted">{t("pages.review2.distilled", { n })}</figcaption>
                    <pre className="fx-rv-text">{v.distilled ? <Marked text={v.distilled} values={chosen?.values.map((x) => x.value) ?? []} /> : t("pages.review2.noText")}</pre>
                  </figure>
                </div>
              )}
            </section>
          </div>
          {fixing && <FixDrawer roomId={roomId} rel={rel} canEdit={canEdit} threshold={room.threshold} onClose={() => { setFixing(false); void qc.invalidateQueries({ queryKey: ["review-page"] }); }} />}
        </>
      )}
    </div>
  );
}

export default ReviewPage;
