import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Badge, DecisionStats, DiffResp, Job, MdResp, Segment, Source, Totals, TrustState } from "./types";
import FolderPicker from "./components/FolderPicker";
import SourceManager from "./components/SourceManager";
import DecisionsPanel from "./components/DecisionsPanel";
import SalvagePanel from "./components/SalvagePanel";
import SourcePreview from "./components/SourcePreview";

const STATUS_TABS: { key: TrustState | ""; label: string }[] = [
  { key: "", label: "全部" },
  { key: "unreviewed", label: "未审" },
  { key: "need_review", label: "待复核" },
  { key: "trusted", label: "可信" },
  { key: "diff_big", label: "差异大" },
  { key: "rejected", label: "不接受" },
];

const PER_PAGE = 50;

/** 文件级字数指标：源文 vs md 的字数/词数与比率（比率直观体现「转换完整度」）。 */
function WordsMeter({ b }: { b?: Badge }) {
  if (!b || b.src_chars == null || b.md_chars == null) return null;
  const ratio = b.src_chars ? Math.round((b.md_chars / b.src_chars) * 100) : null;
  const cls = ratio == null ? "" : ratio >= 90 ? "high" : ratio >= 60 ? "mid" : "low";
  return (
    <span className="wm" title="源文件独立抽取的字数 vs 入库 .md 的字数（.md 已剥离 front-matter / HTML 注释 / 标题）">
      字数 源 <b>{b.src_chars.toLocaleString()}</b> → md <b>{b.md_chars.toLocaleString()}</b>
      {ratio != null && <> · 保留 <span className={`ratio ${cls}`}>{ratio}%</span></>}
      {b.src_words != null && b.md_words != null && (
        <span className="score">（{b.src_words.toLocaleString()} → {b.md_words.toLocaleString()} 词）</span>
      )}
    </span>
  );
}

/** 右栏：入库 .md 原文（按行号渲染，保留换行结构）。 */
function MdView({ md }: { md: MdResp }) {
  const lines = useMemo(() => (md.text || "").split("\n"), [md.text]);
  if (!lines.length) return <div className="empty">.md 为空</div>;
  return (
    <div className="mdview">
      {lines.map((t, i) => (
        <div className="mdline" key={i}>
          <div className="no">{i + 1}</div>
          <div className="tx">{t || " "}</div>
        </div>
      ))}
    </div>
  );
}


