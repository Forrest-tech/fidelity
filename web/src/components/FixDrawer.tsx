import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Drawer, Popconfirm, Spin } from "antd";
import { api, json } from "../net/client";
import { Pill, Seg } from "./ui";
import { FormulaPlace } from "./FormulaPlace";
import type { FormulaItem } from "./FormulaPlace";
import type { FileRow } from "./RoomFiles";

interface Applied {
  rule: string;
  num: number;
  find: string;
  replace: string;
  kind: "text" | "number" | "pattern";
  count: number;
  check: boolean;
  auto?: boolean;
}
interface ResultView {
  rel: string;
  series: string | null;
  files: { path: string; text: string; cut: boolean }[];
  corrections: Applied[];
}
interface Suggestion {
  call: string;
  skill: "arbitrate" | "explain" | "transcribe";
  status: "ok" | "cached" | "invalid" | "error" | "blocked";
  message: string | null;
  decision: string | null;
  result: { text?: string | null; confidence?: number; reason?: string; needs_human?: boolean; action?: string } | null;
}
interface Place {
  i: number;
  kind: string;
  page: number | null;
  detail: string;
  known?: boolean;
  candidates?: string[];
  in_text?: string | null;
  before?: string;
  after?: string;
  suggestion?: Suggestion | null;
  formulas?: FormulaItem[] | null;
}
interface Review {
  items: Place[];
  ai: { enabled: boolean; skills: Record<string, { level: number }> };
}
interface Match {
  room_id: string;
  room: string;
  rel: string;
  places: number;
}
interface Preview {
  kind: "text" | "number";
  before: string;
  after: string;
  series: string | null;
  here: number;
  others: Match[];
  other_places: number;
}
interface Saved {
  rule: { id: string; num: number };
  others: Match[];
}
type Scope = "document" | "series" | "all";
type Sel = { type: "rule"; c: Applied } | { type: "place"; p: Place } | null;

const KIND_TONE: Record<string, "idle" | "warn" | "bad" | "ai"> = { reading: "idle", text: "idle", numbers: "warn", formula: "warn", headings: "bad", tables: "warn" };
const okS = (s?: Suggestion | null) => !!s && (s.status === "ok" || s.status === "cached") && !!s.result;

/** Screen 2 of the design: one file's places that need a look, on the left; the chosen place, its fix and "remember
 * this fix", on the right. A fix is kept as a rule; numbers only ever match with their exact context. */
/** The checker writes its reasons in English ("missing: 2, 0, 5"); show them in the person's language. */
export function reason(t: (k: string, o?: Record<string, unknown>) => string, detail?: string | null): string {
  const d = detail || "";
  let m = d.match(/^missing: (.+)$/);
  if (m) return t("pages.distill.checkReason.missing", { nums: m[1] });
  m = d.match(/^recall ([\d.]+), (\d+) characters missing$/);
  if (m) return t("pages.distill.checkReason.lost", { n: m[2], pct: (Number(m[1]) * 100).toFixed(1) });
  m = d.match(/^(\d+) characters not on the source page$/);
  if (m) return t("pages.distill.checkReason.extra", { n: m[1] });
  return d;
}

