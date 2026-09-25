export interface DocumentModel {
  document_id: string;
  original_name: string;
  size_bytes: number;
  sha256: string;
  page_count: number;
  ingested_at: string;
  metadata: Record<string, string>;
  duplicate: boolean;
}

export type BlockType =
  | "paragraph" | "heading" | "formula" | "table" | "list"
  | "skipped_visual" | "other";

export interface Block {
  block_id: string;
  type: BlockType;
  text: string | null;
  order: number;
  bbox: number[] | null;
  confidence: number | null;
}

export interface Issue {
  issue_id: string;
  block_id?: string | null;
  type: string;
  description: string;
  status?: string;
  resolved_at?: string | null;
  resolved_reason?: string | null;
  checked_revision?: string | null;
  history_only?: boolean;
}

export interface PageResult {
  job_id: string;
  document_id?: string;
  pdf_page: number;
  printed_page: number | null;
  status: string;
  method: string;
  review_status: string;
  error: string | null;
  attempt: number;
  reprocess_state: string;
  revision_id: string | null;
  blocks: Block[];
  coordinate_space: { unit: string; width: number; height: number } | null;
  issues: Issue[];
  open_issues?: Issue[];
  engine_meta: Record<string, unknown>;
}

export interface PageRun {
  page_no: number;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "NEEDS_REVIEW" | "FAILED" | "INTERRUPTED";
  method: string;
  attempt: number;
  duration_s: number | null;
  error: string | null;
  active_revision_id: string | null;
  review_status: string;
}

export interface Job {
  job_id: string;
  document_id: string;
  document_name: string;
  document_page_count: number;
  selected_pages: number[];
  mode: string;
  config_hash: string;
  status: string;
  current_page: number | null;
  succeeded_pages: number;
  failed_pages: number;
  pending_pages: number;
  eta_s: number | null;
  model_phase: string | null;
  process_phase: string | null;
  pages: PageRun[];
}

export interface RevisionInfo {
  revision_id: string;
  kind: string;
  origin: string;
  hash: string;
  created_at: string;
  active: boolean;
}

export interface SelectionResult {
  selected_pages: number[];
  selected_count: number;
  document_page_count: number;
  warnings: string[];
}
