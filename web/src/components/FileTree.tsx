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

/**
 * 展开状态的数据结构（2026-10-05 重写「全部展开/折叠」）。
 *
 * ⚠️ 之前用 `d.name`（目录**名**）当 key，是个真实缺陷：
 * 实测本库 1634 个节点里有 **12 组同名目录**（`SS` 13 次、`DWG` 12 次、`RFA` 9 次…），
 * 用 name 当 key 意味着展开一个 `SS` 会连带展开另外 12 个 `SS`，
 * 用户看到的就是「点了没反应 / 乱跳」。
 * 现在统一用 `父路径/目录名` 作为唯一 key。
 */
export type OpenMap = Record<string, boolean>;

/** 拼出目录的唯一路径 key。根节点传 ""，其直接子目录 key 就是 "/名称"。 */
function dirKey(parentKey: string, name: string): string {
  return parentKey + "/" + name;
}

/** 一行扁平的树节点：目录或文件。虚拟滚动渲染的就是这个数组。 */
type FlatRow =
  | { kind: "dir"; key: string; d: TreeDir; depth: number }
  | { kind: "file"; f: TreeFile; depth: number };

/**
 * 把树按展开状态压平成「可见行」数组。
 *
 * 为什么要压平：全展开会一次性渲染 1634 个节点、11 层深度，
 * 递归 DOM 会让浏览器明显卡顿。压平后配合虚拟滚动只渲染视口内的行。
 * 顺带天然支持了「全部展开 / 全部折叠」—— 只是 openMap 的两种取值。
 */
function flattenTree(root: TreeDir, openMap: OpenMap): FlatRow[] {
  const out: FlatRow[] = [];
  const walk = (d: TreeDir, key: string, depth: number) => {
    for (const c of d.dirs) {
      const k = dirKey(key, c.name);
      out.push({ kind: "dir", key: k, d: c, depth });
      if (openMap[k]) walk(c, k, depth + 1);
    }
    for (const f of d.files) out.push({ kind: "file", f, depth });
  };
  walk(root, "", 0);
  return out;
}

/** 收集所有目录的 key —— 「全部展开」用。 */
function collectDirKeys(d: TreeDir, parentKey = "", out: string[] = []): string[] {
  for (const c of d.dirs) {
    const k = dirKey(parentKey, c.name);
    out.push(k);
    collectDirKeys(c, k, out);
  }
  return out;
}

/**
 * 读取持久化的展开状态，并**迁移旧格式**。
 *
 * 旧版本存的是 string[]（目录**名**数组，且同名目录会互相串联）。
 * 新格式是 OpenMap（完整路径 → true）。
 * 不做迁移的话，老用户 localStorage 里的旧数组会被当成 map 使用，
 * 展开状态全部丢失（表现为「刷新后全折叠」），而且旧键是目录名，
 * 可能误展开某个同名目录 —— 正是本次修掉的那个 bug。
 *
 * 迁移策略：把旧的 name 转成 "/name"（顶层目录的真实 key），
 * 匹配不上的直接丢弃 —— 宁可少展开，也不要错误展开。
 */
function loadOpenMap(): OpenMap {
  const raw = loadLS<unknown>(K_OPEN, {});
  if (raw && !Array.isArray(raw) && typeof raw === "object") return raw as OpenMap;
  if (Array.isArray(raw)) {
    const out: OpenMap = {};
    for (const nm of raw) if (typeof nm === "string") out["/" + nm] = true;
    return out;
  }
  return {};
}

