# REVIEW — Đối chiếu code ↔ SOP Dataset (`docs/Huong_dan_chuan_bi_va_xu_ly_Dataset.docx`)

Ngày kiểm: 2026-09-25
Người kiểm: team-manager (DeepSeek V4.1 Flash)
Phương pháp: đọc trực tiếp toàn bộ cây mã + chạy baseline test. Không sửa code.

## 0. Bằng chứng baseline (đo thật, không suy diễn)

| Lệnh | Kết quả |
|---|---|
| `D:\OCR_Local\.venv313\Scripts\python.exe -m pytest backend\app\tests -q` | **189 passed / 189 collected**, 1 warning (starlette deprecation), ~18.4s |
| Đọc `docs/ACCEPTANCE_REPORT.md` | P01–P20: PASS 19 · PARTIAL 1 (P13) · chưa đủ 0 |
| Đọc `docs/IMPLEMENTATION_STATUS.md` | S1–S8 ✅ (S6 tự động, desktop ⏳) |
| Đọc `docs/OPEN_FINDINGS_PROMPT_AUDIT_2026-09-15.md` | F1 PARTIAL · F2 OPEN/BLOCKER · F3 OPEN/BLOCKER · F4 PARTIAL · báo cáo INCONSISTENT |

> Lưu ý: `pytest_out.txt` ở gốc repo ghi `154 passed` là **số cũ**, không phải hiện hành. Hiện hành là 189.

## 1. Kết luận nhanh

- **Cấp độ "công cụ OCR"**: đã gần hoàn thiện. Là tool local, 1 người dùng, chạy đúng N trang được chọn rồi dừng, có revision, issue, export ZIP + checksum, KaTeX, PII redact metadata. 2 gate còn mở: **C3** (UAT desktop bởi người thật) và **C4** (đối chiếu công thức trên SGK thật).
- **Cấp độ "SOP chuẩn bị & xử lý Dataset"**: **CHƯA hoàn thiện — mới phủ ~10–15%**. Tool dừng ở bước OCR → Markdown/JSON **bản nháp**. SOP yêu cầu cả pipeline: định danh nguồn → metadata → trạng thái duyệt → JSON đề thi chuẩn → chunking → RAG BGE-M3/Qdrant → 5000 mẫu fine-tune → checklist phát hành. Toàn bộ các phần này **chưa có trong mã**.

## 2. Gap matrix (SOP §  ↔  code)

