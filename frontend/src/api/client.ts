import type { DocumentModel, Job, PageResult, RevisionInfo, SelectionResult } from "../types/api";

let sessionToken = "";

async function req<T>(path: string, init: RequestInit = {}, quiet = false): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  if (init.method && init.method !== "GET" && init.method !== "HEAD") {
    headers.set("x-pdfcleaner-token", sessionToken);
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail?.message ?? JSON.stringify(body?.detail ?? body);
    } catch {
      /* giữ nguyên */
    }
    if (!quiet) throw new Error(detail);
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async init(): Promise<void> {
    const r = await req<{ token: string }>("/api/session");
    sessionToken = r.token;
  },
  health: () => req<Record<string, unknown>>("/api/health"),
  listDocuments: () => req<{ items: DocumentModel[] }>("/api/documents"),
  uploadDocument: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<DocumentModel>("/api/documents", { method: "POST", body: fd });
  },
  validateSelection: (docId: string, body: object) =>
    req<SelectionResult>(`/api/documents/${docId}/selection/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, true),
  previewUrl: (docId: string, page: number) =>
    `/api/documents/${docId}/pages/${page}/preview`,
  createJob: (document_id: string, selected_pages: number[], ocr_again: boolean) =>
    req<Job>("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id, selected_pages, mode: "auto_text_formula", ocr_again }),
    }),
  startJob: (id: string) => req<Job>(`/api/jobs/${id}/start`, { method: "POST" }),
  getJob: (id: string) => req<Job>(`/api/jobs/${id}`),
  pauseJob: (id: string) => req<Job>(`/api/jobs/${id}/pause`, { method: "POST" }),
  cancelJob: (id: string) => req<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  resumeJob: (id: string) => req<Job>(`/api/jobs/${id}/resume`, { method: "POST" }),
  retryPage: (id: string, page_no: number) =>
    req<Job>(`/api/jobs/${id}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_no }),
    }),
  getPage: (jobId: string, page: number) =>
    req<PageResult>(`/api/jobs/${jobId}/pages/${page}`),
  editPage: (jobId: string, page: number, base_revision_id: string, blocks: object[]) =>
    req<{ revision_id: string }>(`/api/jobs/${jobId}/pages/${page}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_revision_id, blocks }),
    }),
  reprocessPage: (jobId: string, page: number) =>
    req<{ state: string }>(`/api/jobs/${jobId}/pages/${page}/reprocess`, { method: "POST" }),
  revisions: (jobId: string, page: number) =>
    req<{ items: RevisionInfo[] }>(`/api/jobs/${jobId}/pages/${page}/revisions`),
  useRevision: (jobId: string, page: number, revision_id: string) =>
    req<PageResult>(`/api/jobs/${jobId}/pages/${page}/use_revision?revision_id=${revision_id}`,
      { method: "POST" }),
  revertPage: (jobId: string, page: number) =>
    req<PageResult>(`/api/jobs/${jobId}/pages/${page}/revert`, { method: "POST" }),
  resolveIssue: (jobId: string, page: number, issueId: string, reason: string, baseRevisionId?: string) =>
    req<PageResult>(`/api/jobs/${jobId}/pages/${page}/issues/${issueId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, ...(baseRevisionId ? { base_revision_id: baseRevisionId } : {}) }),
    }),
  patchMetadata: (docId: string, metadata: Record<string, string>) =>
    req<{ document_id: string; metadata: Record<string, string> }>(
      `/api/documents/${docId}/metadata`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(metadata),
      }),
  createExport: (jobId: string, format: string) =>
    req<{ export_id: string; filename: string; included_pages: number[]; missing_pages: number[]; partial: boolean }>(
      `/api/jobs/${jobId}/exports?format=${format}`, { method: "POST" }),
  downloadUrl: (exportId: string) => `/api/exports/${exportId}/download`,
};
