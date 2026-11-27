import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { StageCell, type RunLive } from "./RunProgress";
import { StateHelp } from "./StateHelp";
import { Empty, Modal, Table } from "antd";
import { api, json } from "../net/client";
import { Bar, CellTip, ResizableTh, Seg } from "./ui";

export type FileState = "pending" | "processing" | "ok" | "below" | "unprocessable" | "skipped" | "publishing" | "published";
export const STATES: FileState[] = ["pending", "processing", "ok", "below", "unprocessable", "skipped", "publishing", "published"];

export interface FileRow {
  rel: string;
  name: string;
  kind: string | null;
  size: number | null;
  state: FileState;
  accuracy: number | null;
  diffs: number;
  number_diffs: number;
  /** number differences nobody has confirmed yet: with the guard on these hold the file below whatever the threshold */
  numbers_open?: number;
  reason: string | null;
  detail: string | null;
  pages: number | null;
  corrected?: number;
  checks?: number;
  /** another copy of the same edition that is the one published (an unlocked copy, a searchable copy…) */
  covered_by?: string | null;
  /** which standard and edition the file is, and whether a newer edition in this room replaces it */
  edition?: Edition | null;
}

export interface Edition {
  designation: string;
  amendment: number | null;
  amendment_year?: string;
  consolidated?: boolean;
  status: "current" | "superseded" | "";
  superseded_by: string;
  copy_of: string | null;
  copies: number;
  /** clauses of the building code that call up this very edition */
  called_up_by?: string;
  /** a newer edition the building code calls up that this library does not hold */
  newer_edition?: string;
}

type T = (k: string, o?: Record<string, unknown>) => string;

/** The edition in words, with what to know about it (the cell's tooltip). */
export function editionText(e: Edition | null | undefined, t: T): string {
  if (!e) return "";
  const what = e.designation + (e.amendment != null ? ` ${t("pages.distill.edition.amd", { n: e.amendment })}` : "") + (e.consolidated ? ` ${t("pages.distill.edition.consolidated")}` : "");
  return [
    what,
    e.status === "superseded" ? t("pages.distill.edition.supersededBy", { by: e.superseded_by }) : e.status === "current" ? t("pages.distill.edition.currentLong") : "",
    e.called_up_by ? t("pages.distill.edition.calledUp", { clauses: e.called_up_by }) : "",
    e.newer_edition ? t("pages.distill.edition.newerLong", { ed: e.newer_edition }) : "",
  ].filter(Boolean).join("\n");
}

export function EditionCell({ e, plain }: { e?: Edition | null; plain?: boolean }) {
  const { t } = useTranslation();
  if (!e) return <span className="fx-muted">—</span>;
  const what = e.designation + (e.amendment != null ? ` ${t("pages.distill.edition.amd", { n: e.amendment })}` : "") + (e.consolidated ? ` ${t("pages.distill.edition.consolidated")}` : "");
  return (
    <span className="fx-row" style={{ gap: 6, minWidth: 0, flexWrap: "nowrap" }} title={plain ? undefined : editionText(e, t)}>
      <span className="fx-tiny" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{what}</span>
      {e.called_up_by && <span className="fx-pill ok fx-tiny" style={{ flex: "none" }}>{t("pages.distill.edition.code")}</span>}
      {e.status === "superseded" && !e.called_up_by && <span className="fx-pill warn fx-tiny" style={{ flex: "none" }}>{t("pages.distill.edition.old")}</span>}
      {e.newer_edition && <span className="fx-pill warn fx-tiny" style={{ flex: "none" }}>{t("pages.distill.edition.newer")}</span>}
    </span>
  );
}

type Counts = Record<FileState, number> & { total: number };
const zero = (): Counts => ({ total: 0, pending: 0, processing: 0, ok: 0, below: 0, unprocessable: 0, skipped: 0, publishing: 0, published: 0 });

interface Node {
  key: string;
  name: string;
  depth: number;
  folder: boolean;
  file?: FileRow;
  counts?: Counts;
  kids?: Node[];
}