| SOP | Yêu cầu | Trạng thái | Bằng chứng code |
|---|---|---|---|
| §1.1–1.3 | Phạm vi Toán/Anh THPT 10–12; bằng chứng năm 2025–2026; publication_year/revision_date/school_year; rights_status/HOLD_RIGHTS | ❌ | không có `source_id`, không có `publication_year`, không có `rights_status` (grep = 0 hit) |
| §2.1 | source_id ổn định (`MATH_G10_2026_0001`), source_version, thư mục `00_raw_restricted`…`06_release` | ❌ | chỉ có `document_id` opaque + `data/{raw,jobs,exports}` |
| §2.2 | Metadata tối thiểu ~20 trường (subject, grade, topic, document_type, language, curriculum_reference, publisher, source_url, retrieved_at, year_evidence, allowed_uses, pii_status, review_status, explanation_origin, schema_version…) | ⚠️ ~3/20 | `documents.metadata_json` chỉ nhận `{subject, grade, series, notes}` (`api/documents.py:150`) |
| §2.3 | Workflow `NEW→COLLECTED→CLEANING→READY_FOR_REVIEW→APPROVED→EXPORTED`; `RETURNED`/`HOLD`/`REJECTED` | ❌ | JobState khác hoàn toàn; export **luôn** `status=draft`, P20 cấm nhãn APPROVED |
| §3.1 | Markdown chuẩn; xóa header/footer/watermark; sửa dấu tiếng Việt; bắt cặp OCR dễ nhầm `0/O,1/l,x/×` | ⚠️ một phần | `cleaning/normalize.py` chỉ NFKC + whitespace + `\(..\)`→`$..$`; không xóa header/footer, không check cặp ký tự |
| §3.2 | Công thức BẮT BUỘC LaTeX; `$…$`/`$$…$$`; escape `\\frac` trong JSON; render kiểm cú pháp + đối chiếu nghĩa; nhãn SOURCE_ERROR | ⚠️ phần lớn | `cleaning/math_verify.py` + KaTeX UI ✅; nhưng không có nhãn `SOURCE_ERROR`, không có quy trình "gõ lại công thức" |
| §3.3 | Bảng giữ cột/đơn vị; nhãn trong hình chép ra LaTeX; cờ `REQUIRES_VISUAL`; bài đọc Anh giữ ngữ liệu gắn câu hỏi; audio thiếu → `HOLD_MISSING_CONTEXT` | ⚠️ yếu | có `skipped_visual` + bbox (không bịa mô tả) ✅; KHÔNG chép nhãn trong hình, không có `REQUIRES_VISUAL`, không có context_id, không có audio |
| §3.4 | Loại PII: họ tên, email, ĐT, địa chỉ, ngày sinh, mã HS, giấy tờ, chữ ký, ảnh người; quét cả bảng/header/footer/comment/tracked-changes/author/tên file/URL/QR/chữ trong ảnh/tệp nhúng; nhãn `[NGUOI_01]` | ⚠️ yếu | `cleaning/pii.py` = 6 regex trên text; chỉ **redact metadata** khi export, KHÔNG mask trong content; không quét ảnh/QR/docx props |
| §4 | JSON đề thi: `exam_id`, `metadata`, `questions[]`, `contexts[]`; `question/options/correct_answer/explanation`; enum `question_type`; `rubric`; JSON Schema + kiểm tra quan hệ | ❌ | `content.json` là block-based (`pdf_page`/`blocks`), KHÔNG phải schema đề thi |
| §5 | Vai trò Collectors / Data Cleaners / Reviewers; người duyệt ≠ người làm sạch; cổng nghiệm thu giai đoạn 1 | ❌ | chỉ có `review_status` 3 giá trị, không có vai trò/duyệt |
| §6 | Sliding-window chunking 500–800 token, overlap 15–20%, `chunk_id/prev_chunk_id/next_chunk_id`, tokenizer thật, không cắt cụt | ❌ | grep `sliding`/`chunk_id` = 0 |
| §7 | BGE-M3 (1024 chiều) + Qdrant cosine, UUID point id, payload index, pilot ≥60 query, Hit@5 ≥90% | ❌ | grep `bge`/`qdrant` = 0 |
| §8 | 5000 mẫu fine-tune (2500 Toán/2500 Anh; 800/800/900; 4 nhóm tác vụ), chấm 100 ≥90, dedup, split 4500/250/250, JSONL messages, chống rò rỉ | ❌ | grep `finetune`/`rubric`/`question_type` = 0 |
| §9 | Điều phối/lỗi (issue sheet đủ trường), pilot 12 tài liệu | ⚠️ một phần | `issues` table có, nhưng thiếu `issue_id/source_id/người nhận/hạn sửa`; không có pilot harness |
| §10 | Checklist phát hành nội dung/kỹ thuật; manifest + checksum + hướng dẫn tái chạy | ❌ | có checksum ZIP cục bộ, không có release manifest theo SOP |

Tổng: **❌ 8 hạng mục · ⚠️ 6 hạng mục · ✅ 0 (đủ chuẩn SOP)**.

## 3. Finding còn mở của chính tool (từ audit 2026-09-15, chưa verify là đã đóng)

| ID | Mức | Nội dung | File |
|---|---|---|---|
| F2 | **BLOCKER** | Pin identity: re-check bằng sample có thể chấp nhận weight đã đổi; fallback ghi cache dưới tag không thuộc model worker thực dùng | `backend/app/ocr/paddle_adapter.py:125-145`, `services/job_service.py` |
| F3 | **BLOCKER** | Sanitizer chưa tách hash/sanitize, phá URL, ZIP hỏng bị bỏ qua, ZIP bị thay tại chỗ, thiếu test | `scripts/hash_evidence.py`, `cleaning/export_sanitize.py` |
| F1 | PARTIAL | `model_fingerprint` không kiểm tra đủ shard được index tham chiếu → trả `ok` cho model thiếu artifact | `backend/app/ocr/model_identity.py:168-171` |
| F4 | PARTIAL | Báo cáo gán sai bằng chứng P14 (B4 trang 6) | `docs/ACCEPTANCE_REPORT.md` |

> Lưu ý: nội dung F1–F4 lấy từ note audit; **chưa tự chạy lại probe** trong lần kiểm này. Cần 1 vòng verify trước khi coi là đóng.
