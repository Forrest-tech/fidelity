import { useCallback, useEffect, useRef, useState } from "react";
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

type Notice = { kind: "warn" | "err" | "ok"; text: string };

/** 保留上次选择的审核人，避免每次刷新都要重选。 */
const REVIEWER_KEY = "fidelity.reviewer";

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sid, setSid] = useState("n2");
  const [status, setStatus] = useState<TrustState | "">("");

  const [sel, setSel] = useState("");
  const [badge, setBadge] = useState<Badge | null>(null);
  const [align, setAlign] = useState<AlignResp | null>(null);
  const [md, setMd] = useState<MdResp | null>(null);
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(1);
  const [curLine, setCurLine] = useState<number | null>(null);

  const [showMarks, setShowMarks] = useState(true);
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [lineSearch, setLineSearch] = useState("");

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

  const say = useCallback((kind: Notice["kind"], text: string) => {
    setNotice({ kind, text });
  }, []);

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
        say("err", "后端未就绪：" + e.message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (reviewer) localStorage.setItem(REVIEWER_KEY, reviewer);
  }, [reviewer]);

  const refreshStats = useCallback(() => {
    api.stats(sid).then(setStats).catch(() => {});
  }, [sid]);

  useEffect(() => {
    refreshStats();
  }, [sid, refreshStats]);

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
    setLineSearch("");

    api
      .align(sel, sid)
      .then((a) => alive && setAlign(a))
      .catch((e) => alive && say("err", "读取逐行比对失败：" + e.message));
    api
      .md(sel, sid)
      .then((m) => alive && setMd(m))
      .catch(() => alive && setMd(null));
    api
      .files(sid, status)
      .then((r) => {
        if (!alive) return;
        const b = r.files.find((f) => f.rel === sel);
        if (b) setBadge(b);
      })
      .catch(() => {});

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
    const t = setInterval(async () => {
      try {
        const j = await api.job(job.id);
        setJob(j);
        if (j.status === "done") {
          refreshStats();
          if (sel && sid) {
            const [a, m, r] = await Promise.all([
              api.align(sel, sid).catch(() => null),
              api.md(sel, sid).catch(() => null),
              api.files(sid, status).catch(() => null),
            ]);
            setAlign(a);
            setMd(m);
            const b = r?.files.find((f) => f.rel === sel);
            if (b) setBadge(b);
          }
          say("ok", j.message || "任务完成");
        } else if (j.status === "error") {
          say("err", j.message || "任务失败");
        }
      } catch {
        /* 轮询失败静默重试 */
      }
    }, 1200);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status]);

  // ---------- 操作 ----------
  const runCompare = async () => {
    if (!sel) return;
    try {
      const { job_id } = await api.compare(sel, sid);
      setJob({ id: job_id, kind: "compare", rel: sel, status: "queued", progress: 0, message: "排队中", updated_at: "" });
    } catch (e: any) {
      say("err", "提交评测失败：" + e.message);
    }
  };

  const runBatch = async (force: boolean) => {
    try {
      const { job_id } = await api.batch(sid, force);
      setJob({
        id: job_id, kind: "batch", rel: "", status: "queued", progress: 0,
        message: force ? "排队中（重跑全部）" : "排队中（仅评测未评文件）", updated_at: "",
      });
    } catch (e: any) {
      say("err", "提交批量评测失败：" + e.message);
    }
  };

  const runDeferred = async () => {
    if (!confirm(`将对被延后的大文件逐个重试（放宽时间预算，耗时可能较长）。继续？`)) return;
    try {
      const { job_id } = await api.batchDeferred(sid);
      setJob({ id: job_id, kind: "batch", rel: "", status: "queued", progress: 0, message: "排队中（补跑延后文件）", updated_at: "" });
    } catch (e: any) {
      say("err", "提交补跑失败：" + e.message);
    }
  };

  const showDeferredList = async () => {
    try {
      const d = await api.deferred(sid, 300);
      if (!d.count) {
        say("ok", "当前没有被延后的文件。");
        return;
      }
      const lines = d.items
        .slice(0, 60)
        .map((x) => `${x.mb != null ? String(x.mb).padStart(7) + "MB" : "       ?"}  ${x.reason}  ${x.rel}`)
        .join("\n");
      alert(`被延后的文件 ${d.count} 个（体积 / 原因 / 路径）：\n\n${lines}`);
    } catch (e: any) {
      say("err", "读取延后清单失败：" + e.message);
    }
  };

  const doVerdict = async (v: string) => {
    if (!sel) return;
    if (!reviewer) {
      say("err", "请先选择审核人（右上角「审核人」下拉，或在审核人配置中添加）");
      return;
    }
    try {
      await api.review(sel, v, reviewer, note);
      setNote("");
      const r = await api.files(sid, status);
      setBadge(r.files.find((f) => f.rel === sel) || null);
      refreshStats();
      say("ok", v === "" ? "已撤销裁决" : `已记录裁决：${v === "ok" ? "一致" : v === "diff_big" ? "差异大" : "不接受"}（${reviewer}）`);
    } catch (e: any) {
      say("err", "保存裁决失败：" + e.message);
    }
  };

  // 点 md 行 → 跳到源文件对应页
  const pickLine = (i: number, pg: number | null) => {
    setCurLine(i);
    if (pg && pg !== page) setPage(pg);
  };

  const score = badge?.auto_score ?? null;
  const scoreCls = score == null ? "none" : score >= 90 ? "good" : score >= 70 ? "mid" : "bad";

  return (
    <div className="app">
      {/* ---------- 顶栏 ---------- */}
      <header className="header">
        <div className="brand">
          <div className="brand-mark">F</div>
          <div className="brand-text">
            <b>转换保真度评测</b>
            <span>Fidelity</span>
          </div>
        </div>
        <div className="divider" />
        <select value={sid} onChange={(e) => setSid(e.target.value)} title="数据源">
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <button onClick={() => setShowMgr(true)}>数据源…</button>
        <div className="divider" />
        <button className="primary" disabled={busy} onClick={() => runBatch(false)} title="对尚未评测的文件批量计算自动保真度">
          批量评测
        </button>
        <button disabled={busy} onClick={() => { if (confirm("重跑全部将重新评分所有文件（含已评测），耗时较长。继续？")) runBatch(true); }}>
          重跑全部
        </button>
        <button disabled={busy} onClick={runDeferred} title="对被延后的大文件逐个重试">
          补跑延后{stats?.deferred ? ` (${stats.deferred})` : ""}
        </button>
        <button onClick={showDeferredList}>延后清单</button>
        <div className="divider" />
        <button className="primary" onClick={() => setShowDecide(true)} title="无法自动比对的文件，入库与否由人工决定">
          待决定{stats?.decisions.pending ? ` (${stats.decisions.pending})` : ""}
        </button>
        <button onClick={() => setShowSalvage(true)} title="原产物是二进制打捞的文件：用真实提取结果重写 .md">
          需重新转换{stats?.salvage ? ` (${stats.salvage})` : ""}
        </button>
        <div className="spacer" />
        <label className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid var(--border-strong)", borderRadius: "var(--r)", padding: "6px 12px", cursor: "pointer", background: "var(--surface)" }}>
          上传文件
          <input
            type="file"
            style={{ display: "none" }}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                const r = await api.upload(f, sid);
                say("warn", `已上传 ${r.rel} 到源目录，等待转换生成 .md`);
              } catch (err: any) {
                say("err", "上传失败：" + err.message);
              }
              e.target.value = "";
            }}
          />
        </label>
        <div className="divider" />
        <select
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          title="当前审核人（决定写入审计日志的身份）"
          style={{ width: 150 }}
        >
          <option value="">选择审核人…</option>
          {reviewers.filter((r) => r.enabled).map((r) => (
            <option key={r.id || r.name} value={r.name}>
              {r.name}（{r.role}）
            </option>
          ))}
        </select>
        <button onClick={() => setShowReviewers(true)} title="管理审核人名单">配置</button>
      </header>

      {/* ---------- 统计行（独立成行） ---------- */}
      <div className="statsbar">
        <div className="stat">
          <span className="stat-k">已评测 / 全部</span>
          <span className="stat-v num">
            {stats ? `${stats.evaluated.toLocaleString()}/${stats.total.toLocaleString()}` : "—"}
          </span>
        </div>
        <div className="stat">
          <span className="stat-k">平均保真度</span>
          <span className={`stat-v num ${stats?.avg_score == null ? "" : stats.avg_score >= 90 ? "good" : stats.avg_score >= 70 ? "warn" : "bad"}`}>
            {stats?.avg_score != null ? `${stats.avg_score}%` : "—"}
          </span>
        </div>
        <div className="stat clickable" onClick={() => setStatus("unreviewed")} title="只看未审">
          <span className="stat-k">未审</span>
          <span className="stat-v num">{stats?.by_state.unreviewed?.toLocaleString() ?? "—"}</span>
        </div>
        <div className="stat clickable" onClick={() => setStatus("trusted")} title="只看可信">
          <span className="stat-k">可信</span>
          <span className="stat-v num good">{stats?.by_state.trusted?.toLocaleString() ?? "—"}</span>
        </div>
        <div className="stat clickable" onClick={() => setStatus("need_review")} title="只看待复核">
          <span className="stat-k">待复核</span>
          <span className="stat-v num warn">{stats?.by_state.need_review?.toLocaleString() ?? "—"}</span>
        </div>
        <div className="stat clickable" onClick={() => setStatus("diff_big")} title="只看差异大">
          <span className="stat-k">差异大</span>
          <span className="stat-v num bad">{stats?.by_state.diff_big?.toLocaleString() ?? "—"}</span>
        </div>
        <div className="stat clickable" onClick={() => setShowDecide(true)} title="打开人工决定队列">
          <span className="stat-k">待决定</span>
          <span className="stat-v num warn">{stats?.decisions.pending?.toLocaleString() ?? "—"}</span>
        </div>
        <div className="stat">
          <span className="stat-k">延后</span>
          <span className="stat-v num">{stats?.deferred ?? "—"}</span>
        </div>
        {stats?.totals && stats.totals.src_chars > 0 && (
          <div className="stat" title="全库源文件抽取字数 → 入库 .md 字数">
            <span className="stat-k">总字数 源 → md</span>
            <span className="stat-v num">
              {(stats.totals.src_chars / 1e6).toFixed(1)}M → {(stats.totals.md_chars / 1e6).toFixed(1)}M
              {stats.totals.char_ratio != null && <small>保留 {stats.totals.char_ratio}%</small>}
            </span>
          </div>
        )}

        {busy && (
          <div className="runbar">
            <div className="runbar-track"><i style={{ width: `${job!.progress}%` }} /></div>
            <span className="num">{job!.progress}%</span>
            <span className="truncate" style={{ maxWidth: 260 }}>{job!.message}</span>
          </div>
        )}
      </div>

      {/* ---------- 通知条 ---------- */}
      {notice && (
        <div className={`notice ${notice.kind === "err" ? "err" : notice.kind === "ok" ? "ok" : ""}`}>
          <span>{notice.text}</span>
          <button className="ghost sm" onClick={() => setNotice(null)}>关闭</button>
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
        />

        <div className="work">
          {!sel ? (
            <div className="empty" style={{ paddingTop: 80 }}>
              从左侧目录树中选择一个文件开始核对
            </div>
          ) : (
            <>
              <div className="filehead">
                <div className="path truncate" title={sel}>{sel}</div>
                <div className="spacer" />
                <div className="filemeta">
                  <span className={`score-pill ${scoreCls}`}>
                    {score != null ? `自动 ${score}%` : "无自动分"}
                  </span>
                  {badge && (
                    <>
                      <span className={`badge ${badge.state}`}>{badge.label}</span>
                      {badge.src_chars != null && badge.md_chars != null && (
                        <span className="kv" title="源文件独立抽取字数 → 入库 .md 字数">
                          字数 <b>{badge.src_chars.toLocaleString()}</b> → <b>{badge.md_chars.toLocaleString()}</b>
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className="toolbar">
                <button className="primary" onClick={runCompare} disabled={busy}>
                  重新评测
                </button>
                <div className="divider" style={{ width: 1, height: 20, background: "var(--border)" }} />
                <button className={showMarks ? "on" : ""} onClick={() => setShowMarks((v) => !v)}>
                  高亮命中
                </button>
                <div className="seg">
                  <button className={!onlyDiff ? "on" : ""} onClick={() => setOnlyDiff(false)}>全部内容</button>
                  <button className={onlyDiff ? "on" : ""} onClick={() => setOnlyDiff(true)}>只看差异</button>
                </div>
                <input
                  type="search"
                  value={lineSearch}
                  onChange={(e) => setLineSearch(e.target.value)}
                  placeholder="在 md 中查找…"
                  style={{ width: 180 }}
                />
                <div className="spacer" />
                <span className="legend">
                  <span><i style={{ background: "var(--green-bg)", borderColor: "var(--green-border)" }} />两侧一致</span>
                  <span><i style={{ background: "var(--red-bg)", borderColor: "var(--red-border)" }} />md 多出 / 源文有</span>
                </span>
                {align && !align.not_applicable && (
                  <span className="hint num">
                    {align.total_lines.toLocaleString()} 行
                  </span>
                )}
              </div>

              {align?.verdict && (
                <div className="callout warn" style={{ margin: 0, borderRadius: 0, border: 0, borderBottom: "1px solid var(--amber-border)" }}>
                  {align.verdict}
                </div>
              )}

              <div className="split">
                <div className="pane">
                  {md === null ? (
                    <div className="empty"><span className="spin" /></div>
                  ) : (
                    <SourcePane
                      sid={sid}
                      rel={sel}
                      page={page}
                      onPage={setPage}
                      onPageCount={setPageCount}
                      showMarks={showMarks}
                    />
                  )}
                </div>
                <div className="pane">
                  {md === null ? (
                    <div className="empty">读取 .md 中…</div>
                  ) : (
                    <MdPane
                      md={md}
                      align={align}
                      onlyDiff={onlyDiff}
                      search={lineSearch}
                      curLine={curLine}
                      onPickLine={pickLine}
                    />
                  )}
                </div>
              </div>

              <div className="verdictbar">
                <span className="lbl">人工裁决</span>
                <button className={`vbtn ok ${badge?.trust_state === "ok" ? "sel" : ""}`} onClick={() => doVerdict("ok")}>
                  一致
                </button>
                <button className={`vbtn diff ${badge?.trust_state === "diff_big" ? "sel" : ""}`} onClick={() => doVerdict("diff_big")}>
                  差异大
                </button>
                <button className={`vbtn rej ${badge?.trust_state === "rejected" ? "sel" : ""}`} onClick={() => doVerdict("rejected")}>
                  不接受
                </button>
                {badge?.trust_state && (
                  <button onClick={() => doVerdict("")} title="撤销裁决，回到未审">撤销</button>
                )}
                <div className="divider" style={{ width: 1, height: 20, background: "var(--border)" }} />
                <div className="reviewer-pick">
                  <span className="lbl">审核人</span>
                  <select value={reviewer} onChange={(e) => setReviewer(e.target.value)}>
                    <option value="">选择…</option>
                    {reviewers.filter((r) => r.enabled).map((r) => (
                      <option key={r.id || r.name} value={r.name}>{r.name}</option>
                    ))}
                  </select>
                  <button className="ghost sm" onClick={() => setShowReviewers(true)}>管理</button>
                </div>
                <input
                  className="note"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="裁决备注（可选，写入审计日志）"
                />
                {badge?.badge && <span className="dim nowrap">{badge.badge}</span>}
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
            api.compare(rel, sid).then(({ job_id }) => {
              setJob({ id: job_id, kind: "compare", rel, status: "queued", progress: 0, message: "排队中（重跑识别）", updated_at: "" });
            }).catch(() => {});
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
          onPick={(n) => setReviewer(n)}
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
          title={picker === "src_root" ? "选择源文件目录" : "选择 .md 输出镜像目录"}
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