export function FixDrawer({ roomId, rel, canEdit, onClose, threshold }: { roomId: string; rel: string | null; canEdit: boolean; onClose: () => void; threshold?: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const view = useQuery({ queryKey: ["result", roomId, rel], queryFn: () => api<ResultView>(`/rooms/${roomId}/result?rel=${encodeURIComponent(rel!)}`), enabled: !!rel, retry: false });
  const review = useQuery({ queryKey: ["review", roomId, rel], queryFn: () => api<Review>(`/rooms/${roomId}/review?rel=${encodeURIComponent(rel!)}`), enabled: !!rel, retry: false });
  const files = qc.getQueryData<FileRow[]>(["room-files", roomId, "", ""]);
  const file = files?.find((f) => f.rel === rel);
  const [sel, setSel] = useState<Sel>(null);
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [remember, setRemember] = useState(true);
  const [scope, setScope] = useState<Scope>("series");
  const [aiCall, setAiCall] = useState<{ call: string; text: string } | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [toast, setToast] = useState<Saved | null>(null);
  const [showText, setShowText] = useState(false);
  const [free, setFree] = useState(false);
  const v = view.data;
  const items = review.data?.items ?? [];
  const level = (skill: string) => (review.data?.ai?.enabled ? review.data.ai.skills?.[skill]?.level ?? 0 : 0);

  useEffect(() => {
    setSel(null);
    setFind("");
    setReplace("");
    setAiCall(null);
    setToast(null);
    setShowText(false);
    setFree(false);
  }, [rel]);
  useEffect(() => setScope(v?.series ? "series" : "document"), [v?.series]);
  // the first place that needs a look is opened by itself
  useEffect(() => {
    if (sel || free || !review.data) return;
    const first = items.find((p) => !p.known) ?? items[0];
    if (first) choose({ type: "place", p: first });
    else if (v?.corrections[0]) choose({ type: "rule", c: v.corrections[0] });
  }, [review.data, v]); // eslint-disable-line react-hooks/exhaustive-deps
  // level 2: new reading places are asked about by default when the file is opened
  useEffect(() => {
    if (canEdit && rel && level("arbitrate") >= 2) void api(`/rooms/${roomId}/ask-default`, json({ rel })).then(() => qc.invalidateQueries({ queryKey: ["review", roomId, rel] }), () => undefined);
  }, [rel, review.data?.ai?.enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (s: Sel) => {
    setSel(s);
    setFree(false);
    setPreview(null);
    setPreviewErr(null);
    setAiCall(null);
    if (s?.type === "place" && s.p.kind === "reading" && s.p.in_text) {
      const sug = okS(s.p.suggestion) && s.p.suggestion!.result!.text ? s.p.suggestion! : null;
      setFind(s.p.in_text);
      setReplace(sug?.result?.text ?? (s.p.candidates ?? []).find((c) => c !== s.p.in_text) ?? s.p.in_text);
      if (sug && !sug.decision) setAiCall({ call: sug.call, text: sug.result!.text! });
    } else {
      setFind("");
      setReplace("");
    }
  };
  const refresh = () => {
    for (const k of ["result", "review", "room-files", "rooms", "accept-preview", "corrections", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
  };
  const draft = () => ({ room_id: roomId, rel, find, replace, scope: remember ? scope : "document" });
  // the preview follows what is typed
  useEffect(() => {
    setPreview(null);
    setPreviewErr(null);
    if (!canEdit || !rel || !find || find === replace) return;
    const h = setTimeout(() => {
      api<Preview>("/corrections/preview", json(draft())).then(setPreview, (e: Error) => setPreviewErr(e.message));
    }, 450);
    return () => clearTimeout(h);
  }, [find, replace, scope, remember, rel]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    mutationFn: async () => {
      const d = draft();
      const out = await api<Saved>("/corrections", json(d));
      if (aiCall) await api(`/ai/calls/${aiCall.call}/decision`, json({ decision: d.replace === aiCall.text ? "adopted" : "modified", final: d.replace }));
      return out;
    },
    onSuccess: (s) => {
      setToast(s);
      setAiCall(null);
      refresh();
    },
  });
  const applyOthers = useMutation({ mutationFn: (id: string) => api(`/corrections/${id}/apply`, { method: "POST" }), onSuccess: () => { setToast(null); refresh(); } });
  const undoNew = useMutation({
    mutationFn: async (id: string) => {
      await api(`/corrections/${id}`, { ...json({ enabled: false }), method: "PATCH" });
      await api(`/corrections/${id}/apply`, { method: "POST" });
    },
    onSuccess: () => { setToast(null); refresh(); },
  });
  const rulePlace = useMutation({ mutationFn: (p: { what: "undo" | "confirm"; rule: string }) => api(`/rooms/${roomId}/corrections/${p.what}`, json({ rel, rule_id: p.rule })), onSuccess: refresh });
  const ask = useMutation({ mutationFn: (i: number) => api(`/rooms/${roomId}/ask`, json({ rel, item: i })), onSuccess: () => void qc.invalidateQueries({ queryKey: ["review", roomId, rel] }) });
  const reject = useMutation({ mutationFn: (call: string) => api(`/ai/calls/${call}/decision`, json({ decision: "rejected" })), onSuccess: () => void qc.invalidateQueries({ queryKey: ["review", roomId, rel] }) });
  const known = useMutation({
    mutationFn: (p: { item: number; known: boolean }) => api<Review>(`/rooms/${roomId}/places/known`, json({ rel, ...p })),
    onSuccess: (d) => {
      qc.setQueryData(["review", roomId, rel], d);
      if (sel?.type === "place") setSel({ type: "place", p: d.items.find((x) => x.i === sel.p.i) ?? sel.p });
    },
  });
  const acceptOne = useMutation({ mutationFn: () => api(`/rooms/${roomId}/accept`, json({ rels: [rel], force: true })), onSuccess: refresh });
  const err = (save.error || applyOthers.error || undoNew.error || rulePlace.error || ask.error || reject.error || known.error || acceptOne.error) as Error | null;

  // keep the chosen place in step with fresh data (a suggestion arrives, a formula is approved)
  const current: Sel = useMemo(() => {
    if (sel?.type === "place") return { type: "place", p: items.find((x) => x.i === sel.p.i) ?? sel.p };
    if (sel?.type === "rule") return { type: "rule", c: v?.corrections.find((c) => c.rule === sel.c.rule) ?? sel.c };
    return sel;
  }, [sel, items, v]);
  const name = rel?.split("/").pop() ?? "";
  const handled = items.filter((p) => p.known || (p.suggestion?.decision && p.suggestion.decision !== "rejected") || (p.formulas ?? []).some((f) => f.approved)).length + (v?.corrections.length ?? 0);
  const autoFixed = (v?.corrections ?? []).reduce((a, c) => a + c.count, 0);
  const acc = file?.accuracy ?? null;
  const placeStatus = (p: Place) => {
    if (p.known) return t("pages.distill.fix2.known");
    if ((p.formulas ?? []).length && (p.formulas ?? []).every((f) => f.approved)) return t("pages.distill.fix2.approved");
    if (p.suggestion?.decision === "adopted" || p.suggestion?.decision === "modified") return t("pages.distill.fix2.taken");
    if (okS(p.suggestion) && !p.suggestion!.decision) return t("pages.distill.fix2.toConfirm");
    return t("pages.distill.fix2.open");
  };
  const takeSelection = () => {
    const s = window.getSelection()?.toString() ?? "";
    if (canEdit && s && !s.includes("\n") && s.length <= 200) {
      setFind(s);
      if (!replace || current?.type !== "place" || current.p.kind !== "reading") setReplace(s);
    }
  };

  // ------------------------------------------------------------------ the right-hand detail
  const rememberBox = (
    <div className="fx-card" style={{ padding: 10, display: "grid", gap: 6 }}>
      <label className="fx-row">
        <input type="checkbox" className="fx-cb" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <b>{t("pages.distill.fix2.remember")}</b>
      </label>
      {remember && (
        <Seg tiny label={t("pages.distill.fix.scope")} value={scope} onChange={setScope}
          options={[
            { value: "document", label: t("pages.distill.fix.scopeDocument") },
            ...(v?.series ? [{ value: "series" as Scope, label: t("pages.distill.fix2.scopeSeries", { series: v.series }) }] : []),
            { value: "all", label: t("pages.distill.fix.scopeAll") },
          ]} />
      )}
      <div className="fx-tiny fx-muted" role="status" aria-live="polite">
        {previewErr ? <span style={{ color: "var(--bad)" }}>{previewErr}</span>
          : preview ? (
            <>
              {t("pages.distill.fix2.previewHere", { count: preview.here })}{" "}
              {preview.others.length ? t("pages.distill.fix.previewOthers", { places: preview.other_places, count: preview.others.length }) : t("pages.distill.fix.previewNoOthers")}
              {preview.kind === "number" && <> {t("pages.distill.fix2.numberExact")} <code>{preview.before}<mark>{find}</mark>{preview.after}</code></>}
            </>
          ) : find && find !== replace ? t("pages.distill.fix2.previewing") : t("pages.distill.fix2.typeFix")}
      </div>
    </div>
  );
  const fixFields = (labelWrong: string) => (
    <div style={{ display: "grid", gap: 8 }}>
      <label>
        <span className="fx-lab">{labelWrong}</span>
        <span className="fx-field sm"><input value={find} onChange={(e) => setFind(e.target.value)} maxLength={200} spellCheck={false} aria-label={t("pages.distill.fix.wrong")} /></span>
      </label>
      <label>
        <span className="fx-lab">{t("pages.distill.fix2.final")}</span>
        <span className="fx-field sm"><input value={replace} onChange={(e) => setReplace(e.target.value)} maxLength={200} spellCheck={false} aria-label={t("pages.distill.fix.right")} /></span>
      </label>
    </div>
  );
  const actions = (p?: Place, noSave = false) => (
    <div className="fx-row fx-wrap">
      {!noSave && <button className="fx-btn pri" disabled={!preview || save.isPending} onClick={() => save.mutate()}>{t("pages.distill.fix2.save")}</button>}
      {p && <button className="fx-btn" disabled={known.isPending} onClick={() => known.mutate({ item: p.i, known: !p.known })}>{p.known ? t("pages.distill.fix2.notKnown") : t("pages.distill.fix2.markKnown")}</button>}
    </div>
  );
  const aiNote = (p: Place) => {
    const s = p.suggestion;
    const skill = p.kind === "reading" ? "arbitrate" : "explain";
    if (okS(s) && s!.skill === "arbitrate") {
      return (
        <div className="fx-ainote">
          <b>{t("pages.distill.fix2.aiSuggests")}</b> ({Math.round((s!.result!.confidence ?? 0) * 100)}%){" "}
          {s!.result!.text == null ? t("pages.distill.places.aiUnsure") : <code>{s!.result!.text}</code>} · {s!.result!.reason}
          {s!.result!.needs_human && <div><b>{t("pages.distill.fix2.numbersNeedYou")}</b></div>}
          {canEdit && !s!.decision && <div style={{ marginTop: 4 }}><button className="fx-a" onClick={() => reject.mutate(s!.call)}>{t("pages.distill.places.notRight")}</button></div>}
          {s!.decision && <div className="fx-muted">{t(`pages.distill.places.decision.${s!.decision}`, { defaultValue: s!.decision })}</div>}
        </div>
      );
    }
    if (okS(s) && s!.skill === "explain") return <div className="fx-ainote"><b>{t("pages.distill.fix2.aiExplains")}</b> {s!.result!.reason} <span className="fx-muted">{s!.result!.action}</span></div>;
    if (s && !okS(s)) return <div className="fx-tiny fx-muted">{s.message || t(`pages.distill.places.status.${s.status}`, { defaultValue: s.status })}</div>;
    if (canEdit && level(skill) >= 1) {
      return <div><button className="fx-btn sm" disabled={ask.isPending} onClick={() => ask.mutate(p.i)}>{p.kind === "reading" ? t("pages.distill.places.askAi") : t("pages.distill.places.explain")}</button></div>;
    }
    return null;
  };
  let detail = null;
  if (current?.type === "rule") {
    const c = current.c;
    detail = (
      <>
        <b>{t("pages.distill.fix2.ruleTitle", { num: c.num })}{c.auto ? ` · ${t("pages.distill.fix2.byAi")}` : ""}</b>
        <div className="fx-snip"><mark>{c.find}</mark> → <mark className="g">{c.replace}</mark></div>
        <div className="fx-tiny fx-muted">{t("pages.distill.fix.places", { count: c.count })} · {c.kind === "number" ? t("pages.distill.fix2.numberRule") : c.kind === "pattern" ? t("pages.corrections.pattern") : t("pages.distill.fix2.textRule")}</div>
        {c.check && <div className="fx-warnnote">{t("pages.distill.fix.needsCheck")}</div>}
        {canEdit && (
          <div className="fx-row fx-wrap">
            {c.check && <button className="fx-btn pri" onClick={() => rulePlace.mutate({ what: "confirm", rule: c.rule })}>{t("pages.distill.fix.confirm")}</button>}
            <button className="fx-btn" onClick={() => rulePlace.mutate({ what: "undo", rule: c.rule })}>{t("pages.distill.fix.undo")}</button>
          </div>
        )}
        <Link className="fx-a" to={`/settings/corrections?rule=${c.rule}`}>{t("pages.distill.fix.library")}</Link>
      </>
    );
  } else if (current?.type === "place") {
    const p = current.p;
    detail = (
      <>
        <b>{p.page != null ? t("pages.distill.fix2.pageOf", { n: p.page }) : ""}{t(`pages.distill.places.kind.${p.kind}`, { defaultValue: p.kind })}</b>
        {p.kind === "reading" && (
          <>
            <div className="fx-snip">{p.in_text ? <>…{p.before} <mark>{p.in_text}</mark> {p.after}…</> : t("pages.distill.places.notInText")}</div>
            <div className="fx-row fx-wrap fx-tiny">
              <span className="fx-muted">{t("pages.distill.places.readings")}</span>
              {(p.candidates ?? []).map((c, k) => canEdit && p.in_text ? (
                <button key={k} className={`fx-chip${replace === c ? " on" : ""}`} onClick={() => { setReplace(c); setAiCall(null); }}>{c}</button>
              ) : <code key={k}>{c}</code>)}
            </div>
          </>
        )}
        {p.kind !== "reading" && p.kind !== "formula" && <div className="fx-snip">{reason(t, p.detail)}</div>}
        {p.kind === "formula" && p.formulas && p.page != null && (
          <div className="fx-stack" style={{ gap: 8 }}>
            {p.formulas.map((f) => (
              <FormulaPlace key={f.k} roomId={roomId} rel={rel!} page={p.page!} item={p.i} f={f} canEdit={canEdit} canAsk={level("transcribe") >= 1} onChanged={refresh} />
            ))}
          </div>
        )}
        {p.kind === "formula" && p.formulas === null && <div className="fx-tiny fx-muted">{t("pages.distill.places.noSource")}</div>}
        {p.kind !== "formula" && aiNote(p)}
        {canEdit && p.kind !== "formula" && (
          <>
            {p.kind === "reading" && p.in_text ? (
              <label>
                <span className="fx-lab">{t("pages.distill.fix2.final")}</span>
                <span className="fx-field sm"><input value={replace} onChange={(e) => setReplace(e.target.value)} maxLength={200} spellCheck={false} aria-label={t("pages.distill.fix.right")} /></span>
              </label>
            ) : fixFields(t("pages.distill.fix2.wrongHere"))}
            {rememberBox}
            {actions(p)}
          </>
        )}
        {canEdit && p.kind === "formula" && actions(p, true)}
      </>
    );
  } else if (canEdit && v) {
    detail = (
      <>
        <b>{t("pages.distill.fix2.freeTitle")}</b>
        <div className="fx-tiny fx-muted">{t("pages.distill.fix.hint")}</div>
        {fixFields(t("pages.distill.fix.wrong"))}
        {rememberBox}
        {actions()}
      </>
    );
  }

  return (
    <Drawer open={!!rel} onClose={onClose} size="min(1100px, 100vw)" title={name} destroyOnHidden styles={{ body: { padding: 0 } }}>
      {view.isLoading && <div style={{ padding: 20 }}><Spin /></div>}
      {view.isError && <div className="fx-errnote" style={{ margin: 16 }}>{(view.error as Error).message}</div>}
      {v && (
        <div className="fx-fixgrid">
          <div className="fx-stack" style={{ padding: "18px 20px", gap: 12, minWidth: 0 }}>
            <div className="fx-row">
              {acc != null && <div className={`fx-ring${file?.state === "below" ? " warn" : ""}`} style={{ ["--p" as string]: acc }}><b className="fx-num">{acc}%</b></div>}
              <div style={{ minWidth: 0 }}>
                <b style={{ wordBreak: "break-word" }}>{rel?.replace(/^\//, "").split("/").join(" / ")}</b>
                <div className="fx-muted fx-tiny">{t("pages.distill.fix2.summary", { n: items.length + (v.corrections.length || 0), done: handled, auto: autoFixed })}</div>
              </div>
            </div>
            {(items.length > 0 || v.corrections.length > 0) ? (
              <div className="fx-tbox" style={{ maxHeight: "48vh", overflowY: "auto" }}>
                <table className="fx-t">
                  <thead><tr><th>{t("pages.distill.fix2.colKind")}</th><th>{t("pages.distill.fix2.colPage")}</th><th>{t("pages.distill.fix2.colReason")}</th><th>{t("pages.distill.fix2.colChoice")}</th></tr></thead>
                  <tbody>
                    {v.corrections.map((c) => (
                      <tr key={c.rule} className={current?.type === "rule" && current.c.rule === c.rule ? "sel" : undefined} style={{ cursor: "pointer" }} onClick={() => choose({ type: "rule", c })}>
                        <td><Pill tone="idle">{c.kind === "number" ? t("pages.distill.places.kind.numbers") : t("pages.distill.fix2.chars")}</Pill></td>
                        <td className="fx-num fx-muted">—</td>
                        <td><Pill tone={c.auto ? "ai" : "ok"}>{t("pages.distill.fix2.rule", { num: c.num })}{c.auto ? ` · ${t("pages.distill.fix2.byAi")}` : ""}</Pill> <code>{c.find}</code> → <code>{c.replace}</code>{c.check && <> <Pill tone="warn">{t("pages.distill.fix.needsCheck")}</Pill></>}</td>
                        <td className="fx-muted fx-tiny">{t("pages.distill.fix2.autoFixed")} · <button className="fx-a" onClick={(e) => { e.stopPropagation(); rulePlace.mutate({ what: "undo", rule: c.rule }); }} disabled={!canEdit}>{t("pages.distill.fix2.undoShort")}</button></td>
                      </tr>
                    ))}
                    {items.map((p) => (
                      <tr key={p.i} className={current?.type === "place" && current.p.i === p.i ? "sel" : undefined} style={{ cursor: "pointer" }} onClick={() => choose({ type: "place", p })}
                        tabIndex={0} onKeyDown={(e) => e.key === "Enter" && choose({ type: "place", p })} aria-label={`${t(`pages.distill.places.kind.${p.kind}`, { defaultValue: p.kind })} ${p.page ?? ""}`}>
                        <td><Pill tone={KIND_TONE[p.kind] ?? "idle"}>{t(`pages.distill.places.kind.${p.kind}`, { defaultValue: p.kind })}</Pill></td>
                        <td className="fx-num">{p.page ?? "—"}</td>
                        <td style={{ wordBreak: "break-word" }}>{okS(p.suggestion) && <><Pill tone="ai">{t("pages.distill.fix2.aiSuggestion")}</Pill> </>}{p.kind === "reading" && p.candidates ? `${p.candidates[0]} / ${p.candidates[1]}` : reason(t, p.detail)}</td>
                        <td className="fx-muted fx-tiny">{placeStatus(p)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : review.isLoading ? (
              <div className="fx-muted fx-tiny" role="status"><Spin size="small" /> {t("pages.distill.fix2.looking")}</div>
            ) : file?.state === "below" ? (
              <div className="fx-warnnote">
                {t("pages.distill.fix2.belowNoPlaces", { acc: file.accuracy ?? "—", thr: threshold ?? "—" })}
                {canEdit && (
                  <div className="fx-row fx-wrap" style={{ marginTop: 8 }}>
                    <button className="fx-btn sm" onClick={() => setShowText(true)}>{t("pages.distill.fix2.showText")}</button>
                    <Popconfirm title={t("pages.distill.fix2.acceptOneConfirm")} okText={t("pages.distill.acceptConfirm")} cancelText={t("pages.distill.cancel")} onConfirm={() => acceptOne.mutate()}>
                      <button className="fx-btn sm" disabled={acceptOne.isPending}>{t("pages.distill.fix2.acceptOne")}</button>
                    </Popconfirm>
                  </div>
                )}
              </div>
            ) : (
              <div className="fx-note">{t("pages.distill.fix2.nothing")}</div>
            )}
            <div>
              {canEdit && <><button className="fx-a" onClick={() => { choose(null); setFree(true); setShowText(true); }}>+ {t("pages.distill.fix2.freeTitle")}</button>{" · "}</>}
              <button className="fx-a" aria-expanded={showText} onClick={() => setShowText(!showText)}>{showText ? t("pages.distill.fix2.hideText") : t("pages.distill.fix2.showText")}</button>
              {" · "}
              <Link className="fx-a" to="/settings/corrections">{t("pages.distill.fix.library")}</Link>
            </div>
            {showText && v.files.map((f) => (
              <div key={f.path}>
                {v.files.length > 1 && <div className="fx-tiny fx-muted">{f.path}</div>}
                <pre tabIndex={0} onMouseUp={takeSelection} aria-label={t("pages.distill.fix.result")}
                  style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "40vh", overflow: "auto", margin: 0, padding: 10, fontSize: 12.5, border: "1px solid var(--line)", borderRadius: 6, background: "var(--sunken)" }}>
                  {f.text}
                </pre>
                {f.cut && <div className="fx-tiny fx-muted">{t("pages.distill.fix.cut")}</div>}
              </div>
            ))}
          </div>
          <aside className="fx-fixside" aria-label={t("pages.distill.fix2.detail")}>
            {detail}
            {err && <div className="fx-errnote" role="alert">{err.message}</div>}
          </aside>
        </div>
      )}
      {toast && (
        <div className="fx-toast" role="status">
          <span>{t("pages.distill.fix2.saved", { num: toast.rule.num, count: toast.others.length })}</span>
          {toast.others.length > 0 && <button onClick={() => applyOthers.mutate(toast.rule.id)}>{t("pages.distill.fix.applyOthers", { count: toast.others.length })}</button>}
          <button onClick={() => undoNew.mutate(toast.rule.id)}>{t("pages.distill.fix2.undoShort")}</button>
          <button aria-label={t("pages.distill.dismiss")} onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </Drawer>
  );
}
