import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { TreeCounts, TreeDir, TreeFile, TreeResp, TrustState } from "../types";
import { useI18n } from "../i18n";

/**
 * 侧栏：源文件原目录结构。
 *
 * 职责（对应用户 2026-10-05 的诉求）：
 *  - 目录层级 + 每个目录的状态计数，一眼看出哪块还没审；
 *  - 文件用**颜色**指示状态（不只靠文字），符合行业惯例；
 *  - 可左右拖拽调宽，宽度持久化；
 *  - 展开状态与选中文件持久化，刷新后回到原处；
 *  - 支持「全部展开 / 全部折叠」；
 *  - 支持多选（Ctrl 点选、Shift 连选、勾选框选整目录），配合阈值批量审核。
 */

const STATE_COLOR: Record<TrustState, string> = {
  trusted: "var(--green)",
  need_review: "var(--amber)",
  diff_big: "var(--red)",
  rejected: "var(--text-3)",
  unreviewed: "var(--brand-border)",
};

/** 状态 → 左侧色条，用于「不同状态不同颜色」的快速扫视。 */
const STATE_BAR: Record<TrustState, string> = {
  trusted: "var(--green)",
  need_review: "var(--amber)",
  diff_big: "var(--red)",
  rejected: "var(--text-3)",
  unreviewed: "transparent",
};

const K_WIDTH = "fidelity.tree.width";
const K_OPEN = "fidelity.tree.open";
const K_SEL = "fidelity.tree.sel";

