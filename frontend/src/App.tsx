import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import MarkdownView from "./components/MarkdownView";
import type { Block, DocumentModel, Job, PageResult } from "./types/api";

type Step = "docs" | "select" | "progress" | "view";

const STEP_LABELS: Record<Step, number> = { docs: 1, select: 2, progress: 3, view: 4 };

function fmtBytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const STATUS_VI: Record<string, string> = {
  PENDING: "Chờ", RUNNING: "Đang xử lý", SUCCEEDED: "Đã xong, chưa duyệt",
  NEEDS_REVIEW: "Cần kiểm tra", FAILED: "Lỗi", INTERRUPTED: "Gián đoạn",
};
const METHOD_VI: Record<string, string> = {
  ocr: "OCR", direct: "Lớp chữ PDF", cached: "OCR (cache)", unknown: "—",
};
const PROCESS_VI: Record<string, string> = {
  reading: "Đang đọc trang", ocr: "Đang OCR", saving: "Đang lưu kết quả",
};
function statusVi(s: string) { return STATUS_VI[s] ?? s; }
function methodVi(m: string) { return METHOD_VI[m] ?? m; }

export default function App() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("docs");

  const [docs, setDocs] = useState<DocumentModel[]>([]);
  const [doc, setDoc] = useState<DocumentModel | null>(null);

  const [fromPage, setFromPage] = useState("");
  const [toPage, setToPage] = useState("");
  const [expr, setExpr] = useState("");
  const [allPages, setAllPages] = useState(false);
  const [ocrAgain, setOcrAgain] = useState(false);
  const [selection, setSelection] = useState<{ pages: number[]; count: number; warnings: string[] } | null>(null);
  const [selError, setSelError] = useState<string | null>(null);

  const [job, setJob] = useState<Job | null>(null);
  const [viewPage, setViewPage] = useState<number | null>(null);
  const [drag, setDrag] = useState(false);
  const [ocrReady, setOcrReady] = useState(true);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    api.init()
      .then(() => Promise.all([api.listDocuments(), api.health()]))
      .then(([d, h]) => {
        setDocs(d.items);
        if (typeof h.ocr_ready === "boolean") setOcrReady(h.ocr_ready as boolean);
        setReady(true);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const refreshDocs = useCallback(() => {
    api.listDocuments().then((d) => setDocs(d.items)).catch((e) => setError(String(e)));
  }, []);

  async function handleFiles(files: FileList | File[]) {
    setError(null);
    for (const f of Array.from(files)) {
      if (!f.name.toLowerCase().endsWith(".pdf")) continue;
      try {
        await api.uploadDocument(f);
      } catch (e) {
        setError(`Lỗi với ${f.name}: ${String(e)}`);
      }
    }
    refreshDocs();
  }

  function pickDoc(d: DocumentModel) {
    setDoc(d);
    setSelection(null);
    setFromPage("");
    setToPage("");
    setExpr("");
    setAllPages(false);
    setStep("select");
  }

  async function validateSelection() {
    if (!doc) return;
    setSelError(null);
    try {
      const body = allPages
        ? { all_pages: true }
        : expr.trim()
          ? { expression: expr }
          : { from_page: fromPage ? Number(fromPage) : null, to_page: toPage ? Number(toPage) : null };
      const r = await api.validateSelection(doc.document_id, body);
      setSelection({ pages: r.selected_pages, count: r.selected_count, warnings: r.warnings });
    } catch (e) {
      setSelection(null);
      setSelError(String(e));
    }
  }

  useEffect(() => {
    if (step === "select" && !allPages) void validateSelection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromPage, toPage, expr, allPages]);

  async function runJob() {
    if (!doc || !selection || selection.count === 0) return;
    setError(null);
    try {
      const j = await api.createJob(doc.document_id, selection.pages, ocrAgain);
      await api.startJob(j.job_id);
      setJob(j);
      setStep("progress");
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (step !== "progress" || !job) return;
    const id = job.job_id;
    const tick = async () => {
      try {
        const j = await api.getJob(id);
        setJob(j);
        if (["COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "FAILED", "PAUSED", "INTERRUPTED"].includes(j.status)) {
          if (pollRef.current) window.clearInterval(pollRef.current);
        }
      } catch (e) {
        setError(String(e));
      }
    };
    void tick();
    pollRef.current = window.setInterval(tick, 1500);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [step, job?.job_id]);

  const jobDone = job != null && ["COMPLETED", "COMPLETED_WITH_ERRORS"].includes(job.status);

  if (!ready) {
    return <main><div className="card">Đang kết nối backend…</div>{error && <div className="banner-err">{error}</div>}</main>;
  }

  const running = job != null && ["RUNNING", "PAUSE_REQUESTED"].includes(job.status);

  return (
    <>
      <header className="topbar">
        <h1>PDF Cleaner — trích xuất OCR sang Markdown / JSON</h1>
        <div className="steps">
          Bước {STEP_LABELS[step]}/4:{" "}
          {{ docs: "Mở tài liệu", select: "Chọn trang", progress: "Theo dõi xử lý", view: "Xem & tải kết quả" }[step]}
        </div>
      </header>
      <main>
        {error && (
          <div className="banner-err">
            {error}{" "}
            <button className="ghost" onClick={() => { void navigator.clipboard?.writeText(error); }}>
              Sao chép
            </button>
          </div>
        )}
        {!ocrReady && (
          <div className="banner-warn">
            ⚠️ Model OCR chưa sẵn sàng trên máy này — <b>OCR sẽ báo lỗi rõ</b> khi trang cần nhận dạng,
            nhưng bạn vẫn mở được ứng dụng để xem kết quả cũ hoặc trích xuất trực tiếp từ lớp chữ PDF.
            Hãy chạy PaddleOCR một lần để tải model, rồi khởi động lại tool.
          </div>
        )}

        {step === "docs" && (
          <div className="card">
            <div
              className={`dropzone${drag ? " drag" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); void handleFiles(e.dataTransfer.files); }}
            >
              <p>Kéo thả PDF vào đây, hoặc:</p>
              <input
                type="file"
                accept="application/pdf"
                multiple
                id="pdfinput"
                style={{ display: "none" }}
                onChange={(e) => e.target.files && void handleFiles(e.target.files)}
              />
              <label htmlFor="pdfinput"><button type="button">Chọn PDF</button></label>
              <p className="muted">Thêm file không tự khởi động OCR.</p>
            </div>
            <h3>Danh sách tài liệu</h3>
            <table>
              <thead><tr><th>Tên</th><th>Dung lượng</th><th>Số trang</th><th></th></tr></thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.document_id}>
                    <td>{d.original_name}</td>
                    <td>{fmtBytes(d.size_bytes)}</td>
                    <td>{d.page_count}</td>
                    <td><button onClick={() => pickDoc(d)}>Chọn trang</button></td>
                  </tr>
                ))}
                {docs.length === 0 && <tr><td colSpan={4} className="muted">Chưa có tài liệu nào.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {step === "select" && doc && (
          <div className="card">
            <h3>{doc.original_name} — {doc.page_count} trang PDF</h3>
            <div className="row">
              <label>Từ trang <input type="number" min={1} max={doc.page_count} value={fromPage}
                onChange={(e) => setFromPage(e.target.value)} style={{ width: 80 }} disabled={allPages || expr !== ""} /></label>
              <label>đến trang <input type="number" min={1} max={doc.page_count} value={toPage}
                onChange={(e) => setToPage(e.target.value)} style={{ width: 80 }} disabled={allPages || expr !== ""} /></label>
              <span className="muted">hoặc</span>
              <label>Danh sách tùy chọn <input type="text" placeholder="5-10,15,20-22" value={expr}
                onChange={(e) => setExpr(e.target.value)} style={{ width: 200 }} disabled={allPages} /></label>
              <label><input type="checkbox" checked={allPages}
                onChange={(e) => setAllPages(e.target.checked)} /> Toàn bộ tài liệu</label>
            </div>
            {selError && <div className="banner-err">{selError}</div>}
            {selection && (
              <div className="banner-info">
                Đã chọn {selection.count} trang PDF
                {selection.count > 0 && <>: {selection.pages[0]}–{selection.pages[selection.pages.length - 1]}
                  {selection.pages.length > 20 ? ` (${selection.pages.length} trang)` : ` = ${selection.pages.join(", ")}`}</>}
                {" "}trong tổng số {doc.page_count} trang.
                <br />Tool sẽ xử lý {selection.count} trang này rồi dừng.
                {selection.warnings.map((w, i) => <div key={i} className="muted">• {w}</div>)}
              </div>
            )}
            {selection && selection.count > 0 && (
              <div className="row" style={{ marginTop: 8 }}>
                <span className="muted">Xem trước trang đầu/cuối đã chọn:</span>
                <img src={api.previewUrl(doc.document_id, selection.pages[0])} width={160} alt="preview đầu" />
                <img src={api.previewUrl(doc.document_id, selection.pages[selection.pages.length - 1])} width={160} alt="preview cuối" />
              </div>
            )}
            <details style={{ marginTop: 8 }}>
              <summary className="muted">Thông tin bộ sách (tùy chọn — không bắt điền để được OCR)</summary>
              <MetaForm docId={doc.document_id} initial={doc.metadata ?? {}} onSaved={refreshDocs} />
            </details>
            <details style={{ marginTop: 8 }}>
              <summary className="muted">Nâng cao</summary>
              <label><input type="checkbox" checked={ocrAgain} onChange={(e) => setOcrAgain(e.target.checked)} />
                {" "}OCR lại các trang đã chọn (dùng khi lớp chữ có sẵn nhưng sai)</label>
            </details>
            <div className="row" style={{ marginTop: 12 }}>
              <button onClick={() => pickDoc(doc)} className="secondary">← Quay lại danh sách</button>
              <button onClick={runJob} disabled={!selection || selection.count === 0}>
                Xử lý {selection?.count ?? 0} trang
              </button>
            </div>
          </div>
        )}

        {step === "progress" && job && (
          <div className="card">
            <h3>Đang xử lý: {job.document_name}</h3>
            <div className="banner-info">
              {job.succeeded_pages + job.failed_pages}/{job.selected_pages.length} trang đã xử lý
              {job.current_page ? <> • đang xử lý trang PDF {job.current_page}</> : null}
              {" "}• mẫu số là số trang bạn chọn ({job.selected_pages.length}), không phải tổng {job.document_page_count} trang của file.
              <br />
              {job.model_phase === "loading_model"
                ? "Giai đoạn: Đang chuẩn bị model (lần đầu tốn thời gian nạp model — tách riêng với OCR)…"
                : job.process_phase
                  ? <>Giai đoạn: {PROCESS_VI[job.process_phase] ?? job.process_phase}{job.process_phase === "ocr" && job.model_phase === null ? " (model đã sẵn sàng)" : ""}</>
                  : "Giai đoạn: chờ trang"}
              {job.eta_s != null && <><br />Ước tính còn lại: {job.eta_s}s (chỉ ước tính, tự điều chỉnh theo loại trang)</>}
            </div>
            <table>
              <thead><tr><th>Trang PDF</th><th>Trạng thái</th><th>Phương pháp</th><th></th></tr></thead>
              <tbody>
                {job.pages.map((p) => (
                  <tr key={p.page_no}>
                    <td>{p.page_no}</td>
                    <td><span className={`badge ${
                      p.status === "SUCCEEDED" || p.status === "NEEDS_REVIEW" ? "ok"
                        : p.status === "RUNNING" ? "run"
                          : p.status === "FAILED" || p.status === "INTERRUPTED" ? "err" : ""}`}>{statusVi(p.status)}</span></td>
                    <td>{p.status === "PENDING" ? "Chưa xác định" : methodVi(p.method)}</td>
                    <td>
                      {(p.status === "SUCCEEDED" || p.status === "NEEDS_REVIEW") && (
                        <button className="ghost" onClick={() => { setViewPage(p.page_no); setStep("view"); }}>Xem</button>
                      )}
                      {(p.status === "FAILED" || p.status === "INTERRUPTED") && !running && (
                        <button className="secondary" onClick={() => api.retryPage(job.job_id, p.page_no).then(setJob)}>Thử lại</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="row" style={{ marginTop: 12 }}>
              {["PAUSED", "INTERRUPTED", "CREATED"].includes(job.status) && job.pending_pages > 0 && (
                <button onClick={() => api.resumeJob(job.job_id).then(setJob)}>Tiếp tục</button>
              )}
              {job.status === "RUNNING" && (
                <button className="warn" onClick={() => api.pauseJob(job.job_id).then(setJob)}>Tạm dừng sau trang này</button>
              )}
              {running && (
                <button className="warn" onClick={() => api.cancelJob(job.job_id).then(setJob)}>Dừng ngay</button>
              )}
              {jobDone && <button onClick={() => { setViewPage(job.pages.find((p) => p.active_revision_id)?.page_no ?? null); setStep("view"); }}>
                Xem trang đã xong
              </button>}
              <button className="secondary" onClick={() => setStep("select")}>← Chọn trang khác (job mới)</button>
            </div>
            {job.status === "COMPLETED" && (() => {
              const needReview = job.pages.filter((p) => p.status === "NEEDS_REVIEW").length;
              return (
                <div className="banner-info">
                  Đã xử lý xong {job.succeeded_pages}/{job.selected_pages.length} trang đã chọn
                  — Không xử lý các trang còn lại.
                  {needReview > 0 && <> Trong đó <b>{needReview} trang cần kiểm tra</b> (chưa phải đã duyệt).</>}
                  {" "}Đầu ra vẫn là <b>bản nháp</b>.
                </div>
              );
            })()}
            {job.status === "COMPLETED_WITH_ERRORS" && <div className="banner-err">Đã kết thúc: {job.succeeded_pages} trang thành công, {job.failed_pages} trang lỗi. Bản tải ra vẫn là nháp và chưa đầy đủ.</div>}
            {job.status === "PAUSED" && <div className="banner-info">Tạm dừng sau trang hiện tại. Bấm “Tiếp tục” để chạy nốt các trang chưa xong.</div>}
          </div>
        )}

        {step === "view" && job && (
          <ViewPage job={job} pageNo={viewPage} setPageNo={setViewPage} goProgress={() => setStep("progress")} />
        )}
      </main>
    </>
  );
}

function ViewPage(props: {
  job: Job;
  pageNo: number | null;
  setPageNo: (n: number | null) => void;
  goProgress: () => void;
}) {
  const { job, pageNo, setPageNo, goProgress } = props;
  const [page, setPage] = useState<PageResult | null>(null);
  const [tab, setTab] = useState<"content" | "json" | "issues">("content");
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState<Block[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<{ revision_id: string; kind: string; active: boolean }[]>([]);

  const donePages = job.pages.filter((p) => p.active_revision_id).map((p) => p.page_no);

  const reload = useCallback(() => {
    if (pageNo == null) { setPage(null); return; }
    api.getPage(job.job_id, pageNo).then((p) => {
      setPage(p);
      setDraft(p.blocks);
      setEditMode(false);
      void api.revisions(job.job_id, pageNo).then((r) => setRevisions(r.items));
    }).catch((e) => setMsg(String(e)));
  }, [job.job_id, pageNo]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    if (!page || page.reprocess_state !== "running") return;
    const t = window.setInterval(() => reload(), 3000);
    return () => window.clearInterval(t);
  }, [page?.reprocess_state, reload]);

  async function saveEdit() {
    if (!page) return;
    try {
      await api.editPage(job.job_id, page.pdf_page, page.revision_id ?? "",
        draft.map((b, i) => ({ ...b, order: i })));
      setMsg("Đã lưu bản sửa (revision mới).");
      reload();
      setTab("content");
    } catch (e) {
      setMsg(`Không lưu được: ${String(e)}`);
    }
  }

  const doneCount = donePages.length;
  const partial = doneCount < job.selected_pages.length;

  return (
    <div className="card">
      <div className="row">
        <button className="secondary" onClick={goProgress}>← Tiến độ</button>
        <div className="pagepick">
          {job.selected_pages.map((p) => (
            <button key={p} className={pageNo === p ? "on" : "ghost"} onClick={() => setPageNo(p)}>{p}</button>
          ))}
        </div>
        <span className="muted">
          {job.succeeded_pages}/{job.selected_pages.length} trang có kết quả.
          Nhãn: <b>Bản trích xuất nháp</b> — chưa duyệt độc lập.
        </span>
      </div>
      {msg && <div className="banner-info">{msg}</div>}

      {page == null && <p className="muted">Chọn một trang để xem.</p>}
      {page != null && (
        <>
          <div className="row" style={{ margin: "10px 0" }}>
            <div className="tabs">
              <button className={tab === "content" ? "on" : ""} onClick={() => setTab("content")}>Nội dung</button>
              <button className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>JSON</button>
              <button className={tab === "issues" ? "on" : ""} onClick={() => setTab("issues")}>
                Vấn đề cần kiểm tra ({page.open_issues?.length ?? page.issues.filter((i) => i.status !== "resolved").length})
              </button>
            </div>
            <span className="muted">Trạng thái: {statusVi(page.status)} • {page.review_status === "edited" ? "đã sửa" : page.review_status === "reviewed_by_user" ? "đã duyệt bởi bạn" : "chưa duyệt"} • {methodVi(page.method)}
              {page.attempt > 1 ? ` • lần thử ${page.attempt}` : ""}</span>
          </div>

          <div className="two-col">
            <div className="pane" style={{ maxHeight: "70vh" }}>
              {job.document_id && (
                <img className="pageimg" src={api.previewUrl(job.document_id, page.pdf_page)} alt={`Trang ${page.pdf_page}`} />
              )}
            </div>
            <div className="pane" style={{ maxHeight: "70vh" }}>
              {tab === "content" && !editMode && <MarkdownView blocks={page.blocks} pageNo={page.pdf_page} />}
              {tab === "content" && editMode && (
                <div style={{ padding: 12 }}>
                  {draft.map((b, i) => (
                    <div key={b.block_id}>
                      <div className="muted">#{i + 1} · {b.type === "formula" ? "công thức (LaTeX, không kèm $)" : b.type}</div>
                      <textarea className="blockedit" value={b.text ?? ""}
                        onChange={(e) => setDraft(draft.map((x, j) => j === i ? { ...x, text: e.target.value } : x))} />
                    </div>
                  ))}
                  <div className="row">
                    <button onClick={saveEdit}>Lưu sửa</button>
                    <button className="ghost" onClick={() => { setDraft(page.blocks); setEditMode(false); }}>Hủy sửa</button>
                  </div>
                </div>
              )}
              {tab === "json" && (
                <pre style={{ padding: 12, fontSize: 12 }}>{JSON.stringify(page, null, 1)}</pre>
              )}
              {tab === "issues" && (
                <div style={{ padding: 12 }}>
                  {page.issues.length === 0 && <p className="muted">Không có vấn đề được ghi nhận.</p>}
                  {page.issues.map((i) => (
                    <div key={i.issue_id} style={{ marginBottom: 6 }}>
                      <span className={i.status === "resolved" ? "badge ok" : "badge err"}>
                        {i.status === "resolved" ? "đã xử lý" : "đang mở"}
                      </span>{" "}
                      <span className="badge">{i.type}</span> {i.description}
                      {i.history_only && <span className="muted"> (lịch sử)</span>}
                      {i.status === "resolved" && (
                        <div className="muted">Lý do: {i.resolved_reason} · kiểm ở {i.checked_revision?.slice(0, 12)}</div>
                      )}
                      {i.status !== "resolved" && !i.history_only && (
                        <button className="ghost" style={{ marginLeft: 6 }} onClick={() => {
                          const reason = window.prompt("Lý do đóng vấn đề này (sẽ được lưu cùng revision đã kiểm tra):");
                          if (!reason) return;
                          api.resolveIssue(job.job_id, page.pdf_page, i.issue_id, reason, page.revision_id ?? undefined)
                            .then((p) => setPage(p)).catch((e) => setMsg(String(e)));
                        }}>Đã xử lý</button>
                      )}
                    </div>
                  ))}
                  <p className="muted">Trang có vùng hình bị bỏ qua được ghi nhận bằng khối <code>skipped_visual</code> và vấn đề <code>VISUAL_SKIPPED</code> — không chặn tải bản nháp nhưng chưa đủ ngữ cảnh để coi là đã duyệt phần hình. Việc đóng vấn đề là quyết định của bạn, không tự động.</p>
                </div>
              )}
            </div>
          </div>

          <div className="row" style={{ marginTop: 10 }}>
            {!editMode && tab === "content" && page.revision_id && (
              <button className="secondary" onClick={() => setEditMode(true)}>Sửa nội dung</button>
            )}
            <button className="secondary" onClick={() => {
              api.revertPage(job.job_id, page.pdf_page).then(() => reload()).catch((e) => setMsg(String(e)));
            }}>Hoàn tác về bản OCR</button>
            <button className="secondary" disabled={page.reprocess_state === "running"} onClick={() => {
              api.reprocessPage(job.job_id, page.pdf_page).then(() => reload());
            }}>{page.reprocess_state === "running" ? "Đang OCR lại…" : "OCR lại trang này"}</button>
          </div>
          {revisions.length > 1 && (
            <div className="muted">
              Lịch sử revision: {revisions.map((r) => (
                <span key={r.revision_id} style={{ marginRight: 8 }}>
                  {r.kind}{r.active ? " (đang dùng)" : ""}{" "}
                  {!r.active && <button className="ghost" onClick={() =>
                    api.useRevision(job.job_id, page.pdf_page, r.revision_id).then(() => reload())}>Dùng bản này</button>}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      <hr style={{ margin: "16px 0" }} />
      <h4>Tải kết quả — đúng các trang đã chọn</h4>
      <div className="row">
        <DownloadButton jobId={job.job_id} format="md" label={`Tải Markdown${partial ? ` (bản nháp ${doneCount}/${job.selected_pages.length} trang)` : ""}`} onDone={setMsg} />
        <DownloadButton jobId={job.job_id} format="json" label={`Tải JSON${partial ? ` (bản nháp ${doneCount}/${job.selected_pages.length} trang)` : ""}`} onDone={setMsg} />
        <DownloadButton jobId={job.job_id} format="zip" label={`Tải ZIP${partial ? ` (bản nháp ${doneCount}/${job.selected_pages.length} trang)` : ""}`} onDone={setMsg} />
      </div>
      <p className="muted">Đầu ra chỉ gồm chữ + công thức ở {doneCount} trang có kết quả; ZIP gồm content.md, content.json, manifest.json, issues.json (không kèm file gốc).</p>
    </div>
  );
}

function MetaForm({ docId, initial, onSaved }: {
  docId: string; initial: Record<string, string>; onSaved: () => void;
}) {
  const [subject, setSubject] = useState(initial.subject ?? "");
  const [grade, setGrade] = useState(initial.grade ?? "");
  const [series, setSeries] = useState(initial.series ?? "");
  const [note, setNote] = useState<string | null>(null);
  return (
    <div className="row" style={{ marginTop: 6 }}>
      <label>Môn <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Toán" /></label>
      <label>Lớp <input value={grade} onChange={(e) => setGrade(e.target.value)} placeholder="10" style={{ width: 70 }} /></label>
      <label>Bộ sách <input value={series} onChange={(e) => setSeries(e.target.value)} placeholder="Kết nối / Chân trời…" /></label>
      <button className="secondary" onClick={() => {
        api.patchMetadata(docId, { subject, grade, series })
          .then(() => { setNote("Đã lưu thông tin bộ sách."); onSaved(); })
          .catch((e) => setNote(String(e)));
      }}>Lưu thông tin</button>
      {note && <span className="muted">{note}</span>}
    </div>
  );
}

function DownloadButton({ jobId, format, label, onDone }: {
  jobId: string; format: string; label: string; onDone: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const exp = await api.createExport(jobId, format);
        const a = document.createElement("a");
        a.href = api.downloadUrl(exp.export_id);
        a.download = exp.filename;
        a.click();
        onDone(`Đang tải ${exp.filename}${exp.partial ? ` (thiếu: ${exp.missing_pages.join(",") || "không"})` : ""}`);
      } catch (e) {
        onDone(String(e));
      } finally {
        setBusy(false);
      }
    }}>{label}</button>
  );
}
