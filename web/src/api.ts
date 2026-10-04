import type {
  AlignResp,
  Badge,
  BrowseResp,
  DecisionItem,
  Job,
  MdResp,
  MarksResp,
  PreviewResp,
  Reviewer,
  SalvageItem,
  Source,
  Stats,
  TreeResp,
} from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch {
      /* 非 JSON 错误体，保留 statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return req<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

const q = (o: Record<string, string | number | boolean | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined) p.set(k, String(v));
  return p.toString();
};

export const api = {
  health: () => req<{ ok: boolean; workers: number }>("/health"),
  sources: () => req<Source[]>("/sources"),
  saveSource: (s: Source) => post<Source>("/sources", s),
  deleteSource: (id: string) => req<{ ok: boolean }>(`/sources/${id}`, { method: "DELETE" }),
  browse: (path: string) => req<BrowseResp>(`/browse?${q({ path })}`),

  /** 源目录结构树（保留原目录层级）。 */
  tree: (sid: string, status = "", search = "") =>
    req<TreeResp>(`/tree?${q({ sid, status, q: search })}`),

  /** 扁平文件列表（状态筛选 + 计数用）。 */
  files: (sid: string, status = "") =>
    req<{ count: number; total: number; files: Badge[] }>(`/files?${q({ sid, status })}`),

  /** 逐行状态。status[i] 与 md().lines[i] 同下标。 */
  align: (rel: string, sid: string) =>
    req<AlignResp>(`/align?${q({ rel, sid })}`),

  /** 源文件该页的归一化坐标 + 命中状态（左栏绿色高亮）。 */
  marks: (rel: string, sid: string, page: number) =>
    req<MarksResp>(`/marks?${q({ rel, sid, page })}`),

  /** 入库 md 正文（lines 与 align.status 同下标）。 */
  md: (rel: string, sid: string) => req<MdResp>(`/md?${q({ rel, sid })}`),

  compare: (rel: string, sid: string) => post<{ job_id: string }>(`/compare?${q({ rel, sid })}`),
  batch: (sid: string, force: boolean) => post<{ job_id: string }>(`/batch?${q({ sid, force })}`),
  batchDeferred: (sid: string) => post<{ job_id: string }>(`/batch?${q({ sid, mode: "defer" })}`),
  deferred: (sid: string, limit = 200) =>
    req<{ count: number; items: { rel: string; mb: number | null; reason: string; at: string }[] }>(
      `/deferred?${q({ sid, limit })}`
    ),

  salvage: (limit = 800) => req<{ count: number; items: SalvageItem[] }>(`/salvage?${q({ limit })}`),
  reconvert: (rels: string[], sid: string) =>
    post<{ ok: number; failed: number; items: { rel: string; msg: string }[] }>("/reconvert", {
      rels,
      sid,
      backup: true,
    }),

  decisions: (sid: string, decision = "") =>
    req<{ count: number; items: DecisionItem[] }>(`/decisions?${q({ sid, decision, limit: 800 })}`),
  setDecision: (rel: string, decision: string, reviewer: string, note = "") =>
    post<{ rel: string; decision: string | null }>(`/decision/${rel}`, {
      decision,
      reviewer,
      note,
    }),

  job: (jid: string) => req<Job>(`/job/${encodeURIComponent(jid)}`),
  stats: (sid: string) => req<Stats>(`/stats?${q({ sid })}`),

  previewMeta: (rel: string, sid: string) => req<PreviewResp>(`/preview/meta?${q({ rel, sid })}`),
  preview: (rel: string, sid: string, page: number, sheet = 0) =>
    req<PreviewResp>(`/preview?${q({ rel, sid, page, sheet })}`),
  previewImg: (rel: string, sid: string, page: number, dpi = 110) =>
    `${BASE}/preview/img?${q({ rel, sid, page, dpi })}`,

  reconvertAll: (sid: string) => post<{ job_id: string }>(`/reconvert/all?${q({ sid })}`),

  review: (rel: string, verdict: string, reviewer: string, note: string) =>
    post<Badge & { rev_no: number }>(`/review/${rel}`, { verdict, reviewer, note }),

  /** 审核人名单 + 每人工作量。 */
  reviewers: () => req<{ items: Reviewer[] }>("/reviewers"),
  saveReviewer: (r: { id?: string; name: string; role?: string; enabled?: boolean }) =>
    post<Reviewer>("/reviewers", r),
  deleteReviewer: (id: string) =>
    req<{ ok: boolean }>(`/reviewers/${encodeURIComponent(id)}`, { method: "DELETE" }),

  upload: async (file: File, sid: string) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/ingest/upload?${q({ sid })}`, { method: "POST", body: fd });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};