function loadLS<T>(k: string, fallback: T): T {
  try {
    const v = localStorage.getItem(k);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function saveLS(k: string, v: unknown) {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* 隐私模式下忽略 */
  }
}

function DirIcon({ open }: { open: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden>
      <path
        d="M1.5 3.5h4l1.2 1.5H14v7.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      {open && <path d="M2 6.6h12" stroke="currentColor" strokeWidth="1.3" />}
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden>
      <path d="M4 1.5h5l3 3v10H4z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M9 1.5v3h3" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

/** 勾选框：多选批量审核的入口。 */
function Check({
  checked,
  mixed,
  onChange,
  title,
}: {
  checked: boolean;
  mixed?: boolean;
  onChange: () => void;
  title?: string;
}) {
  return (
    <span
      className={`tcheck ${checked ? "on" : ""} ${mixed ? "half" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      title={title}
      role="checkbox"
      aria-checked={mixed ? "mixed" : checked}
      tabIndex={-1}
    >
      {checked || mixed ? "✓" : ""}
    </span>
  );
}

/** 递归收集目录下所有文件的 rel —— 供「整目录选择」使用。 */
function collectFiles(d: TreeDir, out: string[] = []): string[] {
  for (const f of d.files) out.push(f.rel);
  for (const c of d.dirs) collectFiles(c, out);
  return out;
}

function FileRow({
  f,
  sel,
  picked,
  onPick,
  onTogglePick,
}: {
  f: TreeFile;
  sel: string;
  picked: boolean;
  onPick: (rel: string, e: React.MouseEvent) => void;
  onTogglePick: (rel: string) => void;
}) {
  const [t] = useI18n();
  const active = sel === f.rel;
  const score = f.auto_score;
  const cls = score == null ? "none" : score >= 90 ? "good" : score >= 70 ? "mid" : "bad";
  return (
    <div
      className={`trow tree-file ${active ? "sel" : ""} ${picked ? "picked" : ""}`}
      style={{ borderLeftColor: active ? "var(--brand)" : STATE_BAR[f.state] }}
      onClick={(e) => onPick(f.rel, e)}
      title={`${f.rel}\n${f.label}${score != null ? ` · ${score}%` : ""}`}
    >
      <Check checked={picked} onChange={() => onTogglePick(f.rel)} title={t("tree.selectFile")} />
      <span className="ticon">
        <FileIcon />
      </span>
      <span className="tname">{f.name}</span>
      {score != null && (
        <span className="tcount" style={{ color: cls === "good" ? "var(--green)" : cls === "bad" ? "var(--red)" : "var(--amber)" }}>
          {score}
        </span>
      )}
      <span className="tdot" style={{ background: STATE_COLOR[f.state] }} title={f.label} />
    </div>
  );
}

function DirNode({
  d,
  sel,
  picked,
  openSet,
  allOpen,
  depth,
  onToggleOpen,
  onPick,
  onTogglePick,
  onToggleDir,
}: {
  d: TreeDir;
  sel: string;
  picked: Set<string>;
  openSet: Set<string>;
  allOpen: boolean;
  depth: number;
  onToggleOpen: (name: string) => void;
  onPick: (rel: string, e: React.MouseEvent) => void;
  onTogglePick: (rel: string) => void;
  onToggleDir: (d: TreeDir) => void;
}) {
  const open = allOpen || openSet.has(d.name);
  const rels = useMemo(() => collectFiles(d), [d]);
  const pickedCount = useMemo(() => rels.filter((r) => picked.has(r)).length, [rels, picked]);
  const allPicked = rels.length > 0 && pickedCount === rels.length;

  const c: TreeCounts = d.counts;
  const title = `${d.name} · ${c.all}`;

  return (
    <div className="tnode">
      <div
        className="trow dir"
        onClick={() => onToggleOpen(d.name)}
        title={title}
        style={depth === 0 ? { fontWeight: 600 } : undefined}
      >
        <Check
          checked={allPicked}
          mixed={pickedCount > 0 && !allPicked}
          onChange={() => onToggleDir(d)}
          title={`${pickedCount}/${rels.length}`}
        />
        <span className={`twist ${open ? "open" : ""}`}>▶</span>
        <span className="ticon">
          <DirIcon open={open} />
        </span>
        <span className="tname">{d.name}</span>
        <span className="tcount">{c.all}</span>
        <span className="tstatebar">
          {c.unreviewed > 0 && <i style={{ background: "var(--brand-border)" }} title={`${c.unreviewed}`} />}
          {c.trusted > 0 && <i style={{ background: "var(--green)" }} title={`${c.trusted}`} />}
          {c.need_review > 0 && <i style={{ background: "var(--amber)" }} title={`${c.need_review}`} />}
          {c.diff_big > 0 && <i style={{ background: "var(--red)" }} title={`${c.diff_big}`} />}
        </span>
      </div>
      {open && (
        <div className="tchildren">
          {d.dirs.map((x) => (
            <DirNode
              key={x.name}
              d={x}
              sel={sel}
              picked={picked}
              openSet={openSet}
              allOpen={allOpen}
              depth={depth + 1}
              onToggleOpen={onToggleOpen}
              onPick={onPick}
              onTogglePick={onTogglePick}
              onToggleDir={onToggleDir}
            />
          ))}
          {d.files.map((f) => (
            <FileRow
              key={f.rel}
              f={f}
              sel={sel}
              picked={picked.has(f.rel)}
              onPick={onPick}
              onTogglePick={onTogglePick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function FileTree({
  sid,
  sel,
  status,
  onStatus,
  onPick,
  picked,
  onPickedChange,
  threshold,
  onThreshold,
  onBatchPass,
  busy,
}: {
  sid: string;
  sel: string;
  status: TrustState | "";
  onStatus: (s: TrustState | "") => void;
  onPick: (rel: string) => void;
  picked: Set<string>;
  onPickedChange: (s: Set<string>) => void;
  threshold: number;
  onThreshold: (n: number) => void;
  onBatchPass: () => void;
  busy?: boolean;
}) {
  const [t] = useI18n();
  const [tree, setTree] = useState<TreeResp | null>(null);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  /** 失败可重试：之前只能刷新页面，用户体验很差。 */
  const [attempt, setAttempt] = useState(0);

  const [width, setWidth] = useState(() => loadLS<number>(K_WIDTH, 300));
  const [openSet, setOpenSet] = useState<Set<string>>(() => new Set(loadLS<string[]>(K_OPEN, [])));
  const [allOpen, setAllOpen] = useState(false);
  const [lastAnchor, setLastAnchor] = useState<string>("");

  const dragging = useRef(false);

  // 宽度限制：太窄树里名字全看不见，太宽会挤掉对比区
  const clampW = (w: number) => Math.max(200, Math.min(640, w));

  useEffect(() => saveLS(K_WIDTH, width), [width]);
  useEffect(() => saveLS(K_OPEN, Array.from(openSet)), [openSet]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      setWidth(clampW(e.clientX));
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  // 搜索防抖
  useEffect(() => {
    const tmr = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(tmr);
  }, [search]);

  useEffect(() => {
    let alive = true;
    setErr("");
    api
      .tree(sid, status, q)
      .then((x) => alive && setTree(x))
      .catch((e) => alive && setErr(e.message || "network"));
    return () => {
      alive = false;
    };
  }, [sid, status, q, attempt]);

  /** 展开状态持久化后，刷新仍回到同一位置。 */
  const toggleOpen = useCallback((name: string) => {
    setAllOpen(false);
    setOpenSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const togglePick = useCallback(
    (rel: string) => {
      const next = new Set(picked);
      if (next.has(rel)) next.delete(rel);
      else next.add(rel);
      onPickedChange(next);
    },
    [picked, onPickedChange],
  );

  const toggleDir = useCallback(
    (d: TreeDir) => {
      const rels = collectFiles(d);
      const next = new Set(picked);
      const all = rels.every((r) => next.has(r));
      rels.forEach((r) => (all ? next.delete(r) : next.add(r)));
      onPickedChange(next);
    },
    [picked, onPickedChange],
  );

  /** Ctrl = 多选；Shift = 区间连选；普通点击 = 打开。 */
  const handlePick = useCallback(
    (rel: string, e: React.MouseEvent) => {
      if (e.ctrlKey || e.metaKey) {
        togglePick(rel);
        setLastAnchor(rel);
        return;
      }
      if (e.shiftKey && lastAnchor) {
        const flat: string[] = [];
        const walk = (n: TreeDir) => {
          n.files.forEach((f) => flat.push(f.rel));
          n.dirs.forEach(walk);
        };
        if (tree) walk(tree);
        const a = flat.indexOf(lastAnchor);
      const b = flat.indexOf(rel);
        if (a >= 0 && b >= 0) {
          const [lo, hi] = a < b ? [a, b] : [b, a];
          const next = new Set(picked);
          for (let i = lo; i <= hi; i++) next.add(flat[i]);
          onPickedChange(next);
        }
        return;
      }
      setLastAnchor(rel);
      onPick(rel);
    },
    [lastAnchor, picked, onPickedChange, onPick, tree],
  );

  const counts = tree?.counts;
  const FILTERS: { key: TrustState | ""; label: string }[] = [
    { key: "", label: t("filter.all") },
    { key: "unreviewed", label: t("filter.unreviewed") },
    { key: "need_review", label: t("filter.need_review") },
    { key: "trusted", label: t("filter.trusted") },
    { key: "diff_big", label: t("filter.diff_big") },
    { key: "rejected", label: t("filter.rejected") },
  ];

  return (
    <aside className="tree" style={{ width }}>
      <div className="tree-head">
        <div className="tree-search">
          <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden>
            <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input type="search" value={search} placeholder={t("tree.search")} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="tree-filters">
          {FILTERS.map((f) => (
            <button key={f.key || "all"} className={`chip ${status === f.key ? "on" : ""}`} onClick={() => onStatus(f.key)}>
              {f.key !== "" && <i style={{ background: STATE_COLOR[f.key] }} />}
              {f.label}
              {counts && f.key !== "" && counts[f.key] > 0 && <span className="c">{counts[f.key]}</span>}
            </button>
          ))}
        </div>
        <div className="tree-tools">
          <button className="ghost sm" onClick={() => setAllOpen((v) => !v)} title={allOpen ? t("act.collapseAll") : t("act.expandAll")}>
            {allOpen ? t("act.collapseAll") : t("act.expandAll")}
          </button>
          {picked.size > 0 && (
            <>
              <span className="dim num nowrap">
                {t("tree.selected", { n: picked.size })}
              </span>
              <button className="ghost sm" onClick={() => onPickedChange(new Set())}>
                {t("act.cancel")}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="tree-body">
        {err && (
          <div className="empty">
            <div>{t("tree.failed")}：{err}</div>
            <button className="ghost sm" onClick={() => setAttempt((a) => a + 1)}>
              {t("tree.retry")}
            </button>
          </div>
        )}
        {!err && !tree && (
          <div className="empty">
            <span className="spin" /> {t("tree.loading")}
          </div>
        )}
        {tree && tree.dirs.length === 0 && tree.files.length === 0 && <div className="empty">{t("tree.empty")}</div>}
        {tree &&
          tree.dirs.map((d) => (
            <DirNode
              key={d.name}
              d={d}
              sel={sel}
              picked={picked}
              openSet={openSet}
              allOpen={allOpen}
              depth={0}
              onToggleOpen={toggleOpen}
              onPick={handlePick}
              onTogglePick={togglePick}
              onToggleDir={toggleDir}
            />
          ))}
        {tree &&
          tree.files.map((f) => (
            <FileRow
              key={f.rel}
              f={f}
              sel={sel}
              picked={picked.has(f.rel)}
              onPick={handlePick}
              onTogglePick={togglePick}
            />
          ))}
      </div>

      {/* 批量审核：阈值可调 + 多选批量打标 */}
      <div className="tree-foot">
        <label className="thresh" title={t("tree.threshold")}>
          <span className="nowrap">{t("tree.threshold")}</span>
          <input
            type="range"
            min={50}
            max={100}
            step={1}
            value={threshold}
            onChange={(e) => onThreshold(parseInt(e.target.value, 10))}
          />
          <b className="num">{threshold}%</b>
        </label>
        <button className="primary sm" disabled={!picked.size || busy} onClick={onBatchPass}>
          {t("tree.batchPass")}
          {picked.size ? ` (${picked.size})` : ""}
        </button>
      </div>

      {/* 拖拽调宽 */}
      <div className="tree-resizer" onMouseDown={startDrag} role="separator" aria-orientation="vertical" />
    </aside>
  );
}