function FileRow({
  f,
  sel,
  picked,
  onPick,
  onTogglePick,
  depth,
}: {
  f: TreeFile;
  sel: string;
  picked: boolean;
  onPick: (rel: string, e: React.MouseEvent) => void;
  onTogglePick: (rel: string) => void;
  /** 层级缩进（px/层）—— 压平后靠 style 表达缩进，视觉与原递归一致。 */
  depth: number;
}) {
  const [t] = useI18n();
  const active = sel === f.rel;
  const score = f.auto_score;
  const cls = score == null ? "none" : score >= 90 ? "good" : score >= 70 ? "mid" : "bad";
  return (
    <div
      className={`trow tree-file ${active ? "sel" : ""} ${picked ? "picked" : ""}`}
      style={{ borderLeftColor: active ? "var(--brand)" : STATE_BAR[f.state], paddingLeft: 6 + INDENT * depth }}
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

/** 单行高度（px）。虚拟滚动用，改一处要同步 CSS 的 .trow 高度。 */
const ROW_H = 24;
/** 每层缩进（px）。 */
const INDENT = 13;
/** 虚拟滚动视口上下各多渲染的行数。 */
const OVERSCAN = 12;

/**
 * 目录行（扁平行，不再递归）。
 * key 用**完整路径**，不是目录名 —— 同名目录会互相串联（实测 SS×13 / DWG×12）。
 */
function DirRow({
  d,
  keyName,
  sel,
  picked,
  open,
  depth,
  onToggleOpen,
  onPick,
  onTogglePick,
  onToggleDir,
}: {
  d: TreeDir;
  keyName: string;
  sel: string;
  picked: Set<string>;
  open: boolean;
  depth: number;
  onToggleOpen: (key: string) => void;
  onPick: (rel: string, e: React.MouseEvent) => void;
  onTogglePick: (rel: string) => void;
  onToggleDir: (d: TreeDir) => void;
}) {
  const rels = useMemo(() => collectFiles(d), [d]);
  const pickedCount = useMemo(() => rels.filter((r) => picked.has(r)).length, [rels, picked]);
  const allPicked = rels.length > 0 && pickedCount === rels.length;

  const c: TreeCounts = d.counts;
  const title = `${d.name} · ${c.all}`;

  return (
    <div
      className="trow dir"
      onClick={() => onToggleOpen(keyName)}
      title={title}
      style={depth === 0 ? { fontWeight: 600, paddingLeft: 6 + INDENT * depth } : { paddingLeft: 6 + INDENT * depth }}
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
  const [openMap, setOpenMap] = useState<OpenMap>(() => loadOpenMap());
  const [lastAnchor, setLastAnchor] = useState<string>("");

  /** 虚拟滚动：滚动位置 + 视口高度。 */
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [bodyRef, setBodyRef] = useState({ top: 0, h: 600 });

  const dragging = useRef(false);

  // 宽度限制：太窄树里名字全看不见，太宽会挤掉对比区
  const clampW = (w: number) => Math.max(200, Math.min(640, w));

  useEffect(() => saveLS(K_WIDTH, width), [width]);
  useEffect(() => saveLS(K_OPEN, openMap), [openMap]);

  /** 视口高度测量（虚拟滚动用）。 */
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const measure = () => setBodyRef((b) => (b.h === el.clientHeight ? b : { ...b, h: el.clientHeight || 600 }));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

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

  /** 展开状态持久化后，刷新仍回到同一位置。key 是完整路径，不是目录名。 */
  const toggleOpen = useCallback((key: string) => {
    setOpenMap((prev) => {
      const next = { ...prev };
      if (next[key]) delete next[key];
      else next[key] = true;
      return next;
    });
  }, []);

  /**
   * 搜索 / 筛选时自动展开。
   *
   * ⚠️ 后端在有 q 或 status 时只返回**匹配路径上的目录**（层级仍完整），
   * 若沿用用户上次的展开状态，新命中路径上的目录多半是折叠的 ——
   * 用户会看到「搜到了却什么都看不见」。所以这里按当前树全部展开。
   * 清空搜索后不自动折叠：保留用户刚才看到的结果，避免二次操作。
   */
  useEffect(() => {
    if (!tree) return;
    if (!q.trim() && !status) return;
    setOpenMap((prev) => {
      const next: OpenMap = { ...prev };
      let n = 0;
      for (const k of collectDirKeys(tree)) {
        if (!next[k]) n++;
        next[k] = true;
      }
      return n ? next : prev;
    });
  }, [tree, q, status]);

  /**
   * 全部展开 / 全部折叠（用户 2026-10-05 明确要求「放开这两个功能」）。
   *
   * 实现要点：
   *  - 展开 = 把**所有目录**的 key 置 true（递归收集，实测 368 个目录）；
   *  - 折叠 = 清空整个 map（不是设 false，留着 true 会让下次展开按钮失灵）；
   *  - 展开后可见行 2002（1634 文件 + 368 目录）→ 必须靠虚拟滚动才不卡。
   *
   * ⚠️ 之前这里是死代码：`allOpen` 只在 `allOpen || openSet.has(d.name)` 里
   * 短路一级目录，且 key 用目录名（同名目录串联，实测 SS×13/DWG×12），
   * 所以「点了像没反应」。现在改为真正遍历所有层级。
   */
  const allDirKeys = useMemo(
    () => (tree ? collectDirKeys(tree) : []),
    [tree],
  );
  const expandAll = useCallback(() => {
    const next: OpenMap = {};
    for (const k of allDirKeys) next[k] = true;
    setOpenMap(next);
    setBodyRef((b) => ({ ...b, top: 0 }));
    scrollerRef.current?.scrollTo({ top: 0 });
  }, [allDirKeys]);
  const collapseAll = useCallback(() => {
    // 必须清空而不是全置 false：false 的键在 persist 后是噪音，
    // 且 toggleOpen 用 `if (next[key])` 判断，残留 true 会导致折叠后再点开不了。
    setOpenMap({});
    setBodyRef((b) => ({ ...b, top: 0 }));
    scrollerRef.current?.scrollTo({ top: 0 });
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

  /** 扁平化：只包含「当前展开状态下可见」的行。 */
  const rows = useMemo(() => (tree ? flattenTree(tree, openMap) : []), [tree, openMap]);

  /** 虚拟滚动窗口。行高固定（目录/文件都是单行 trow），无需动态测量。 */
  const startIdx = Math.max(0, Math.floor(bodyRef.top / ROW_H) - OVERSCAN);
  const endIdx = Math.min(rows.length, Math.ceil((bodyRef.top + bodyRef.h) / ROW_H) + OVERSCAN);
  const slice = rows.slice(startIdx, endIdx);
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
          {/* 「全部展开 / 全部折叠」—— 之前是死按钮（allOpen 只短路一级目录，
              且用目录名当 key 导致同名目录串联）。现在真正作用于所有层级。 */}
          <button className="ghost sm" onClick={expandAll} disabled={!tree} title={t("act.expandAllTip", { n: allDirKeys.length })}>
            {t("act.expandAll")}
          </button>
          <button className="ghost sm" onClick={collapseAll} disabled={!tree} title={t("act.collapseAllTip")}>
            {t("act.collapseAll")}
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

      <div
        className="tree-body tvirtual"
        ref={scrollerRef}
        onScroll={(e) => setBodyRef((b) => (b.top === e.currentTarget.scrollTop ? b : { ...b, top: e.currentTarget.scrollTop }))}
      >
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
        {/* 虚拟滚动：全展开 1634 行也只渲染视口内的 ~30 行 */}
        {tree && rows.length > 0 && (
          <div style={{ height: rows.length * ROW_H, position: "relative" }}>
            {slice.map((r, k) => {
              const abs = startIdx + k;
              return (
                <div
                  key={r.kind === "dir" ? r.key : r.f.rel}
                  style={{ position: "absolute", top: abs * ROW_H, left: 0, right: 0, height: ROW_H }}
                >
                  {r.kind === "dir" ? (
                    <DirRow
                      d={r.d}
                      keyName={r.key}
                      sel={sel}
                      picked={picked}
                      open={!!openMap[r.key]}
                      depth={r.depth}
                      onToggleOpen={toggleOpen}
                      onPick={handlePick}
                      onTogglePick={togglePick}
                      onToggleDir={toggleDir}
                    />
                  ) : (
                    <FileRow
                      f={r.f}
                      sel={sel}
                      picked={picked.has(r.f.rel)}
                      depth={r.depth}
                      onPick={handlePick}
                      onTogglePick={togglePick}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
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
