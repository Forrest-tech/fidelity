export type TrustState =
  | "trusted"
  | "need_review"
  | "diff_big"
  | "rejected"
  | "unreviewed";

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

export interface FileRow extends Badge {}

export type SegStatus = "match" | "src_only" | "md_only" | "changed";

export interface Segment {
  status: SegStatus;
  src: string | null;
  md: string | null;
  src_no?: number | null;
  md_no?: number | null;
}

export interface DiffResp {
  rel: string;
  not_applicable: boolean;
  reason?: string;
  segments: Segment[];
  total: number;
  page: number;
  pages: number;
  src_chars?: number;
  md_chars?: number;
  src_words?: number;
  md_words?: number;
  by_status?: Record<string, number>;
  /** 低分原因的人话解释（源文本身没文字 / md 超短 / md 过长…）。 */
  verdict?: string;
}

/** 源文件预览：按格式渲染出的内容。 */
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

/** 入库 .md 原文。 */
export interface MdResp {
  rel: string;
  text: string;
  missing: boolean;
  salvage: boolean;
  chars: number;
  words: number;
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

export interface DecisionStats {
  pending: number;
  include: number;
  exclude: number;
}

/** 原转换产物是「二进制字符串打捞」的文件 —— 重新转换候选。 */
export interface SalvageItem {
  rel: string;
  auto_score: number | null;
  engine_b: string;
  fail_reasons: string;
}