export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sid, setSid] = useState("n2");
  const [status, setStatus] = useState<TrustState | "">("");
  const [files, setFiles] = useState<Badge[]>([]);
  const [sel, setSel] = useState<string>("");
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [page, setPage] = useState(1);
  const [diff, setDiff] = useState<DiffResp | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [reviewer, setReviewer] = useState("Forrest");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ kind: "warn" | "err"; text: string } | null>(null);
  const [stats, setStats] = useState<{ total: number; evaluated: number; avg_score: number | null; reviewed: number; deferred: number; decisions?: DecisionStats; salvage?: number; totals?: Totals } | null>(null);
  const [showMgr, setShowMgr] = useState(false);
  // 左栏视图：preview = 源文件原生渲染；text = 源文本逐行比对（绿/红标记）
  const [leftMode, setLeftMode] = useState<"preview" | "text">("preview");
  const [mdText, setMdText] = useState<MdResp | null>(null);
  const [showDecide, setShowDecide] = useState(false);
  const [showSalvage, setShowSalvage] = useState(false);
  const [picker, setPicker] = useState<null | "src_root" | "md_root">(null);
  const [draft, setDraft] = useState<Partial<Source>>({});
  const fileRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // 初始化：健康检查 + 数据源
  useEffect(() => {
    (async () => {
      try {
        await api.health();
        const ss = await api.sources();
        setSources(ss);
        if (ss.length && !ss.some((s) => s.id === sid)) setSid(ss[0].id);
      } catch (e: any) {
        setMsg({ kind: "err", text: "后端未就绪：" + e.message });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 文件列表
  const loadFiles = async (s = sid, st = status) => {
    if (!s) return;
    try {
      const r = await api.files(s, st);
      setFiles(r.files);
      if (r.files.length && !r.files.some((f) => f.rel === sel)) setSel(r.files[0].rel);
      if (!r.files.length) setSel("");
    } catch (e: any) {
      setMsg({ kind: "err", text: "读取文件列表失败：" + e.message });
    }
  };
  useEffect(() => {
    loadFiles();
    setPage(1);
    api
      .stats(sid)
      .then(setStats)
      .catch(() => setStats(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, status]);

  // diff（分页/只看差异切换）
  useEffect(() => {
    if (!sel || !sid) {
      setDiff(null);
      return;
    }
    let alive = true;
    setLoadingDiff(true);
    api
      .diff(sel, sid, page, PER_PAGE, onlyDiff)
      .then((d) => alive && setDiff(d))
      .catch((e) => alive && setMsg({ kind: "err", text: "读取对比失败：" + e.message }))
      .finally(() => alive && setLoadingDiff(false));
    return () => {
      alive = false;
    };
  }, [sel, sid, page, onlyDiff]);

  // 选中文件滚动到可视区
  useEffect(() => {
    fileRefs.current[sel]?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  // 入库 .md 原文（右栏「源文件」视图用）
  useEffect(() => {
    if (!sel || !sid) {
      setMdText(null);
      return;
    }
    let alive = true;
    api
      .md(sel, sid)
      .then((d) => alive && setMdText(d))
      .catch(() => alive && setMdText(null));
    return () => {
      alive = false;
    };
  }, [sel, sid]);

  // job 轮询
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const t = setInterval(async () => {
      try {
        const j = await api.job(job.id);
        setJob(j);
        if (j.status === "done") {
          loadFiles();
          setPage(1);
          api.stats(sid).then(setStats).catch(() => {});
        }
      } catch {
        /* ignore */
      }
    }, 1200);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status]);

  // 切换文件时回到预览视图（避免新文件落在不合适的对比页）
  useEffect(() => {
    setLeftMode("preview");
    setPage(1);
  }, [sel, sid]);

  const runCompare = async () => {
    if (!sel) return;
    try {
      setNote("");
      const { job_id } = await api.compare(sel, sid);
      setJob({ id: job_id, kind: "compare", rel: sel, status: "queued", progress: 0, message: "排队中", updated_at: "" });
    } catch (e: any) {
      setMsg({ kind: "err", text: "提交对比任务失败：" + e.message });
    }
  };

  const runDeferred = async () => {
    if (!stats?.deferred) return;
    if (!confirm(`将对 ${stats.deferred} 个被延后的大文件逐个重试（放宽时间预算，耗时可能较长）。继续？`)) return;
    try {
      const { job_id } = await api.batchDeferred(sid);
      setJob({ id: job_id, kind: "batch", rel: "", status: "queued", progress: 0,
               message: "排队中（补跑延后文件）", updated_at: "" });
    } catch (e: any) {
      setMsg({ kind: "err", text: "提交补跑失败：" + e.message });
    }
  };

  const showDeferred = async () => {
    try {
      const d = await api.deferred(sid, 300);
      if (!d.count) { alert("当前没有被延后的文件。"); return; }
      const lines = d.items
        .map((x) => `${x.mb != null ? String(x.mb).padStart(7) + "MB" : "       ?"}  ${x.reason}  ${x.rel}`)
        .join("\n");
      alert(`被延后的文件 ${d.count} 个（体积 / 原因 / 路径）：\n\n` + lines);
    } catch (e: any) {
      setMsg({ kind: "err", text: "读取延后清单失败：" + e.message });
    }
  };

  const runBatch = async (force: boolean) => {
    try {
      const { job_id } = await api.batch(sid, force);
      setJob({
        id: job_id,
        kind: "batch",
        rel: "",
        status: "queued",
        progress: 0,
        message: force ? "排队中（重跑全部）" : "排队中（仅评测未评文件）",
        updated_at: "",
      });
    } catch (e: any) {
      setMsg({ kind: "err", text: "提交批量评测失败：" + e.message });
    }
  };

  const doVerdict = async (v: string) => {
    if (!sel) return;
    try {
      await api.review(sel, v, reviewer || "local", note);
      setNote("");
      await loadFiles();
    } catch (e: any) {
      setMsg({ kind: "err", text: "保存裁决失败：" + e.message });
    }
  };

  const badgeOf = (rel: string) => files.find((f) => f.rel === rel);

  return (
    <div className="app">
      <div className="topbar">
        <h1>转换保真度评测台</h1>
        <select value={sid} onChange={(e) => setSid(e.target.value)} title="数据源">
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button onClick={() => setShowMgr(true)}>数据源…</button>
        <button
          className="primary"
          title="对本数据源下尚未评测的文件批量算自动转化率"
          disabled={!!job && (job.status === "queued" || job.status === "running")}
          onClick={() => runBatch(false)}
        >
          批量评测
        </button>
        <button
          title="清空重跑：连同已评测的文件一起重新评分"
          disabled={!!job && (job.status === "queued" || job.status === "running")}
          onClick={() => {
            if (confirm("重跑全部将重新评分所有文件（含已评测），耗时较长。继续？")) runBatch(true);
          }}
        >
          重跑全部
        </button>
        <button
          title="对之前被延后（体积过大或抽取过慢）的文件逐个重试，放宽时间预算"
          disabled={!!job && (job.status === "queued" || job.status === "running")}
          onClick={runDeferred}
        >
          补跑延后{stats?.deferred ? `(${stats.deferred})` : ""}
        </button>
        <button
          title="查看被延后的文件清单（体积 / 原因 / 路径）"
          onClick={showDeferred}
        >
          延后清单
        </button>
        <button
          className="primary"
          title="无法自动比对的文件（扫描件/图片/CAD/压缩包等）：入不入库由你决定"
          onClick={() => setShowDecide(true)}
        >
          待决定{stats?.decisions?.pending ? `(${stats.decisions.pending})` : ""}
        </button>
        <button
          title="原转换产物是二进制打捞垃圾的文件：用真实提取结果（CAD 文字 / OCR）重写 .md，原文件自动备份"
          onClick={() => setShowSalvage(true)}
        >
          需重新转换{stats?.salvage ? `(${stats.salvage})` : ""}
        </button>
        {stats && (
          <span className="score" title="已评测 / 全部文件 · 平均自动分 · 已人工裁决 · 延后大文件">
            已评测 {stats.evaluated}/{stats.total}
            {stats.avg_score != null ? ` · 均分 ${stats.avg_score}%` : ""} · 已裁 {stats.reviewed}
            {stats.deferred ? ` · 延后 ${stats.deferred}` : ""}
            {stats.decisions?.pending ? ` · 待决定 ${stats.decisions.pending}` : ""}
            {stats.salvage ? ` · 需重转 ${stats.salvage}` : ""}
            {stats.totals && stats.totals.src_chars > 0 && (
              <span
                className="score"
                title="全库源文件抽取字数 → 入库 .md 字数（不含 front-matter / 注释 / 标题）"
              >
                {" "}
                · 总字数 {stats.totals.src_chars.toLocaleString()}→{stats.totals.md_chars.toLocaleString()}
                {stats.totals.char_ratio != null && `（保留 ${stats.totals.char_ratio}%）`}
              </span>
            )}
          </span>
        )}
        <label className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          上传新文件
          <input
            type="file"
            style={{ display: "none" }}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                const r = await api.upload(f, sid);
                setMsg({ kind: "warn", text: `已上传 ${r.rel} 到源目录，等待转换生成 .md` });
              } catch (err: any) {
                setMsg({ kind: "err", text: "上传失败：" + err.message });
              }
              e.target.value = "";
            }}
          />
        </label>
        <div className="spacer" />
        {job && (job.status === "queued" || job.status === "running") && (
          <div className="progress-wrap">
            <div className="progress-bar">
              <i style={{ width: `${job.progress}%` }} />
            </div>
            <span>
              {job.progress}% · {job.message || "处理中"}
            </span>
          </div>
        )}
        {job && job.status === "done" && <span className="score">上一任务完成 ✓</span>}
        {job && job.status === "error" && (
          <span className={`badge ${job.message?.includes("中断") ? "need_review" : "rejected"}`}>
            {job.message?.includes("中断") ? "任务被重启中断" : "任务失败"}：{job.message}
          </span>
        )}
      </div>

      {msg && (
        <div className={`notice ${msg.kind === "err" ? "err" : ""}`} onClick={() => setMsg(null)}>
          {msg.text}（点击关闭）
        </div>
      )}

      <div className="main">
        <div className="sidebar">
          <div className="sidebar-head">
            <input
              type="search"
              placeholder="筛选当前数据源下已转 .md 的文件…"
              onChange={(e) => {
                const q = e.target.value.toLowerCase();
                setFiles((prev) =>
                  q ? prev.filter((f) => f.rel.toLowerCase().includes(q)) : prev
                );
              }}
            />
            <div className="filter-row">
              {STATUS_TABS.map((t) => (
                <button
                  key={t.key || "all"}
                  className={`chip ${status === t.key ? "active" : ""}`}
                  onClick={() => setStatus(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div className="file-list">
            {files.length === 0 && <div className="empty">该筛选条件下暂无文件</div>}
            {files.map((f) => (
              <div
                key={f.rel}
                ref={(el) => (fileRefs.current[f.rel] = el)}
                className={`file-item ${sel === f.rel ? "sel" : ""}`}
                onClick={() => {
                  setSel(f.rel);
                  setPage(1);
                }}
              >
                <div className="name">{f.rel.split("/").pop()}</div>
                <div className="path">{f.rel}</div>
                <div className="meta">
                  <span className={`badge ${f.state}`}>{f.label}</span>
                  <span className="score">{f.auto_score != null ? `自动 ${f.auto_score}%` : "无自动分"}</span>
                  {f.src_chars != null && f.md_chars != null && (
                    <span
                      className="score"
                      title={`源 ${f.src_chars.toLocaleString()} 字 → md ${f.md_chars.toLocaleString()} 字`}
                    >
                      字 {f.src_chars.toLocaleString()}→{f.md_chars.toLocaleString()}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="workspace">
          {!sel ? (
            <div className="empty">从左侧选择一个文件开始核对</div>
          ) : (
            <>
              <div className="file-head">
                <div className="rel">{sel}</div>
                <div className="kv">
                  <span>
                    状态 <span className={`badge ${badgeOf(sel)?.state || "unreviewed"}`}>{badgeOf(sel)?.label || "未审"}</span>
                  </span>
                  <span>
                    自动分 <b>{badgeOf(sel)?.auto_score != null ? badgeOf(sel)!.auto_score + "%" : "—"}</b>
                  </span>
                  <WordsMeter b={badgeOf(sel)} />
                  <span className="legend">
                    <span>
                      <i style={{ background: "var(--green-bg)", border: "1px solid var(--green-bd)" }} />
                      两侧一致
                    </span>
                    <span>
                      <i style={{ background: "var(--red-bg)", border: "1px solid var(--red-bd)" }} />
                      源有 / md 无（可能漏转）
                    </span>
                    <span>
                      <i style={{ background: "var(--amber-bg)", border: "1px solid #f2d99a" }} />
                      md 多出
                    </span>
                  </span>
                </div>
              </div>

              <div className="toolbar">
                <button className="primary" onClick={runCompare} disabled={!!job && job.status === "running"}>
                  运行自动评测
                </button>
                <button
                  className={leftMode === "preview" ? "active" : ""}
                  onClick={() => setLeftMode("preview")}
                  title="左栏显示源文件原貌（PDF/图片/表格/幻灯片/邮件/CAD），右栏显示转换后的 .md"
                >
                  源文件预览
                </button>
                <button
                  className={leftMode === "text" ? "active" : ""}
                  onClick={() => setLeftMode("text")}
                  title="逐行对齐：源文与 .md 一致为绿、缺失为红，可只看差异"
                >
                  逐行比对
                </button>
                {leftMode === "text" && (
                  <>
                    <button className={onlyDiff ? "active" : ""} onClick={() => { setOnlyDiff(!onlyDiff); setPage(1); }}>
                      只看差异
                    </button>
                    <button className={!onlyDiff ? "active" : ""} onClick={() => { setOnlyDiff(false); setPage(1); }}>
                      全部内容
                    </button>
                  </>
                )}
                <div className="spacer" />
                <span className="hint">
                  {leftMode === "preview"
                    ? mdText
                      ? `md ${mdText.chars.toLocaleString()} 字 / ${mdText.words.toLocaleString()} 词`
                      : loadingDiff
                        ? "加载中…"
                        : ""
                    : loadingDiff
                      ? "加载中…"
                      : diff?.not_applicable
                        ? "不适用"
                        : `共 ${diff?.total ?? 0} 条 · 第 ${page}/${diff?.pages ?? 1} 页`}
                </span>
                {leftMode === "text" && (
                  <>
                    <button disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                      上一页
                    </button>
                    <button disabled={!diff || page >= diff.pages} onClick={() => setPage((p) => p + 1)}>
                      下一页
                    </button>
                  </>
                )}
              </div>

              {leftMode === "preview" ? (
                <div className="split">
                  <div className="pane">
                    <SourcePreview sid={sid} rel={sel} onTextMode={() => setLeftMode("text")} />
                  </div>
                  <div className="pane">
                    <div className="pane-head">
                      <b>入库 .md</b>
                      {mdText?.salvage && (
                        <span className="badge rejected" title="原产物是二进制字符串打捞，建议用「需重新转换」重写">
                          salvage 无效产物
                        </span>
                      )}
                      <div className="spacer" />
                      {mdText && !mdText.missing && (
                        <span className="score">
                          {mdText.chars.toLocaleString()} 字 · {mdText.words.toLocaleString()} 词
                        </span>
                      )}
                    </div>
                    <div className="pane-body">
                      {mdText === null ? (
                        <div className="empty">读取 .md 中…</div>
                      ) : mdText.missing ? (
                        <div className="empty">
                          该文件还没有对应的 .md —— 请先运行「批量评测」触发转换，或用「需重新转换」生成。
                        </div>
                      ) : (
                        <MdView md={mdText} />
                      )}
                    </div>
                  </div>
                </div>
              ) : (
              <div className="diff-wrap">
                {diff?.not_applicable ? (
                  <div className="empty">
                    该文件不适用文本对比：{diff.reason}（图纸 / 视频 / 无文本层）—— 切到「源文件预览」查看原貌
                  </div>
                ) : (
                  <>
                    {diff?.verdict && <div className="notice">{diff.verdict}</div>}
                    <div className="diff-head">
                        <div>#</div>
                        <div>源文件（引擎 B 独立抽取）</div>
                        <div>#</div>
                        <div className="mid">入库 .md（已剥离管线元数据）</div>
                      </div>
                      {(diff?.segments || []).map((s: Segment, i: number) => (
                        <div key={i} className={`diff-row ${s.status}`}>
                          <div className="no">{s.src_no ?? ""}</div>
                          <div className="src">{s.src ?? ""}</div>
                          <div className="no">{s.md_no ?? ""}</div>
                          <div className={`mid md ${s.md ? "" : "gone"}`}>{s.md ?? "（转换结果中无对应内容）"}</div>
                        </div>
                      ))}
                      {diff && diff.segments.length === 0 && (
                        <div className="empty">
                          {onlyDiff ? "没有差异 —— 两侧内容全部对齐" : "无内容"}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              <div className="verdictbar">
                <span style={{ fontSize: 12, color: "var(--muted)" }}>人工裁决</span>
                <button
                  className={`vbtn ok ${badgeOf(sel)?.trust_state === "ok" ? "sel" : ""}`}
                  onClick={() => doVerdict("ok")}
                >
                  一致
                </button>
                <button
                  className={`vbtn diff ${badgeOf(sel)?.trust_state === "diff_big" ? "sel" : ""}`}
                  onClick={() => doVerdict("diff_big")}
                >
                  差异大
                </button>
                <button
                  className={`vbtn rej ${badgeOf(sel)?.trust_state === "rejected" ? "sel" : ""}`}
                  onClick={() => doVerdict("rejected")}
                >
                  不接受
                </button>
                {badgeOf(sel)?.trust_state && (
                  <button onClick={() => doVerdict("")} title="撤销裁决，回到未审">
                    撤销
                  </button>
                )}
                <input
                  className="reviewer"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                  placeholder="审核人"
                  title="审核人（写入审计日志）"
                />
                <input
                  className="note"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="裁决备注（可选，写入审计日志）"
                />
                <span className="score">{badgeOf(sel)?.badge}</span>
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
          onChanged={async () => {
            api.stats(sid).then(setStats).catch(() => {});
          }}
          onReeval={(rel) => {
            // 入库后对可自动处理的格式立即重跑识别+评测（异步任务，不阻塞面板）
            api
              .compare(rel, sid)
              .then(({ job_id }) => {
                setJob({ id: job_id, kind: "compare", rel, status: "queued", progress: 0, message: "排队中（重跑识别）", updated_at: "" });
              })
              .catch(() => {});
          }}
        />
      )}

      {showSalvage && (
        <SalvagePanel
          sid={sid}
          onClose={() => setShowSalvage(false)}
          onChanged={async () => {
            setStats(await api.stats(sid));
            setFiles((await api.files(sid, status)).files);
          }}
        />
      )}

      {showMgr && (
        <SourceManager
          sources={sources}
          onClose={() => setShowMgr(false)}
          onSaved={async () => {
            setSources(await api.sources());
            setShowMgr(false);
          }}
          onPick={(which) => setPicker(which)}
          draft={draft}
          setDraft={setDraft}
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
