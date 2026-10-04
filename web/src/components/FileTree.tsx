import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { TreeCounts, TreeDir, TreeFile, TreeResp, TrustState } from "../types";

const STATE_DOT: Record<TrustState, string> = {
  trusted: "var(--green)",
  need_review: "var(--amber)",
  diff_big: "var(--red)",
  rejected: "var(--text-3)",
  unreviewed: "var(--brand-border)",
};

const FILTERS: { key: TrustState | ""; label: string }[] = [
  { key: "", label: "全部" },
  { key: "unreviewed", label: "未审" },
  { key: "need_review", label: "待复核" },
  { key: "trusted", label: "可信" },
  { key: "diff_big", label: "差异大" },
  { key: "rejected", label: "不接受" },
];

/** 目录图标：用极简几何形状，避免引入图标库依赖。 */
function DirIcon({ open }: { open: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden>
      <path
        d={open ? "M1.5 3.5h4l1.2 1.5H14v7.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z" : "M1.5 3.5h4l1.2 1.5H14v7.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"}
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

function FileRow({
  f,
  sel,
  onPick,
}: {
  f: TreeFile;
  sel: string;
  onPick: (rel: string) => void;
}) {
  const active = sel === f.rel;
  const score = f.auto_score;
  const cls = score == null ? "none" : score >= 90 ? "good" : score >= 70 ? "mid" : "bad";
  return (
    <div
      className={`trow tree-file ${active ? "sel" : ""}`}
      onClick={() => onPick(f.rel)}
      title={`${f.rel}\n${f.label}${score != null ? ` · 自动 ${score}%` : ""}`}
    >
      <span className="ticon">
        <FileIcon />
      </span>
      <span className="tname">{f.name}</span>
      {score != null && (
        <span className="tcount" style={{ color: cls === "good" ? "var(--green)" : cls === "bad" ? "var(--red)" : "var(--amber)" }}>
          {score}
        </span>
      )}
      <span className="tdot" style={{ background: STATE_DOT[f.state] }} title={f.label} />
    </div>
  );
}

function DirNode({
  d,
  sel,
  onPick,
  depth,
  defaultOpen,
}: {
  d: TreeDir;
  sel: string;
  onPick: (rel: string) => void;
  depth: number;
  defaultOpen: boolean;
}) {
  // 含选中文件时强制展开，保证「当前文件」永远可见
  const containsSel = useMemo(() => {
    const walk = (n: TreeDir): boolean =>
      n.files.some((f) => f.rel === sel) || n.dirs.some(walk);
    return walk(d);
  }, [d, sel]);

  const [open, setOpen] = useState(defaultOpen || containsSel || depth === 0);
  useEffect(() => {
    if (containsSel) setOpen(true);
  }, [containsSel]);

  const c: TreeCounts = d.counts;
  const title = `${d.name} · 共 ${c.all} 个${
    c.unreviewed ? ` · 未审 ${c.unreviewed}` : ""
  }${c.trusted ? ` · 可信 ${c.trusted}` : ""}`;

  return (
    <div className="tnode">
      <div
        className="trow dir"
        onClick={() => setOpen((o) => !o)}
        title={title}
        style={depth === 0 ? { fontWeight: 600 } : undefined}
      >
        <span className={`twist ${open ? "open" : ""}`}>▶</span>
        <span className="ticon">
          <DirIcon open={open} />
        </span>
        <span className="tname">{d.name}</span>
        <span className="tcount">{c.all}</span>
        {c.unreviewed > 0 && (
          <span className="tdot" style={{ background: "var(--brand-border)" }} title={`未审 ${c.unreviewed}`} />
        )}
      </div>
      {open && (
        <div className="tchildren">
          {d.dirs.map((x) => (
            <DirNode key={x.name} d={x} sel={sel} onPick={onPick} depth={depth + 1} defaultOpen={false} />
          ))}
          {d.files.map((f) => (
            <FileRow key={f.rel} f={f} sel={sel} onPick={onPick} />
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
}: {
  sid: string;
  sel: string;
  status: TrustState | "";
  onStatus: (s: TrustState | "") => void;
  onPick: (rel: string) => void;
}) {
  const [tree, setTree] = useState<TreeResp | null>(null);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  // 搜索防抖：避免每敲一个字就打一次全量树
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let alive = true;
    setErr("");
    api
      .tree(sid, status, q)
      .then((t) => alive && setTree(t))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [sid, status, q]);

  const counts = tree?.counts;

  return (
    <aside className="tree">
      <div className="tree-head">
        <div className="tree-search">
          <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden>
            <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={search}
            placeholder="搜索文件或目录…"
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="tree-filters">
          {FILTERS.map((f) => (
            <button
              key={f.key || "all"}
              className={`chip ${status === f.key ? "on" : ""}`}
              onClick={() => onStatus(f.key)}
            >
              {f.key !== "" && <i style={{ background: STATE_DOT[f.key] }} />}
              {f.label}
              {counts && f.key !== "" && counts[f.key] > 0 && <span className="c">{counts[f.key]}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="tree-body">
        {err && <div className="empty">读取目录失败：{err}</div>}
        {!err && !tree && (
          <div className="empty">
            <span className="spin" />
          </div>
        )}
        {tree && tree.dirs.length === 0 && tree.files.length === 0 && (
          <div className="empty">该筛选条件下没有文件</div>
        )}
        {tree &&
          tree.dirs.map((d) => (
            <DirNode key={d.name} d={d} sel={sel} onPick={onPick} depth={0} defaultOpen />
          ))}
        {tree &&
          tree.files.map((f) => <FileRow key={f.rel} f={f} sel={sel} onPick={onPick} />)}
      </div>
    </aside>
  );
}
