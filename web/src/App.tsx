import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  AlignResp,
  Badge,
  Job,
  MdResp,
  Reviewer,
  Source,
  Stats,
  TrustState,
} from "./types";
import FileTree from "./components/FileTree";
import SourcePane from "./components/SourcePane";
import MdPane from "./components/MdPane";
import DecisionsPanel from "./components/DecisionsPanel";
import SalvagePanel from "./components/SalvagePanel";
import ReviewerPanel from "./components/ReviewerPanel";
import SourceManager from "./components/SourceManager";
import FolderPicker from "./components/FolderPicker";
import { useI18n } from "./i18n";

type Notice = { kind: "warn" | "err" | "ok"; text: string };

const REVIEWER_KEY = "fidelity.reviewer";
const SEL_KEY = "fidelity.lastfile";
const ZOOM_KEY = "fidelity.zoom";
const THRESH_KEY = "fidelity.threshold";

function loadNum(k: string, d: number, lo: number, hi: number) {
  const v = parseFloat(localStorage.getItem(k) || "");
  return Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : d;
}

export default function App() {
  const [t, lang, setLang] = useI18n();

  const [sources, setSources] = useState<Source[]>([]);
  const [sid, setSid] = useState("n2");
  const [status, setStatus] = useState<TrustState | "">("");

  const [sel, setSel] = useState(() => localStorage.getItem(SEL_KEY) || "");
  const [badge, setBadge] = useState<Badge | null>(null);
  const [align, setAlign] = useState<AlignResp | null>(null);
  const [md, setMd] = useState<MdResp | null>(null);
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(1);
  const [curLine, setCurLine] = useState<number | null>(null);
  /** 由右栏点击触发的左栏高亮文本。 */
  const [focusMark, setFocusMark] = useState<string | null>(null);
  /** 由左栏点击触发的右栏定位行。 */
  const [focusLine, setFocusLine] = useState<number | null>(null);

  const [zoomL, setZoomL] = useState(() => loadNum(ZOOM_KEY + ".l", 1, 0.5, 3));
  const [zoomR, setZoomR] = useState(() => loadNum(ZOOM_KEY + ".r", 1, 0.5, 3));

  const [showMarks, setShowMarks] = useState(true);
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [lineSearch, setLineSearch] = useState("");

  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [threshold, setThreshold] = useState(() => loadNum(THRESH_KEY, 90, 50, 100));

  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [reviewer, setReviewer] = useState(() => localStorage.getItem(REVIEWER_KEY) || "");
  const [note, setNote] = useState("");

  const [showReviewers, setShowReviewers] = useState(false);
  const [showDecide, setShowDecide] = useState(false);
  const [showSalvage, setShowSalvage] = useState(false);
  const [showMgr, setShowMgr] = useState(false);
  const [picker, setPicker] = useState<null | "src_root" | "md_root">(null);
  const [draft, setDraft] = useState<Partial<Source>>({});

  const busy = !!job && (job.status === "queued" || job.status === "running");

  const say = useCallback((kind: Notice["kind"], text: string) => setNotice({ kind, text }), []);

  useEffect(() => localStorage.setItem(REVIEWER_KEY, reviewer), [reviewer]);
  useEffect(() => localStorage.setItem(THRESH_KEY, String(threshold)), [threshold]);
  useEffect(() => localStorage.setItem(ZOOM_KEY + ".l", String(zoomL)), [zoomL]);
  useEffect(() => localStorage.setItem(ZOOM_KEY + ".r", String(zoomR)), [zoomR]);
  useEffect(() => {
    if (sel) localStorage.setItem(SEL_KEY, sel);
  }, [sel]);

  // ---------- 启动 ----------
  useEffect(() => {
    (async () => {
      try {
        await api.health();
        const ss = await api.sources();
        setSources(ss);
        if (ss.length && !ss.some((s) => s.id === sid)) setSid(ss[0].id);
        const rv = await api.reviewers();
        setReviewers(rv.items);
        setReviewer((cur) => {
          const ok = rv.items.find((r) => r.name === cur && r.enabled);
          if (ok) return cur;
          const first = rv.items.find((r) => r.enabled);
          return first ? first.name : cur;
        });
      } catch (e: any) {
        say("err", t("msg.backendDown", { m: e.message }));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshStats = useCallback(() => {
    api.stats(sid).then(setStats).catch(() => {});
  }, [sid]);

  useEffect(() => {
    refreshStats();
  }, [sid, refreshStats]);

  const refreshBadge = useCallback(() => {
    if (!sel || !sid) return;
    api
      .files(sid, status)
      .then((r) => setBadge(r.files.find((f) => f.rel === sel) || null))
      .catch(() => {});
  }, [sel, sid, status]);

  // ---------- 当前文件的数据 ----------
  useEffect(() => {
    if (!sel || !sid) {
      setAlign(null);
      setMd(null);
      setBadge(null);
      return;
    }
    let alive = true;
    setAlign(null);
    setMd(null);
    setPage(1);
    setCurLine(null);
    setFocusMark(null);
    setFocusLine(null);
    setLineSearch("");

    api
      .align(sel, sid)
      .then((a) => alive && setAlign(a))
      .catch((e) => alive && say("err", e.message));
    api
      .md(sel, sid)
      .then((m) => alive && setMd(m))
      .catch(() => alive && setMd(null));
    refreshBadge();

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, sid]);

  // 状态筛选变化时，若当前文件已被筛掉，自动切到第一个
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    api
      .files(sid, status)
      .then((r) => {
        if (!alive || !r.files.length) return;
        if (!r.files.some((f) => f.rel === sel)) setSel(r.files[0].rel);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [sid, status, sel]);

  // ---------- 任务轮询 ----------
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const iv = setInterval(async () => {
      try {
        const j = await api.job(job.id);
        setJob(j);
        if (j.status === "done") {
          refreshStats();
          refreshBadge();
          if (sel && sid) {
            const [a, m] = await Promise.all([
              api.align(sel, sid).catch(() => null),
              api.md(sel, sid).catch(() => null),
            ]);
            setAlign(a);
            setMd(m);
          }
          say("ok", j.message || "OK");
        } else if (j.status === "error") {
          say("err", j.message || "error");
        }
      } catch {
        /* 静默重试 */
      }
    }, 1200);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status]);

  // ---------- 操作 ----------
  const runCompare = async () => {
    if (!sel) return;
    try {
      const { job_id } = await api.compare(sel, sid);
      setJob({ id: job_id, kind: "compare", rel: sel, status: "queued", progress: 0, message: "…", updated_at: "" });
      say("ok", t("msg.recalcQueued"));
    } catch (e: any) {
      say("err", e.message);
    }
  };

  const runBatch = async (force: boolean) => {
    try {
      const { job_id } = await api.batch(sid, force);
      setJob({ id: job_id, kind: "batch", rel: "", status: "queued", progress: 0, message: "…", updated_at: "" });
      say("ok", force ? t("msg.batchQueuedAll") : t("msg.batchQueued"));
    } catch (e: any) {
      say("err", e.message);
    }
  };

  const runDeferred = async () => {
    if (!confirm("重试被延后的大文件（放宽时间预算，耗时较长）。继续？")) return;
    try {
      const { job_id } = await api.batchDeferred(sid);
      setJob({ id: job_id, kind: "batch", rel: "", status: "queued", progress: 0, message: "…", updated_at: "" });
      say("ok", t("msg.deferredQueued"));
    } catch (e: any) {
      say("err", e.message);
    }
  };

  const showDeferredList = async () => {
    try {
      const d = await api.deferred(sid, 300);
      if (!d.count) {
        say("ok", t("msg.deferredNone"));
        return;
      }
      const lines = d.items
        .slice(0, 60)
        .map((x) => `${x.mb != null ? String(x.mb).padStart(7) + "MB" : "       ?"}  ${x.reason}  ${x.rel}`)
        .join("\n");
      alert(t("msg.deferredTitle", { n: d.count }) + "\n\n" + lines);
    } catch (e: any) {
      say("err", e.message);
    }
  };

  const doVerdict = async (v: string) => {
    if (!sel) return;
    if (!reviewer) {
      say("err", t("msg.reviewerNeeded"));
      return;
    }
    try {
      await api.review(sel, v, reviewer, note);
      setNote("");
      refreshBadge();
      refreshStats();
      const label = v === "ok" ? t("verdict.ok") : v === "diff_big" ? t("verdict.diff_big") : t("verdict.rejected");
      say("ok", v === "" ? t("msg.verdictRevoked") : t("msg.verdictSaved", { v: label, r: reviewer }));
    } catch (e: any) {
      say("err", e.message);
    }
  };

  /** 批量按阈值打「人工审核通过」标签。 */
  const batchPass = async () => {
    if (!picked.size) return;
    if (!reviewer) {
      say("err", t("msg.reviewerNeeded"));
      return;
    }
    const rels = Array.from(picked);
    if (!confirm(`${rels.length} 个文件，正确率 ≥ ${threshold}% 的将标记为「${t("verdict.ok")}」。继续？`)) return;
    try {
      const r = await api.reviewBatch(rels, threshold, reviewer, "");
      setPicked(new Set());
      refreshStats();
      refreshBadge();
      say("ok", t("msg.batchDone", { ok: r.ok, skip: r.skipped + r.already + r.no_score }));
    } catch (e: any) {
      say("err", e.message);
    }
  };

  /**
   * 点 md 行 → 左栏跳到对应页并高亮该段（双向联动）。
   * focusMark 传文本，左栏在源文件上描边；focusLine 让右栏也确保可见。
   */
  const pickLine = (i: number, pg: number | null) => {
    setCurLine(i);
    if (pg && pg !== page) setPage(pg);
    const txt = md?.lines?.[i];
    if (txt) {
      setFocusMark(txt.trim().slice(0, 60));
      window.setTimeout(() => setFocusMark(null), 2600);
    }
  };

  const score = badge?.auto_score ?? null;
  const scoreCls = score == null ? "none" : score >= 90 ? "good" : score >= 70 ? "mid" : "bad";
  const srcPath = useMemo(() => {
    const s = sources.find((x) => x.id === sid);
    if (!s || !sel) return sel;
    return `${s.src_root}\\${sel.replace(/\//g, "\\")}`;
  }, [sources, sid, sel]);

  const st = stats?.by_state || {};

  return (
    <div className="app">
      {/* ---------- 顶栏 ---------- */}
      <header className="header">
        <div className="brand">
          <div className="brand-mark">F</div>
          <div className="brand-text">
            <b>{t("app.title")}</b>
            <span>{t("app.subtitle")}</span>
          </div>
        </div>
        <div className="divider" />
        <select value={sid} onChange={(e) => setSid(e.target.value)} title={t("src.label")}>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button onClick={() => setShowMgr(true)}>{t("src.manage")}</button>
        <div className="divider" />
        <button className="primary" disabled={busy} onClick={() => runBatch(false)}>
          {t("act.batch")}
        </button>
        <button disabled={busy} onClick={() => { if (confirm("重跑全部将重新评分所有文件（含已评测），耗时较长。继续？")) runBatch(true); }}>
          {t("act.rebatch")}
        </button>
        <button disabled={busy} onClick={runDeferred}>
          {t("act.deferred")}
          {stats?.deferred ? ` (${stats.deferred})` : ""}
        </button>
        <button onClick={showDeferredList}>{t("act.deferredList")}</button>
        <div className="divider" />
        <button onClick={() => setShowDecide(true)}>
          {t("act.decide")}
          {stats?.decisions.pending ? ` (${stats.decisions.pending})` : ""}
        </button>
        <button onClick={() => setShowSalvage(true)}>
          {t("act.salvage")}
          {stats?.salvage ? ` (${stats.salvage})` : ""}
        </button>
        <div className="spacer" />
        <label className="btn upload">
          {t("act.upload")}
          <input
            type="file"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                const r = await api.upload(f, sid);
                say("warn", t("msg.uploaded", { rel: r.rel }));
              } catch (err: any) {
                say("err", err.message);
              }
              e.target.value = "";
            }}
          />
        </label>
        <div className="divider" />
        <select value={reviewer} onChange={(e) => setReviewer(e.target.value)} title={t("act.reviewer")} className="w-reviewer">
          <option value="">{t("verdict.pick")}</option>
          {reviewers.filter((r) => r.enabled).map((r) => (
            <option key={r.id || r.name} value={r.name}>
              {r.name}
            </option>
          ))}
        </select>
        <button onClick={() => setShowReviewers(true)}>{t("act.config")}</button>
        <div className="divider" />
        {/* 语言切换：仅界面文案切换，文件内容始终原样 */}
        <div className="langsw" role="group" aria-label={t("act.lang")}>
          <button className={lang === "zh" ? "on" : ""} onClick={() => setLang("zh")}>
            中文
          </button>
          <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>
            EN
          </button>
        </div>
      </header>

      {/* ---------- 统计行 ---------- */}
      <div className="statsbar">
        <div className="stat" title={t("stat.evaluatedTip")}>
          <span className="stat-k">{t("stat.evaluated")}</span>
          <span className="stat-v num">
            {stats ? `${stats.evaluated.toLocaleString()} / ${stats.total.toLocaleString()}` : "—"}
          </span>
        </div>
        <div className="stat">
          <span className="stat-k">{t("stat.avg")}</span>
          <span className={`stat-v num ${stats?.avg_score == null ? "" : stats.avg_score >= 90 ? "good" : stats.avg_score >= 70 ? "warn" : "bad"}`}>
            {stats?.avg_score != null ? `${stats.avg_score}%` : "—"}
          </span>
        </div>
        {/* 可点击的状态块：点击即筛选，避免用户找不到筛选入口 */}
        <button
          className={`stat clickable ${status === "unreviewed" ? "on" : ""}`}
          onClick={() => setStatus(status === "unreviewed" ? "" : "unreviewed")}
          title={t("stat.unreviewedTip")}
        >
          <span className="stat-k">{t("stat.unreviewed")}</span>
          <span className="stat-v num">{st.unreviewed?.toLocaleString() ?? "—"}</span>
        </button>
        <button className={`stat clickable ${status === "trusted" ? "on" : ""}`} onClick={() => setStatus(status === "trusted" ? "" : "trusted")}>
          <span className="stat-k">{t("stat.trusted")}</span>
          <span className="stat-v num good">{st.trusted?.toLocaleString() ?? "—"}</span>
        </button>
        <button className={`stat clickable ${status === "need_review" ? "on" : ""}`} onClick={() => setStatus(status === "need_review" ? "" : "need_review")}>
          <span className="stat-k">{t("stat.need_review")}</span>
          <span className="stat-v num warn">{st.need_review?.toLocaleString() ?? "—"}</span>
        </button>
        <button className={`stat clickable ${status === "diff_big" ? "on" : ""}`} onClick={() => setStatus(status === "diff_big" ? "" : "diff_big")}>
          <span className="stat-k">{t("stat.diff_big")}</span>
          <span className="stat-v num bad">{st.diff_big?.toLocaleString() ?? "—"}</span>
        </button>
        {stats?.decisions.pending ? (
          <button className="stat clickable" onClick={() => setShowDecide(true)}>
            <span className="stat-k">{t("stat.pending")}</span>
            <span className="stat-v num warn">{stats.decisions.pending.toLocaleString()}</span>
          </button>
        ) : null}
        {stats?.deferred ? (
          <div className="stat">
            <span className="stat-k">{t("stat.deferred")}</span>
            <span className="stat-v num">{stats.deferred}</span>
          </div>
        ) : null}
        {stats?.totals && stats.totals.src_chars > 0 && (
          <div className="stat" title={t("stat.keepTip")}>
            <span className="stat-k">{t("stat.chars")}</span>
            <span className="stat-v num">
              {(stats.totals.src_chars / 1e6).toFixed(1)}M → {(stats.totals.md_chars / 1e6).toFixed(1)}M
              {stats.totals.char_ratio != null && (
                /* ★ 不能一律写「保留」：ratio > 100% 说明 md 反而更大（膨胀），
                   标成「保留 143%」会误导用户以为内容超量保留。 */
                <small className={stats.totals.char_ratio > 100 ? "warn" : undefined}>
                  {stats.totals.char_ratio > 100
                    ? t("stat.expand", { n: Math.round(stats.totals.char_ratio - 100) })
                    : t("stat.keep", { n: stats.totals.char_ratio })}
                </small>
              )}
            </span>
          </div>
        )}
        <div className="spacer" />
        {busy && (
          <div className="runbar">
            <span className="nowrap">{t("stat.progress")}</span>
            <div className="runbar-track">
              <i style={{ width: `${job!.progress}%` }} />
            </div>
            <span className="num">{job!.progress}%</span>
            <span className="truncate" style={{ maxWidth: 220 }}>
              {job!.message}
            </span>
          </div>
        )}
      </div>

      {notice && (
        <div className={`notice ${notice.kind === "err" ? "err" : notice.kind === "ok" ? "ok" : ""}`}>
          <span>{notice.text}</span>
          <button className="ghost sm" onClick={() => setNotice(null)}>
            {t("act.close")}
          </button>
        </div>
      )}

      {/* ---------- 主体 ---------- */}
      <div className="main">
        <FileTree
          sid={sid}
          sel={sel}
          status={status}
          onStatus={setStatus}
          onPick={(rel) => setSel(rel)}
          picked={picked}
          onPickedChange={setPicked}
          threshold={threshold}
          onThreshold={setThreshold}
          onBatchPass={batchPass}
          busy={busy}
        />

        <div className="work">
          {!sel ? (
            <div className="empty pad">{t("file.none")}</div>
          ) : (
            <>
              <div className="filehead">
                <div className="path truncate" title={sel}>
                  {sel}
                </div>
                <div className="spacer" />
                <div className="filemeta">
                  <span className={`score-pill ${scoreCls}`}>
                    {score != null ? t("file.auto", { n: score }) : t("file.noScore")}
                  </span>
                  {badge && (
                    <>
                      <span className={`badge ${badge.state}`}>{badge.label}</span>
                      {badge.src_chars != null && badge.md_chars != null && (
                        <span className="kv nowrap">
                          {t("file.chars")} <b>{badge.src_chars.toLocaleString()}</b> → <b>{badge.md_chars.toLocaleString()}</b>
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className="toolbar">
                <button className="primary" onClick={runCompare} disabled={busy}>
                  {t("act.recalc")}
                </button>
                <div className="vsep" />
                <button className={showMarks ? "on" : ""} onClick={() => setShowMarks((v) => !v)}>
                  {t("act.marks")}
                </button>
                <div className="seg">
                  <button className={!onlyDiff ? "on" : ""} onClick={() => setOnlyDiff(false)}>
                    {t("act.all")}
                  </button>
                  <button className={onlyDiff ? "on" : ""} onClick={() => setOnlyDiff(true)}>
                    {t("act.diff")}
                  </button>
                </div>
                <input
                  type="search"
                  value={lineSearch}
                  onChange={(e) => setLineSearch(e.target.value)}
                  placeholder={t("act.searchMd")}
                  className="w-search"
                />
                <div className="spacer" />
                {align && !align.not_applicable && (
                  <span className="hint num nowrap">{t("file.lines", { n: align.total_lines.toLocaleString() })}</span>
                )}
              </div>

              {align?.verdict && <div className="callout warn edge">{align.verdict}</div>}

              <div className="split">
                <div className="pane">
                  {md === null ? (
                    <div className="empty">
                      <span className="spin" />
                    </div>
                  ) : (
                    <SourcePane
                      sid={sid}
                      rel={sel}
                      page={page}
                      onPage={setPage}
                      onPageCount={setPageCount}
                      showMarks={showMarks}
                      zoom={zoomL}
                      onZoom={setZoomL}
                      focusMark={focusMark}
                      srcPath={srcPath}
                    />
                  )}
                </div>
                <div className="pane">
                  {md === null ? (
                    <div className="empty">…</div>
                  ) : (
                    <MdPane
                      md={md}
                      align={align}
                      onlyDiff={onlyDiff}
                      search={lineSearch}
                      curLine={curLine}
                      onPickLine={pickLine}
                      zoom={zoomR}
                      page={page}
                      focusLine={focusLine}
                    />
                  )}
                </div>
              </div>

              {/* 裁决区：三个状态用色块 + 文案，符合行业规范 */}
              <div className="verdictbar">
                <span className="lbl nowrap">{t("verdict.label")}</span>
                <div className="vgroup">
                  <button className={`vbtn ok ${badge?.trust_state === "ok" ? "sel" : ""}`} onClick={() => doVerdict("ok")}>
                    {t("verdict.ok")}
                  </button>
                  <button className={`vbtn diff ${badge?.trust_state === "diff_big" ? "sel" : ""}`} onClick={() => doVerdict("diff_big")}>
                    {t("verdict.diff_big")}
                  </button>
                  <button className={`vbtn rej ${badge?.trust_state === "rejected" ? "sel" : ""}`} onClick={() => doVerdict("rejected")}>
                    {t("verdict.rejected")}
                  </button>
                </div>
                {badge?.trust_state && (
                  <button className="ghost sm" onClick={() => doVerdict("")}>
                    {t("act.revoke")}
                  </button>
                )}
                <div className="vsep" />
                <div className="reviewer-pick">
                  <span className="lbl nowrap">{t("verdict.reviewer")}</span>
                  <select value={reviewer} onChange={(e) => setReviewer(e.target.value)}>
                    <option value="">{t("verdict.pick")}</option>
                    {reviewers.filter((r) => r.enabled).map((r) => (
                      <option key={r.id || r.name} value={r.name}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                  <button className="ghost sm" onClick={() => setShowReviewers(true)}>
                    {t("verdict.manage")}
                  </button>
                </div>
                <input className="note" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("verdict.note")} />
                {!badge?.trust_state && <span className="dim nowrap">{t("verdict.none")}</span>}
              </div>
            </>
          )}
        </div>
      </div>

      {showDecide && (
        <DecisionsPanel
          sid={sid}
          reviewer={reviewer}
          onClose={() => setShowDecide(false)}
          onChanged={refreshStats}
          onReeval={(rel) => {
            api
              .compare(rel, sid)
              .then(({ job_id }) =>
                setJob({ id: job_id, kind: "compare", rel, status: "queued", progress: 0, message: "…", updated_at: "" }),
              )
              .catch(() => {});
          }}
        />
      )}
      {showSalvage && (
        <SalvagePanel
          sid={sid}
          onClose={() => setShowSalvage(false)}
          onChanged={async () => {
            refreshStats();
            if (sel) {
              setMd(await api.md(sel, sid).catch(() => null));
              setAlign(await api.align(sel, sid).catch(() => null));
            }
          }}
        />
      )}
      {showReviewers && (
        <ReviewerPanel
          current={reviewer}
          onPick={setReviewer}
          onClose={async () => {
            setShowReviewers(false);
            const rv = await api.reviewers().catch(() => null);
            if (rv) setReviewers(rv.items);
          }}
        />
      )}
      {showMgr && (
        <SourceManager
          sources={sources}
          draft={draft}
          setDraft={setDraft}
          onClose={() => setShowMgr(false)}
          onSaved={async () => {
            setSources(await api.sources());
            setShowMgr(false);
          }}
          onPick={(which) => setPicker(which)}
        />
      )}
      {picker && (
        <FolderPicker
          title={picker === "src_root" ? t("src.pickSrc") : t("src.pickMd")}
          onClose={() => setPicker(null)}
          onPick={(p) => {
            setDraft((d) => ({ ...d, [picker]: p }));
            setPicker(null);
          }}
        />
      )}
    </div>
  );
}
