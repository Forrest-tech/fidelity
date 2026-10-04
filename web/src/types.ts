export type TrustState =
  | "trusted"
  | "need_review"
  | "diff_big"
  | "rejected"
  | "unreviewed";

/** 逐行比对状态。unmatched = 该行在源文里找不到对应（多为 md 结构性内容）。 */
export type LineStatus = "match" | "changed" | "md_only" | "src_only" | "unmatched";

export interface Source {
  id: string;
  name: string;
  src_root: string;
  md_root: string;
  enabled?: boolean;
}

export interface Badge {
  rel: string;
  state: TrustState;
  label: string;
  badge: string;
  auto_score: number | null;
  trust_state: string | null;
  reviewer: string | null;
  status?: string | null;
  flags?: string;
  src_chars?: number | null;
  md_chars?: number | null;
  src_words?: number | null;
  md_words?: number | null;
}

export interface Reviewer {
  id: string;
  name: string;
  role: string;
  enabled: boolean;
  /** 历史数据里存在但未登记进名单的审核人 */
  orphan?: boolean;
  verdicts: number;
  ok: number;
  diff_big: number;
  rejected: number;
  decisions: number;
}

/** 源目录树节点。 */
export interface TreeFile {
  rel: string;
  name: string;
  ext: string;
  state: TrustState;
  label: string;
  auto_score: number | null;
}

export interface TreeCounts {
  all: number;
  trusted: number;
  need_review: number;
  diff_big: number;
  rejected: number;
  unreviewed: number;
}

export interface TreeDir {
  name: string;
  dirs: TreeDir[];
  files: TreeFile[];
  counts: TreeCounts;
}

export interface TreeResp {
  name: string;
  dirs: TreeDir[];
  files: TreeFile[];
  counts: TreeCounts;
}

/**
 * /api/align 的返回：只含状态与页码，**不含正文**。
 * `status[i]` 与 /api/md 的 `lines[i]` 一一对应（后端保证同一下标语义）。
 */
export interface AlignResp {
  rel: string;
  not_applicable: boolean;
  reason?: string;
  status: LineStatus[];
  src_page: (number | null)[];
  truncated: boolean;
  total_lines: number;
  by_status?: Record<string, number>;
  src_chars?: number;
  md_chars?: number;
  verdict?: string;
}

/** 源文件页面内某一行的归一化坐标（0..1）+ 命中状态。 */
export interface MarkLine {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  status: LineStatus | "unmatched";
}

export interface MarksResp {
  rel: string;
  page: number;
  supported: boolean;
  reason?: string;
  page_w?: number;
  page_h?: number;
  lines: MarkLine[];
  src_line_count?: number;
}

/** 入库 .md 正文（已剥离管线伪影）。lines 与 align.status 同下标。 */
export interface MdResp {
  rel: string;
  text: string;
  lines: string[];
  missing: boolean;
  salvage: boolean;
  chars: number;
  words: number;
}

export interface PreviewResp {
  rel?: string;
  ext?: string;
  kind: "image" | "html" | "text" | "unsupported" | "missing" | "list";
  page?: number;
  pages?: number;
  total_pages?: number;
  engine?: string;
  note?: string;
  html?: string;
  text?: string;
  sheets?: string[];
  sheet?: number;
  items?: { name: string; size: number }[];
}

export interface Totals {
  files: number;
  src_chars: number;
  md_chars: number;
  src_words: number;
  md_words: number;
  char_ratio: number | null;
  word_ratio: number | null;
}

export interface Stats {
  total: number;
  evaluated: number;
  avg_score: number | null;
  reviewed: number;
  reviewed_pct: number;
  deferred: number;
  by_state: Record<string, number>;
  decisions: DecisionStats;
  salvage: number;
  totals: Totals;
}

export interface DecisionStats {
  pending: number;
  include: number;
  exclude: number;
}

export interface Job {
  id: string;
  kind: string;
  rel: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  updated_at: string;
}

export interface BrowseResp {
  cwd: string;
  dirs: string[];
  files: string[];
}

export interface DecisionItem {
  rel: string;
  ext: string;
  mb: number;
  reason: string;
  engine: string;
  decision: string | null;
  decided_at: string | null;
}

export interface SalvageItem {
  rel: string;
  auto_score: number | null;
  engine_b: string;
  fail_reasons: string;
}