/** The folder structure of the source, built from the file paths. Every folder carries the roll-up of everything below it. */
export function buildTree(files: FileRow[]): Node {
  const root: Node = { key: "", name: "", depth: -1, folder: true, counts: zero(), kids: [] };
  const index = new Map<string, Node>([["", root]]);
  for (const f of files) {
    const parts = f.rel.split("/").filter(Boolean);
    let parent = root;
    let path = "";
    const chain: Node[] = [root];
    for (let i = 0; i < parts.length - 1; i++) {
      path += "/" + parts[i];
      let n = index.get(path);
      if (!n) {
        n = { key: path, name: parts[i], depth: i, folder: true, counts: zero(), kids: [] };
        index.set(path, n);
        parent.kids!.push(n);
      }
      parent = n;
      chain.push(n);
    }
    parent.kids!.push({ key: f.rel, name: parts[parts.length - 1] ?? f.rel, depth: parts.length - 1, folder: false, file: f });
    for (const n of chain) {
      n.counts!.total += 1;
      n.counts![f.state] += 1;
    }
  }
  const sort = (n: Node) => {
    n.kids?.sort((a, b) => (a.folder === b.folder ? a.name.localeCompare(b.name, undefined, { numeric: true }) : a.folder ? -1 : 1));
    n.kids?.forEach(sort);
  };
  sort(root);
  return root;
}

/** The rows that are visible: a folder's children are listed only when it is expanded. */
export function flatten(root: Node, open: Set<string>): Node[] {
  const out: Node[] = [];
  const walk = (n: Node) => {
    for (const k of n.kids ?? []) {
      out.push(k);
      if (k.folder && open.has(k.key)) walk(k);
    }
  };
  walk(root);
  return out;
}

const TONE: Record<FileState, string> = {
  pending: "idle", processing: "run", ok: "ok", below: "warn", unprocessable: "bad", skipped: "idle", publishing: "run", published: "ok",
};
const COLOR: Record<FileState, string> = {
  ok: "var(--ok)", published: "var(--ok)", below: "var(--warn)", processing: "var(--run)", publishing: "var(--run)", unprocessable: "var(--bad)", skipped: "var(--idle)", pending: "var(--idle-soft)",
};

/** The state of one file, in the design's words: a percentage when there is a result, a reason when there is none. */
export function StateTag({ state, accuracy, detail, title }: { state: FileState; accuracy?: number | null; detail?: string; title?: string }) {
  const { t } = useTranslation();
  const pct = (state === "ok" || state === "below") && accuracy != null ? ` ${accuracy}%` : "";
  return (
    <span className={`fx-pill p-${TONE[state]}`} title={title}>
      {t(`pages.distill.state.${state}`)}{pct}
      {detail ? ` · ${detail}` : ""}
    </span>
  );
}

const storeKey = (room: string) => `fidelity.distill.open.${room}`;
const prefKey = "fidelity.distill.view";

function loadOpen(room: string): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(storeKey(room)) || "[]") as string[]);
  } catch {
    return new Set();
  }
}
const widthKey = "fidelity.distill.colwidths";
const DEFAULT_WIDTHS: Record<string, number> = { name: 340, edition: 240, size: 100, state: 240, accuracy: 150 };
function loadWidths(): Record<string, number> {
  try {
    return { ...DEFAULT_WIDTHS, ...(JSON.parse(localStorage.getItem(widthKey) || "{}") as Record<string, number>) };
  } catch {
    return { ...DEFAULT_WIDTHS };
  }
}
function loadPref(): { flat: boolean; compact: boolean } {
  try {
    return { flat: false, compact: true, ...(JSON.parse(localStorage.getItem(prefKey) || "{}") as object) };
  } catch {
    return { flat: false, compact: true };
  }
}

/** All files of a room, in pages of 1000. */
export async function loadFiles(room: string, state: string, q: string): Promise<FileRow[]> {
  const out: FileRow[] = [];
  for (let offset = 0; offset < 50000; offset += 1000) {
    const qs = new URLSearchParams({ offset: String(offset), limit: "1000" });
    if (state) qs.set("state", state);
    if (q) qs.set("q", q);
    const r = await api<{ total: number; files: FileRow[] }>(`/rooms/${room}/files?${qs}`);
    out.push(...r.files);
    if (out.length >= r.total) break;
  }
  return out;
}

