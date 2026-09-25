# Tiến độ triển khai — PDF Cleaner (MVP v1.1)

> **PHẦN HIỆN HÀNH** (đợt 3, 15/09/2026) ở đầu file. Mọi thứ bên dưới mục
> “LỊCH SỬ” là kết quả cũ, **không còn là trạng thái hiện hành**.
> Số liệu & lệnh chạy thật: xem `docs/ACCEPTANCE_REPORT.md` (đã tách Nhóm A/B/C).
> Snapshot mã: `docs/SOURCE_SNAPSHOT.sha256` (91 file, agg `e27ae846…` — không phụ thuộc tài liệu;
> giá trị `3593b848…` của đợt 2 đã supersede vì mã sửa trong đợt 3);
> snapshot bằng chứng: `docs/EVIDENCE_SNAPSHOT.sha256` (21 file: artifact + log **đã sanitize** +
> báo cáo, tham chiếu một chiều → source; **KHÔNG** ghi aggregate của EVIDENCE vào đây vì
> EVIDENCE hash chính tài liệu này).
> **Lưu ý phạm vi:** "✅" dưới đây = đã kiểm chứng bằng lệnh/test tự động hoặc OCR thật có log;
> **không** đồng nghĩa nghiệm thu sản phẩm (C3/C4 còn chờ người dùng thật — xem ACCEPTANCE_REPORT).

## TRẠNG THÁI HIỆN HÀNH (đợt 3) — quy ước ✅ đã kiểm chứng · ⚠️ một phần · ❌ chưa

