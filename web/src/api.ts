import type {
  Badge,
  BrowseResp,
  DecisionItem,
  DiffResp,
  Job,
  MdResp,
  PreviewResp,
  SalvageItem,
  Source,
  Totals,
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
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ ok: boolean; workers: number }>("/health"),
  sources: () => req<Source[]>("/sources"),
  saveSource: (s: Source) =>
    req<Source>("/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
    }),
  deleteSource: (id: string) => req<{ ok: boolean }>(`/sources/${id}`, { method: "DELETE" }),
  browse: (path: string) => req<BrowseResp>(`/browse?path=${encodeURIComponent(path)}`),

  files: (sid: string, status: string) =>
    req<{ count: number; files: Badge[] }>(
      `/files?sid=${encodeURIComponent(sid)}&status=${encodeURIComponent(status)}`
    ),

  compare: (rel: string, sid: string) =>
    req<{ job_id: string }>(`/compare?rel=${encodeURIComponent(rel)}&sid=${encodeURIComponent(sid)}`, {
      method: "POST",
    }),
  batch: (sid: string, force: boolean) =>
    req<{ job_id: string }>(
      `/batch?sid=${encodeURIComponent(sid)}&force=${force}`,
      { method: "POST" }
    ),
  batchDeferred: (sid: string) =>
    req<{ job_id: string }>(
      `/batch?sid=${encodeURIComponent(sid)}&mode=defer`,
      { method: "POST" }
    ),
  deferred: (sid: string, limit = 200) =>
    req<{ count: number; items: { rel: string; mb: number | null; reason: string; at: string }[] }>(
      `/deferred?sid=${encodeURIComponent(sid)}&limit=${limit}`
    ),

  salvage: (limit = 800) =>
    req<{ count: number; items: SalvageItem[] }>(`/salvage?limit=${limit}`),

  reconvert: (rels: string[], sid: string) =>
    req<{ ok: number; failed: number; items: { rel: string; msg: string }[] }>("/reconvert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rels, sid, backup: true }),
    }),

  decisions: (sid: string, decision = "") =>
    req<{ count: number; items: DecisionItem[] }>(
      `/decisions?sid=${encodeURIComponent(sid)}&decision=${encodeURIComponent(decision)}&limit=800`
    ),
  setDecision: (rel: string, decision: string, reviewer: string, note = "") =>
    req<{ rel: string; decision: string | null }>(`/decision/${rel}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer, note }),
    }),
  job: (jid: string) => req<Job>(`/job/${encodeURIComponent(jid)}`),
  stats: (sid: string) =>
    req<{ total: number; evaluated: number; avg_score: number | null; reviewed: number; deferred: number; by_state: Record<string, number> }>(
      `/stats?sid=${encodeURIComponent(sid)}`
    ),

  diff: (rel: string, sid: string, page: number, perPage: number, onlyDiff: boolean) =>
    req<DiffResp>(
      `/diff?rel=${encodeURIComponent(rel)}&sid=${encodeURIComponent(sid)}` +
        `&page=${page}&per_page=${perPage}&only_diff=${onlyDiff}`
    ),

  md: (rel: string, sid: string) =>
    req<MdResp>(`/md?rel=${encodeURIComponent(rel)}&sid=${encodeURIComponent(sid)}`),

  previewMeta: (rel: string, sid: string) =>
    req<PreviewResp>(`/preview/meta?rel=${encodeURIComponent(rel)}&sid=${encodeURIComponent(sid)}`),

  preview: (rel: string, sid: string, page: number, sheet = 0) =>
    req<PreviewResp>(
      `/preview?rel=${encodeURIComponent(rel)}&sid=${encodeURIComponent(sid)}` +
        `&page=${page}&sheet=${sheet}`
    ),

  /** 图像型预览的直接 URL（供 <img src> 使用，带缓存头）。 */
  previewImg: (rel: string, sid: string, page: number, dpi = 110) =>
    `/api/preview/img?rel=${encodeURIComponent(rel)}&sid=${encodeURIComponent(sid)}` +
    `&page=${page}&dpi=${dpi}`,

  reconvertAll: (sid: string) =>
    req<{ job_id: string }>(`/reconvert/all?sid=${encodeURIComponent(sid)}`, { method: "POST" }),

  review: (rel: string, verdict: string, reviewer: string, note: string) =>
    req<Badge & { rev_no: number }>(`/review/${rel}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict, reviewer, note }),
    }),

  upload: async (file: File, sid: string) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/ingest/upload?sid=${encodeURIComponent(sid)}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};