const LEGEND: FileState[] = ["ok", "published", "below", "processing", "publishing", "unprocessable", "skipped", "pending"];

export function RoomFiles({
  roomId, live, counts, filter, onFilter, focusFile, onCompare, onFix, onReview, onRetry, canEdit = false, progress, threshold, numberGuard,
}: {
  roomId: string;
  threshold?: number;
  numberGuard?: boolean;
  live: boolean;
  /** the room's run as it goes: which files are in which step, which wait */
  progress?: RunLive;
  counts?: Counts & { finished?: number; rate?: number };
  filter?: string;
  onFilter?: (s: string) => void;
  focusFile?: string | null;
  onCompare?: (rel: string) => void;
  onFix?: (rel: string) => void;
  /** a file below the threshold: "Review" opens the page-by-page compare & review (falls back to onFix) */
  onReview?: (rel: string) => void;
  onRetry?: () => void;
  canEdit?: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [ownFilter, setOwnFilter] = useState("");
  const state = filter ?? ownFilter;
  const setState = onFilter ?? setOwnFilter;
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => loadOpen(roomId));
  const [pref, setPref] = useState(loadPref);
  const [widths, setWidths] = useState(loadWidths);       // dragged column widths, remembered in this browser
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const search = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const all = useQuery({ queryKey: ["room-files", roomId, "", ""], queryFn: () => loadFiles(roomId, "", ""), refetchInterval: live ? 3000 : false });
  const files = useQuery({
    queryKey: ["room-files", roomId, state, q],
    queryFn: () => loadFiles(roomId, state, q),
    enabled: !!state || !!q,
    refetchInterval: live ? 3000 : false,
  });
  const data = state || q ? files.data : all.data;
  const loading = state || q ? files.isLoading : all.isLoading;
  const tree = useMemo(() => buildTree(data ?? []), [data]);
  const allFiles = useMemo(() => all.data ?? [], [all.data]);
  const tot: Counts = useMemo(() => {
    const c = zero();
    for (const f of allFiles) {
      c.total += 1;
      c[f.state] += 1;
    }
    return c;
  }, [allFiles]);
  // searching shows where the hits are: every folder above a hit opens
  const effective = useMemo(() => {
    const s = new Set(open);
    if (q) {
      const walk = (n: Node) => {
        if (n.folder && n.key) s.add(n.key);
        n.kids?.forEach(walk);
      };
      walk(tree);
    }
    return s;
  }, [open, q, tree]);
  const rows = useMemo(() => {
    if (pref.flat) return (data ?? []).slice().sort((a, b) => a.rel.localeCompare(b.rel, undefined, { numeric: true })).map((f) => ({ key: f.rel, name: f.rel.replace(/^\//, "").split("/").join(" / "), depth: 0, folder: false, file: f }) as Node);
    return flatten(tree, effective);
  }, [tree, effective, pref.flat, data]);

  useEffect(() => {
    try {
      sessionStorage.setItem(storeKey(roomId), JSON.stringify([...open]));
    } catch {
      /* storage unavailable: the tree still works, it just forgets on reload */
    }
  }, [open, roomId]);
  useEffect(() => {
    try {
      localStorage.setItem(prefKey, JSON.stringify(pref));
    } catch {
      /* per-viewer convenience only */
    }
  }, [pref]);
  useEffect(() => {
    try {
      localStorage.setItem(widthKey, JSON.stringify(widths));
    } catch {
      /* per-viewer convenience only */
    }
  }, [widths]);
  // a column whose header edge can be dragged; `label` names the handle for screen readers
  const sized = (key: string, label: string) => ({
    width: widths[key],
    onHeaderCell: () => ({ width: widths[key], label, onResize: (w: number) => setWidths((p) => ({ ...p, [key]: w })) }) as React.HTMLAttributes<HTMLElement>,
  });
  useEffect(() => setSel(new Set()), [state, q]);
  // "/" focuses the file search of the open room
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /input|textarea|select/i.test((e.target as HTMLElement)?.tagName ?? "");
      if (e.key === "/" && !typing && box.current?.offsetParent) {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const reveal = (rel: string) => {
    const parts = rel.split("/").filter(Boolean);
    setOpen((p) => {
      const n = new Set(p);
      let path = "";
      for (const x of parts.slice(0, -1)) {
        path += "/" + x;
        n.add(path);
      }
      return n;
    });
    setFlash(rel);
    setTimeout(() => setFlash(null), 2500);
  };
  // a link to a file: open its folders, scroll to it and highlight it for two seconds
  useEffect(() => {
    if (focusFile && allFiles.length) reveal(focusFile);
  }, [focusFile, allFiles.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (k: string) =>
    setOpen((p) => {
      const n = new Set(p);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const folders = (pred: (n: Node) => boolean) => {
    const s = new Set<string>();
    const walk = (n: Node): boolean => {
      let any = false;
      for (const k of n.kids ?? []) if (k.folder && walk(k)) any = true;
      const mine = n.folder && n.key !== "" && pred(n);
      if (mine || any) s.add(n.key);
      return mine || any;
    };
    walk(tree);
    s.delete("");
    return s;
  };
  const relsUnder = (n: Node): string[] => (n.folder ? (n.kids ?? []).flatMap(relsUnder) : [n.key]);
  const filesInView = (data ?? []).map((f) => f.rel);
  const allSelected = filesInView.length > 0 && filesInView.every((r) => sel.has(r));
  const selRows = allFiles.filter((f) => sel.has(f.rel));
  const selAcceptable = selRows.filter((f) => f.state === "ok" || f.state === "below");
  const selBelow = selAcceptable.filter((f) => f.state === "below").length;
  const accept = useMutation({
    mutationFn: () => api(`/rooms/${roomId}/accept`, json({ rels: selAcceptable.map((f) => f.rel), force: selBelow > 0 })),
    onSuccess: () => {
      setConfirm(false);
      setSel(new Set());
      for (const k of ["rooms", "room-files", "accept-preview", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
  // a second published copy of an edition: taken out of the output folder (archived there, undoable)
  const [toWithdraw, setToWithdraw] = useState<FileRow | null>(null);
  const withdraw = useMutation({
    mutationFn: (rel: string) => api(`/rooms/${roomId}/withdraw`, json({ rels: [rel] })),
    onSuccess: () => {
      setToWithdraw(null);
      for (const k of ["rooms", "queue", "room-files", "accept-preview", "room-editions", "notifications"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
  const processing = allFiles.find((f) => f.state === "processing");
  const rowH = pref.compact ? 34 : 40;
  const height = Math.min(360, Math.max(rowH * 3, rows.length * rowH + 2));
  const flashIndex = flash ? rows.findIndex((r) => r.key === flash) : -1;

  const action = (f: FileRow, name: string) => {
    // a skipped file has no result of its own: point to the file that covers it (the original, or the unlocked copy)
    if (f.state === "skipped") {
      const to = f.covered_by || (f.reason === "duplicate" ? (f.detail || "").replace(/^same content as /, "") : "");
      return to && allFiles.some((x) => x.rel === to)
        ? <button className="fx-a" aria-label={t("pages.distill.showOriginalOf", { name })} onClick={() => reveal(to)}>{t("pages.distill.showOriginal")}</button>
        : null;
    }
    // retrying helps only when the cause can go away (the network, memory, a change); not a copy-protected file
    if (f.state === "unprocessable" && ["protected", "unsupported", "unreadable", "duplicate"].includes(f.reason ?? "")) return null;
    if (f.state === "unprocessable") return onRetry ? <button className="fx-a" onClick={onRetry} aria-label={t("pages.distill.retryFile", { name })}>{t("pages.distill.retry")}</button> : null;
    if (f.state === "pending" || f.state === "processing") return null;
    return (
      <span style={{ whiteSpace: "nowrap" }}>
        {onFix && (
          <button className="fx-a" aria-label={t(f.state === "below" ? "pages.distill.reviewFile" : "pages.distill.fixFile", { name })} onClick={() => (f.state === "below" && onReview ? onReview(f.rel) : onFix(f.rel))}>
            {f.state === "below" ? t("pages.distill.review") : t("pages.distill.view")}
          </button>
        )}
        {onCompare && (f.state === "ok" || f.state === "below" || f.state === "published") && (
          <>
            {" · "}
            <button className="fx-a" aria-label={t("pages.distill.compareFile", { name })} onClick={() => onCompare(f.rel)}>{t("pages.distill.compare")}</button>
          </>
        )}
        {canEdit && f.state === "published" && f.covered_by && allFiles.some((x) => x.rel === f.covered_by && x.state === "published") && (
          <>
            {" · "}
            <button className="fx-a" aria-label={t("pages.distill.edition.withdrawFile", { name })} onClick={() => setToWithdraw(f)}>{t("pages.distill.edition.withdraw")}</button>
          </>
        )}
      </span>
    );
  };

  const c = counts ?? tot;
  return (
    <div className="fx-stack" style={{ gap: 10 }} ref={box}>
      {tot.total > 0 && (
        <div>
          <div className="fx-dist" role="img" aria-label={LEGEND.filter((s) => tot[s]).map((s) => `${t(`pages.distill.state.${s}`)} ${tot[s]}`).join(", ")}>
            {LEGEND.filter((s) => s !== "pending" && tot[s]).map((s) => <i key={s} style={{ width: `${(100 * tot[s]) / tot.total}%`, background: COLOR[s] }} />)}
          </div>
          <div className="fx-legend" style={{ marginTop: 7 }}>
            {LEGEND.filter((s) => tot[s]).map((s) => (
              <button key={s} aria-pressed={state === s} onClick={() => setState(state === s ? "" : s)}>
                <b style={{ background: COLOR[s], border: s === "pending" ? "1px solid var(--line)" : undefined }} />
                {t(`pages.distill.state.${s}`)} {tot[s]}
              </button>
            ))}
            <span className="fx-muted fx-tiny">{t("pages.distill.legendHint")}</span>
            <StateHelp />
          </div>
        </div>
      )}
      <div className="fx-row fx-wrap" style={{ rowGap: 8 }}>
        <label className="fx-field sm" style={{ minWidth: 220 }}>
          <input ref={search} value={typed} onChange={(e) => setTyped(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setQ(typed.trim())} onBlur={() => setQ(typed.trim())}
            placeholder={t("pages.distill.searchFileNames")} aria-label={t("pages.distill.searchFiles")} />
          {typed ? <button className="fx-iconbtn" aria-label={t("pages.distill.clearSearch")} onClick={() => { setTyped(""); setQ(""); }}>✕</button> : <span className="fx-kbd">/</span>}
        </label>
        <div className="fx-chips" role="group" aria-label={t("pages.distill.filterByState")}>
          <button className={`fx-chip${!state ? " on" : ""}`} aria-pressed={!state} onClick={() => setState("")}>{t("pages.distill.all")} {tot.total}</button>
          {(["below", "unprocessable", "ok"] as FileState[]).filter((s) => tot[s]).map((s) => (
            <button key={s} className={`fx-chip${state === s ? " on" : ""}`} aria-pressed={state === s} onClick={() => setState(state === s ? "" : s)}>{t(`pages.distill.state.${s}`)} {tot[s]}</button>
          ))}
        </div>
        <span className="fx-sp" />
        <Seg tiny label={t("pages.distill.viewAs")} value={pref.flat ? "flat" : "tree"} onChange={(v) => setPref({ ...pref, flat: v === "flat" })}
          options={[{ value: "tree", label: t("pages.distill.tree") }, { value: "flat", label: t("pages.distill.flat") }]} />
        {!pref.flat && (
          <>
            <button className="fx-btn sm" onClick={() => setOpen(folders(() => true))}>{t("pages.distill.expandAll")}</button>
            <button className="fx-btn sm" onClick={() => setOpen(new Set())}>{t("pages.distill.collapseAll")}</button>
            <button className="fx-btn sm" onClick={() => setOpen(folders((n) => !!n.counts && (n.counts.below > 0 || n.counts.unprocessable > 0)))}>{t("pages.distill.expandProblems")}</button>
          </>
        )}
        <Seg tiny label={t("pages.distill.density")} value={pref.compact ? "compact" : "standard"} onChange={(v) => setPref({ ...pref, compact: v === "compact" })}
          options={[{ value: "standard", label: t("pages.distill.standard") }, { value: "compact", label: t("pages.distill.compact") }]} />
        {processing && <button className="fx-btn sm" onClick={() => reveal(processing.rel)}>{t("pages.distill.jumpProcessing")}</button>}
      </div>
      {canEdit && sel.size > 0 && (
        <div className="fx-row fx-note fx-wrap" style={{ justifyContent: "space-between" }}>
          <span>{t("pages.distill.selected", { count: sel.size })}</span>
          <span className="fx-row fx-wrap">
            {!allSelected && filesInView.length > sel.size && (
              <button className="fx-a" onClick={() => setSel(new Set(filesInView))}>{t("pages.distill.selectAllMatching", { count: filesInView.length })}</button>
            )}
            <button className="fx-a" onClick={() => setSel(new Set())}>{t("pages.distill.clear")}</button>
            <button className="fx-btn sm pri" disabled={!selAcceptable.length} onClick={() => setConfirm(true)}>{t("pages.distill.acceptSelected", { count: selAcceptable.length })}</button>
          </span>
        </div>
      )}
      {(files.isError || all.isError) && <div className="fx-errnote" role="alert">{((files.error || all.error) as Error).message}</div>}
      {!loading && !rows.length ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={tot.total === 0 && !q && !state ? t("pages.distill.noFilesYet") : t("pages.distill.noMatch")} />
      ) : (
        <div className="fx-vlist fx-files">
          <Table<Node>
            size="small"
            virtual
            pagination={false}
            rowKey="key"
            loading={loading}
            dataSource={rows}
            scroll={{ x: Math.max(820, Object.values(widths).reduce((a, b) => a + b, 0) + (canEdit ? 34 : 0) + 120), y: height }}
            components={{ header: { cell: ResizableTh } }}
            aria-label={t("pages.distill.files")}
            rowClassName={(n, i) => [n.folder ? "fx-folder" : "", i === flashIndex ? "fx-flash" : "", pref.compact ? "fx-compact" : ""].join(" ")}
            columns={[
              ...(canEdit
                ? [{
                    title: (
                      <input type="checkbox" className="fx-cb" aria-label={t("pages.distill.selectAll")} checked={allSelected}
                        onChange={(e) => setSel(e.target.checked ? new Set(filesInView) : new Set())} />
                    ),
                    width: 34,
                    render: (_: unknown, n: Node) => {
                      const rels = relsUnder(n);
                      const on = rels.length > 0 && rels.every((r) => sel.has(r));
                      return (
                        <input type="checkbox" className="fx-cb" checked={on} aria-label={t("pages.distill.selectItem", { name: n.name })}
                          onChange={(e) => setSel((p) => {
                            const s = new Set(p);
                            rels.forEach((r) => (e.target.checked ? s.add(r) : s.delete(r)));
                            return s;
                          })} />
                      );
                    },
                  }]
                : []),
              {
                title: t("pages.distill.colName"),
                ...sized("name", t("pages.distill.colName")),
                render: (_: unknown, n: Node) =>
                  n.folder ? (
                    <CellTip text={n.key}>
                      <span style={{ paddingLeft: n.depth * 18, display: "inline-flex", alignItems: "center", gap: 2 }}>
                        <button className="fx-caret" aria-expanded={effective.has(n.key)} aria-label={t(effective.has(n.key) ? "pages.distill.collapse" : "pages.distill.expand", { name: n.name })} onClick={() => toggle(n.key)}>
                          {effective.has(n.key) ? "▾" : "▸"}
                        </button>
                        <b>{n.name}</b>
                      </span>
                    </CellTip>
                  ) : (
                    <CellTip text={n.file!.rel}>
                      <span style={{ paddingLeft: pref.flat ? 0 : n.depth * 18 + 18 }}>{n.name}</span>
                    </CellTip>
                  ),
              },
              {
                title: t("pages.distill.colEdition"),
                ...sized("edition", t("pages.distill.colEdition")),
                render: (_: unknown, n: Node) => (n.folder ? null : (
                  <CellTip text={editionText(n.file!.edition, t)}><EditionCell e={n.file!.edition} plain /></CellTip>
                )),
              },
              {
                title: t("pages.distill.colSize"),
                ...sized("size", t("pages.distill.colSize")),
                render: (_: unknown, n: Node) => {
                  const s = n.folder ? t("pages.distill.fileCount", { count: n.counts!.total }) : n.file!.pages ? t("pages.distill.pageCount", { count: n.file!.pages }) : "";
                  return <CellTip text={s}><span className="fx-num fx-muted">{s || "—"}</span></CellTip>;
                },
              },
              {
                title: t("pages.distill.colState"),
                ...sized("state", t("pages.distill.colState")),
                render: (_: unknown, n: Node) => {
                  if (n.folder) {
                    const k = n.counts!;
                    const parts = (["ok", "published", "below", "unprocessable", "skipped", "processing", "publishing"] as FileState[]).filter((s) => k[s]).map((s) => `${t(`pages.distill.state.${s}`)} ${k[s]}`);
                    const s = parts.join(" · ") || t("pages.distill.notStarted");
                    return <CellTip text={s}><span className="fx-tiny fx-muted">{s}</span></CellTip>;
                  }
                  const f = n.file!;
                  const act = progress?.active?.[f.rel];
                  const qi = progress?.queued ? progress.queued.indexOf(f.rel) : -1;
                  if (act || (qi >= 0 && (f.state === "pending" || f.state === "processing"))) return <StageCell a={act} queuedAt={act ? undefined : qi} />;
                  const base = (p?: string | null) => (p || "").split("/").pop() || "";
                  // a skipped file names the file that covers it: the original of a duplicate, or the unlocked copy
                  const detail = f.state === "skipped" && f.covered_by ? t("pages.distill.coveredBy", { name: base(f.covered_by) })
                    : f.state === "published" && f.covered_by ? t("pages.distill.edition.alsoPublished", { name: base(f.covered_by) })
                    : f.state === "skipped" && f.reason === "duplicate" ? t("pages.distill.dupOf", { name: base((f.detail || "").replace(/^same content as /, "")) })
                    : f.state === "unprocessable" && f.reason ? t(`pages.distill.reason.${f.reason}`, { defaultValue: f.reason })
                    : f.state === "below" && f.checks ? t("pages.distill.ruleChecks", { count: f.checks })
                    // why a file is below, in words: the threshold alone, or number differences the threshold cannot release
                    : f.state === "below" && numberGuard && (f.numbers_open ?? 0) > 0 && threshold != null && f.accuracy != null && f.accuracy >= threshold
                      ? t("pages.distill.numbersHold", { count: f.numbers_open })
                    : f.state === "below" && threshold != null && f.accuracy != null && f.accuracy < threshold
                      ? t("pages.distill.underThreshold", { thr: threshold })
                    : f.state === "below" && f.diffs ? t("pages.distill.diffs", { count: f.diffs }) : undefined;
                  const autoFixed = !f.checks && !!f.corrected ? t("pages.distill.autoFixed", { count: f.corrected }) : "";
                  const tip = [
                    `${t(`pages.distill.state.${f.state}`)}${detail ? ` · ${detail}` : ""}`,
                    f.reason ? t(`pages.distill.reasonLong.${f.state === "skipped" && f.covered_by ? "covered" : f.reason}`, { defaultValue: "" }) : "",
                    autoFixed,
                  ].filter(Boolean).join("\n");
                  return (
                    <CellTip text={tip}>
                      <span className="fx-row" style={{ gap: 6, minWidth: 0, maxWidth: "100%", flexWrap: "nowrap" }}>
                        <StateTag state={f.state} detail={detail} />
                        {autoFixed && <span className="fx-tiny fx-muted">{autoFixed}</span>}
                      </span>
                    </CellTip>
                  );
                },
              },
              {
                title: t("pages.distill.colAccuracy"),
                ...sized("accuracy", t("pages.distill.colAccuracy")),
                render: (_: unknown, n: Node) => {
                  if (n.folder) {
                    const k = n.counts!;
                    const pct = k.total ? Math.round((100 * (k.total - k.pending - k.processing)) / k.total) : 0;
                    return (
                      <CellTip text={t("pages.distill.folderProgress", { name: n.name }) + `: ${pct}%`}>
                        <span className="fx-row" style={{ gap: 6 }}>
                          <Bar pct={pct} width={70} label={t("pages.distill.folderProgress", { name: n.name })} />
                          <span className="fx-num fx-tiny">{pct}%</span>
                        </span>
                      </CellTip>
                    );
                  }
                  const a = n.file!.accuracy;
                  return a == null ? <span className="fx-muted">—</span> : <CellTip text={`${t("pages.distill.colAccuracy")}: ${a}%`}><b className="fx-num">{a}%</b></CellTip>;
                },
              },
              {
                title: <span className="sr-only">{t("pages.distill.colActions")}</span>,
                width: 120,
                render: (_: unknown, n: Node) => (n.folder ? null : action(n.file!, n.name)),
              },
            ]}
          />
        </div>
      )}
      <div className="fx-row fx-tiny fx-muted">
        <span>{t("pages.distill.showing", { n: rows.length, total: c.total })}</span>
        <span className="fx-sp" />
        <span>{t("pages.distill.keysHint")}</span>
      </div>
      <Modal
        open={!!toWithdraw}
        onCancel={() => setToWithdraw(null)}
        title={t("pages.distill.edition.withdrawTitle")}
        width={440}
        footer={[
          <button key="c" className="fx-btn" onClick={() => setToWithdraw(null)}>{t("pages.distill.cancel")}</button>,
          <button key="ok" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={withdraw.isPending} onClick={() => toWithdraw && withdraw.mutate(toWithdraw.rel)}>{t("pages.distill.edition.withdraw")}</button>,
        ]}
      >
        {toWithdraw && (
          <div className="fx-stack fx-tiny" style={{ gap: 8 }}>
            <div>{t("pages.distill.edition.withdrawBody", { name: toWithdraw.rel.split("/").pop(), keep: (toWithdraw.covered_by || "").split("/").pop() })}</div>
            {withdraw.error && <div className="fx-errnote" role="alert">{(withdraw.error as Error).message}</div>}
          </div>
        )}
      </Modal>
      <Modal
        open={confirm}
        onCancel={() => setConfirm(false)}
        title={t("pages.distill.acceptTitle", { count: selAcceptable.length })}
        width={420}
        footer={[
          <button key="c" className="fx-btn" onClick={() => setConfirm(false)}>{t("pages.distill.cancel")}</button>,
          <button key="ok" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={accept.isPending} onClick={() => accept.mutate()}>{t("pages.distill.acceptConfirm")}</button>,
        ]}
      >
        <div className="fx-stack" style={{ gap: 8 }}>
          {selBelow > 0 && <div className="fx-warnnote">{t("pages.distill.forceNote", { count: selBelow })}</div>}
          {selRows.length > selAcceptable.length && <div className="fx-tiny fx-muted">{t("pages.distill.notAcceptable", { count: selRows.length - selAcceptable.length })}</div>}
          <div className="fx-tiny fx-muted">{t("pages.distill.rollbackHint")}</div>
          {accept.error && <div className="fx-errnote">{(accept.error as Error).message}</div>}
        </div>
      </Modal>
    </div>
  );
}