| # | Hạng mục | Trạng thái | Ghi chú ngắn |
|---|---|---|---|
| S1 | Resolution gắn revision + content fingerprint | ✅ | `content_fp` (SHA-256 nội dung) chặn kế thừa sai; resolve bắt base_revision (409 conflict). `test_issue_resolution_revision` 4 |
| S2 | Công thức thật: verifier + negative + KaTeX UI | ✅ | `math_verify` giữ toán tử (=,<,>,≥,≤,+,−,^), bắt đủ display và inline, expected-rỗng→FAIL. 15 unit + Playwright KaTeX + OCR thật B2 (chạy lại đợt 3, exit 0) |
| S3 | Chặn đường dẫn local/PII trong export | ✅ | `model_identity` path-free; `export_sanitize.sanitize_public` quét cấu trúc manifest+issues. **Đợt 3 sửa bug thật:** blocked-key `search` → **exact-match** (không xóa nhầm key chứa 'path'; test FAIL trước đó nay pass). `test_export_sanitize` 5 + B5 sạch `Users`/`[PATH] |
| S4 | Model identity = SHA-256 + verify cache theo đĩa | ✅ | Xác minh FULL SHA **đúng 1 lần/job** rồi pin (sửa hash-kép `identity_from_fps`); cache chỉ dùng tag full đã pin, `unresolved`→cấm đọc. **Đợt 3 sửa lỗ hổng thật:** weight layout `inference.pdiparams` nằm ngoài whitelist → chưa từng được hash; đã thêm `.pdiparams` + `inference.json`; ZIP B4 mới chứng minh đủ SHA-256 cả 2 model. `test_model_identity` 5 (gồm test đổi byte ngoài vùng sample, giữ size+mtime) + `test_findings` 10 |
| S5 | Temp/upload/finalize + fault injection | ✅ | reconcile→cleanup tmp job không chạy, `.part`, raw orphan có kiểm tra tham chiếu; rename/DB fail → rollback. `test_ops_lifecycle` 6 |
| S6 | Setup/launcher | ✅(tự động) / ⏳(desktop) | `check_interpreter` xác minh 3.13/64-bit/paddle thật; `npm ci`; `ocr_ready` trong health + banner (thiếu model vẫn mở UI, không chặn direct/old). `test_launcher_env` 4. Double-click desktop = C3 chờ bạn |
| S7 | Bảo toàn chọn trang (sau mọi sửa đổi) | ✅ | recording adapter + dispatch_log: 5–7→{5,6,7}; retry/cache/resume/cancel/page-lỗi không vượt tập. `test_scope_guard` 3 |
| S8 | Snapshot + báo cáo | ✅ | tách source vs evidence, một chiều, không self-hash, không secret/runtime-config; log evidence qua **cơ chế sanitize regex + fail-closed** (không phải 2 lệnh Replace) |

**Tổng test (đo thật đợt 3)**: `pytest` **137 passed / 137 collected** · `tsc -b` strict pass · `vite build` pass ·
Playwright **6 passed** (đo lại trên backend sau sửa) · `test_ops_hardkill` PASS · `verify_formula_ocr` (OCR THẬT,
`mode=live OCR`) 3 trang block+inline **ĐẠT**, mã thoát 0 · `e2e_real_page` (OCR THẬT full-stack, mã thoát 0) → ZIP
mở lại: checksum khớp byte thật, **không** lộ đường dẫn, `model_fp` có **SHA-256 weights cả 2 model** (sau sửa
`.pdiparams`), `disk_identity` full-hash pinned; **`partial:false` nằm trong `content.json` + response API,
KHÔNG phải trường của manifest.json**. Số cũ "131 passed (93; +38)" là của đợt 2 và **sai** tại thời điểm chốt
(một test khi đó đang FAIL) — chuyển vào LỊCH SỬ, không dùng làm hiện hành.

**Gate còn MỞ (chưa nghiệm thu)**: C3 UAT desktop do người dùng; C4 công thức hiển thị trên SGK thật (3–5 trang —
`test.pdf` đã OCR không có phân số/căn hiển thị). **C5 lô 10 trang + ngưỡng duyệt** là bước MỞ RỘNG TỰ CHỌN
sau khi duyệt mẫu nhỏ — **chưa được chọn thực hiện, không tính là blocker**. **P13 = PARTIAL** vì còn thiếu
C4; **P14 = PASS** (giữ chữ, đánh dấu hình bỏ qua `skipped_visual`+bbox, không bịa mô tả; bảng phức tạp→`table_not_simple`, không flatten).
**Không** kết luận hoàn thành MVP khi còn gate C và P13 PARTIAL.

### File/hàm chính đã sửa trong đợt 3 (khi xác minh lại các kết luận đợt 2)
- `backend/app/cleaning/export_sanitize.py` — `_BLOCKED_KEYS` chuyển sang **khớp chính xác** (fix xóa nhầm key)
- `backend/app/ocr/model_identity.py` — whitelist `.pdiparams` (weight layout THẬT), hash thêm `inference.json`; tách `identity_from_fps` (không đọc/model hash lại)
- `backend/app/services/job_service.py` — `_current_model_fp` dùng fingerprint đã tính (1 lần full-hash/job); pin dưới `_mu`
- `backend/app/tests/unit/test_model_identity.py` (+2 test), `docs` (2 báo cáo), `scripts/hash_evidence.py` (sanitize log fail-closed), `README.md` (bỏ username/đường dẫn tuyệt đối)
- Bằng chứng OCR chạy lại: `docs/formula_run0915.*`, `docs/e2e_real_run0915.*`, `e2e_real_export.zip` + `formula_fixture/` mới

### File/hàm chính đã sửa trong đợt 2
- `backend/app/services/revision_service.py` — `block_content_fp`/`page_content_fp`/`apply_resolution`/`resolve_issue`/`compute_validator_issues`
- `backend/app/services/job_service.py` — `_current_cache_tag`/`_pinned_tag`/`cleanup_orphan_artifacts`, `content_fp` trong `_commit_page`, cache write/delete theo tag đĩa
- `backend/app/cleaning/math_verify.py` **(mới)**; `backend/app/cleaning/export_sanitize.py` **(mới)**; `backend/app/ocr/model_identity.py` **(mới)**
- `backend/app/ocr/paddle_adapter.py` — `_model_identity` bỏ `dir`, dùng SHA-256/sample-fp
- `backend/app/db.py` — migration v3 `issues.content_fp`; `backend/app/api/documents.py` — rollback rename/DB, hash-race, 413 message; `backend/app/api/results.py` — `base_revision_id` conflict
- `backend/app/services/export_service.py` — `method_by_page`, engine_meta ưu tiên model thật, `sanitize_public`
- `backend/app/main.py` — startup cleanup + `/api/health.ocr_ready`
- `scripts/verify_formula_ocr.py` (viết lại + `--reverify`), `scripts/check_interpreter.py` **(mới)**, `scripts/hash_source.py`/`hash_evidence.py`, `scripts/run_e2e_server.py`
- `setup.cmd` (validate interpreter), `frontend/src/App.tsx` (nhãn VISUAL_SKIPPED, base_revision_id, banner ocr_ready), `frontend/src/api/client.ts`, `frontend/src/styles.css`, `frontend/playwright.config.ts` (workers=1), `frontend/tests/formula.spec.ts` **(mới)**, fixtures `formula_blocks.json`
- Test mới: `unit/test_math_verify.py`, `unit/test_export_sanitize.py`, `unit/test_direct_extract.py`, `integration/test_issue_resolution_revision.py`, `integration/test_ops_lifecycle.py`, `integration/test_launcher_env.py`, `integration/test_scope_guard.py`, `integration/test_formula_pipeline.py`; cập nhật `test_findings.py`, `conftest.py` (fake model root)

---

## LỊCH SỬ (kết quả cũ — KHÔNG còn là trạng thái hiện hành)

### Đợt rà soát 2 (15/09/2026, đã được supersede bởi đợt 3)
Sửa S1–S8 trên mã, thêm fixtures/test, `hash_evidence.py`; chốt SOURCE agg `3593b848…` (90 file) và ghi
"131 passed (93; +38)" rồi "134 passed" — **cả hai không phản ánh đúng** lần chạy cuối (đầu đợt 3 tìm thấy
1 test FAILED chưa được tính). ZIP e2e + `model_meta.json` của đợt này **thiếu SHA-256 weights layout**
(`.pdiparams` chưa nằm trong whitelist) → toàn bộ artifact/manifest đợt 2 được thay bằng artifact đợt 3.

### Đợt rà soát 1 (15/09/2026, đã được supersede)
Xác minh 8 phát hiện trên mã; các mục đã đúng từ trước: checksum manifest (bỏ self-hash, ZIP hash ngoài DB),
PII tên file/metadata (opaque label, redact), direct-vs-OCR theo coverage/layout, validator chạy lại + giữ lịch sử.
Sửa: `engine_meta` mixed-export; nhãn UI `needs_visual_review`→`VISUAL_SKIPPED`; fixture công thức vẽ tay→toán set.
**93 passed**, Playwright 4/4, thêm `hash_source.py`. (Giờ nằm trong phần Hiện hành.)

### OC00–OC08 (14/09/2026, bản đầu)
- **OC00** ✅ dựng dự án, dùng lại `.venv313`, `check_environment` đủ model; tránh `[PATH]
- **OC01** ✅ `page_selection` khoảng/danh sách/'*', Pydantic strict int; 54 unit.
- **OC02** ✅ upload stream + hash dedupe, pypdfium2 đọc/render ĐÚNG MỘT TRANG, preview lazy; id opaque.
- **OC03** ✅ `ocr/base`+`paddle_adapter`; phát hiện paddleocr 3.7.0 không cho truyền `vl_rec_model_name`; benchmark THẬT
  (model 49.3s; p5 395.9/p6 216.6/p7 228.1s; RAM ~8.7 GB; tiếng Việt đối chiếu được; 1 lỗi nhỏ "MÊNH"→bản nháp).
- **OC04** ✅ worker tiến trình thật JSON-lines, whitelist+fingerprint, dispatch_log, atomic artifact, pause/cancel/resume/retry/reconcile.
- **OC05** ✅ NFKC, `\(..\)`→`$..$`, formula LaTeX, export content/manifest/issues + ZIP opaque.
- **OC06** ✅ React18+TS strict, KaTeX, anti-XSS (không dangerouslySetInnerHTML cho nội dung OCR thô).
- **OC07** ✅ launcher `%~dp0` + venv tường minh, stop chỉ PID đúng danh tính; smoke launch/HTTP/CSRF/upload-dedupe/stop.
- **OC08** ✅ `pytest 73 passed` · typecheck/build pass · e2e OCR THẬT trang 6 (`method=ocr`→`cached`).
