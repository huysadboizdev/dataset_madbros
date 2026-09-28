# Kế hoạch: Đưa `pdf-cleaner-tool` lên chuẩn SOP Dataset

> **For agentic workers:** Kế hoạch này chia thành 9 giai đoạn (GĐ0–GĐ8). Mỗi task có
> owner, file, acceptance criteria (AC) và test bắt buộc. Thực thi tuần tự theo dependency.
> GĐ0 và GĐ1 đã đủ chi tiết để code ngay; GĐ2–GĐ8 sẽ được **làm mịn thành task TDD chi tiết**
> ngay trước khi bắt đầu giai đoạn đó (theo `writing-plans`), vì phần lớn phụ thuộc kết quả GĐ1.

**Goal:** Bổ sung vào tool hiện tại toàn bộ pipeline chuẩn bị & xử lý dataset theo
`docs/Huong_dan_chuan_bi_va_xu_ly_Dataset.docx`: định danh nguồn → metadata → trạng thái duyệt →
JSON đề thi → chunking → RAG BGE-M3/Qdrant → 5000 mẫu fine-tune → checklist phát hành.

**Architecture:** Giữ nguyên FastAPI + SQLite + React/Vite hiện có. Mở rộng theo lớp:
(1) **Dataset core** (nguồn/metadata/trạng thái) là nền của mọi thứ; (2) **Cleaning** nâng lên chuẩn §3;
(3) **Exam JSON** + **Review** là cổng chất lượng; (4) **Chunking → RAG → Fine-tune** là 3 đầu ra dẫn xuất.
Không phá vỡ hợp đồng hiện có (job/revision/issue/export) — tầng mới đọc từ tầng cũ.

**Tech Stack:** Python 3.13 (`D:\OCR_Local\.venv313`), FastAPI, SQLite (migration `user_version`),
Pydantic v2, pytest; React 18 + TS strict + Vite + Playwright; bổ sung: `jsonschema`,
`sentence-transformers`/`FlagEmbedding` (BGE-M3), `qdrant-client`, `python-docx`, `python-pptx`,
`tiktoken`/`transformers` tokenizer.

**Spec:** `docs/Huong_dan_chuan_bi_va_xu_ly_Dataset.docx` (trích xuất text: xem `.ai-team/REVIEW.md`)
+ đối chiếu trạng thái: `.ai-team/REVIEW.md`.

## Global Constraints

- Chạy test bằng `D:\OCR_Local\.venv313\Scripts\python.exe -m pytest backend\app\tests -q`.
  Baseline hiện hành: **189 passed**. Không được giảm số test pass.
- Mọi thay đổi schema DB phải là **migration mới** trong `backend/app/db.py:MIGRATIONS` (append,
  không sửa migration cũ). DB hiện ở `user_version=3`.
- Export cũ (`content.md`, `content.json`, `manifest.json`, `issues.json`) là hợp đồng đã nghiệm thu →
  **không đổi format**; chỉ thêm file/khối mới.
- Không hard-code đường dẫn tuyệt đối, username, hay thông tin nhận diện vào output (đã có
  `export_sanitize.sanitize_public` + test P19; mọi output mới phải đi qua sanitizer).
- Không tuyên bố PASS nếu chưa chạy lệnh kiểm chứng (`verification-before-completion`).
- UI: không `dangerouslySetInnerHTML` cho nội dung OCR thô (anti-XSS hiện có).
- Mọi artifact mới phải ghi `schema_version` / `pipeline_version` / checksum SHA-256.

---

## Bản đồ thay đổi file (tầng mới)

```
backend/app/
  dataset/                      # MỚI — GĐ1
    __init__.py
    source_id.py                # sinh source_id chuẩn MATH_G10_2026_0001
    layout.py                   # thư mục 00_raw_restricted..06_release
    metadata.py                 # schema metadata tối thiểu + validate
    status.py                   # state machine NEW..EXPORTED + RETURNED/HOLD/REJECTED
    registry.py                 # CRUD nguồn + manifest nguồn
  cleaning/
    header_footer.py            # MỚI — GĐ2
    vi_normalize.py             # MỚI — GĐ2
    pii_engine.py               # MỚI — GĐ2 (thay pii.py, giữ shim)
    visual_labels.py            # MỚI — GĐ2
  ingest/                       # MỚI — GĐ2
    docx_ingest.py
    pptx_ingest.py
  exams/                        # MỚI — GĐ3
    schema/exam.schema.json
    builder.py
    validate.py
  review/                       # MỚI — GĐ4
    workflow.py
    issue_sheet.py
  chunks/                       # MỚI — GĐ5
    units.py
    windower.py
    manifest.py
  rag/                          # MỚI — GĐ6
    embed.py
    qdrant_store.py
    pilot_eval.py
  finetune/                     # MỚI — GĐ7
    sample_builder.py
    quality.py
    dedup.py
    split.py
    export_jsonl.py
  api/
    dataset.py                  # MỚI — API GĐ1/GĐ4
    exams.py                    # MỚI — API GĐ3
    chunks.py                   # MỚI — API GĐ5
    rag.py                      # MỚI — API GĐ6
    finetune.py                 # MỚI — API GĐ7
frontend/src/
  components/DatasetPanel.tsx   # MỚI — nhập metadata nguồn + trạng thái
  components/ReviewPanel.tsx    # MỚI — duyệt/từ chối
```

---

## GĐ0 — Đóng nợ kỹ thuật của tool (BLOCKER, làm trước mọi mở rộng)

**Lý do:** đang có 2 finding BLOCKER (F2/F3) trong `docs/OPEN_FINDINGS_PROMPT_AUDIT_2026-09-15.md`.
Mở rộng lên dataset trong khi nền còn lỗ hổng identity/sanitize là tích lũy nợ.

### Task 0.1 — F1: xác minh đủ shard được index tham chiếu
- **Owner:** team-coder · **Skill:** `systematic-debugging`, `rtk-tdd`, `verification-before-completion`
- **Files:** `backend/app/ocr/model_identity.py:118-175`; test `backend/app/tests/unit/test_model_identity.py`
- **AC:** nếu `*.safetensors.index.json` tham chiếu shard không tồn tại/không đọc được →
  `model_fingerprint()` trả `status != 'ok'` (incomplete/unresolved), không được trả `ok`.
- **Test bắt buộc:** 3 ca — index đủ shard → ok; thiếu 1 shard → incomplete; shard không đọc được → unresolved.

### Task 0.2 — F2: pin identity không chấp nhận weight đã đổi
- **Owner:** team-coder · **Skill:** `systematic-debugging`, `test-driven-development`
- **Files:** `backend/app/ocr/paddle_adapter.py:125-145`, `backend/app/services/job_service.py` (pinned tag/cache)
- **AC:** (a) `sample_fp` một mình KHÔNG đủ để kết luận "weight nguyên vẹn" — phải kiểm tra đủ điều kiện
  tương đương identity đã pin (inventory + size + full-hash file nhỏ + index shard như Task 0.1), hoặc
  fail rõ ràng bằng `ModelChangedSincePin`; (b) không ghi cache dưới tag không thuộc model worker thực dùng.
- **Test bắt buộc:** sửa byte weight **ngoài** vùng sample, giữ nguyên size+mtime → phải bị phát hiện;
  fallback path không tạo cache sai tag.

### Task 0.3 — F3: tách hash/sanitize + sanitizer an toàn
- **Owner:** team-coder · **Skill:** `security-guardian`, `test-driven-development`
- **Files:** `scripts/hash_evidence.py`, `backend/app/cleaning/export_sanitize.py`; test `unit/test_hash_evidence.py`, `unit/test_export_sanitize.py`
- **AC:** (a) hash đọc byte thô, sanitize không bao giờ phá URL/LaTeX/tiếng Việt; (b) ZIP không đọc được →
  fail-closed (không bỏ qua âm thầm); (c) không sửa ZIP tại chỗ; (d) không có file tạm lọt vào evidence.
- **Test bắt buộc:** URL giữ nguyên; LaTeX `\\frac` giữ nguyên; ZIP hỏng → lỗi rõ; file tạm bị loại.

### Task 0.4 — F4 + đồng bộ báo cáo/snapshot
- **Owner:** team-manager (docs) + team-reviewer (verify) · **Skill:** `verification-before-completion`
- **Files:** `docs/ACCEPTANCE_REPORT.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/SOURCE_SNAPSHOT.sha256`, `docs/EVIDENCE_SNAPSHOT.sha256`
- **AC:** sửa trích dẫn P14 (B3 trang 7, không phải B4 trang 6); hai báo cáo mô tả cùng một trạng thái;
  chạy `scripts/verify_snapshots.py` pass sau khi cập nhật hash.

### Task 0.5 — Chạy lại toàn bộ verification + chốt snapshot
- **Owner:** team-reviewer · **Skill:** `verify-and-stop`
- **AC:** `pytest` ≥189 passed; `npm run typecheck` + `npm run build` pass; Playwright 6 passed;
  `test_ops_hardkill.py` PASS; cập nhật snapshot + ghi số liệu thật vào ACCEPTANCE_REPORT.

### Task 0.6 — C4: đối chiếu công thức trên SGK thật (CẦN NGƯỜI DÙNG)
- **Owner:** team-manager điều phối · **Skill:** `verify-and-stop`
- **Blocker:** cần user chỉ 3–5 trang SGK THẬT có phân số/căn/số mũ hiển thị (test.pdf hiện tại không có).
- **AC:** chạy `scripts/verify_formula_ocr.py --pages <trang> --report docs/FORMULA_CHECK.md`, exit 0,
  và người dùng đối chiếu ý nghĩa công thức.

---

## GĐ1 — Dataset core: định danh nguồn + metadata + trạng thái (SOP §1, §2)

**Dependency:** GĐ0 xong. **Đây là nền của mọi giai đoạn sau.**

### Task 1.1 — Migration DB v4: nguồn, phiên bản, lịch sử trạng thái
- **Owner:** team-coder · **Files:** `backend/app/db.py` (append MIGRATIONS), test `integration/test_dataset_registry.py`
- **Bảng mới:**
  - `sources(source_id PK, subject, grade, document_type, curriculum_reference, language,
    title, publisher, source_url, retrieved_at, publication_year, revision_date, school_year,
    year_evidence, rights_status, allowed_uses, pii_status, review_status, status, topic,
    source_version, content_hash, schema_version, owner_code, reviewer_code, created_at, updated_at)`
  - `source_events(event_id PK, source_id FK, from_status, to_status, reason_code, note, actor_role, created_at)`
  - `source_files(file_id PK, source_id FK, sha256, rel_path, kind, size_bytes, created_at)`
- **AC:** migration chạy được từ DB user_version=3 hiện có **không mất dữ liệu**; test mở DB cũ → migrate → query OK.

### Task 1.2 — Sinh `source_id` + đặt tên file chuẩn
- **Owner:** team-coder · **Files:** `backend/app/dataset/source_id.py`; test `unit/test_source_id.py`
- **Interface:**
  ```python
  def make_source_id(subject: str, grade: int, year: int, seq: int) -> str: ...
  # subject ∈ {"MATH","ENG"}; grade ∈ {10,11,12}; → "MATH_G10_2026_0001"
  def source_filename(source_id: str, version: int, ext: str) -> str: ...
  # → "math_g10_2026_0001_v1.pdf"
  ```
- **AC:** seq padding 4 chữ số; tăng version không đổi source_id; tên file không chứa PII
  (không họ tên/SĐT/CCCD); test regex tên file.

### Task 1.3 — Bố cục thư mục `00_raw_restricted` … `06_release`
- **Owner:** team-coder · **Files:** `backend/app/dataset/layout.py`; test `unit/test_dataset_layout.py`
- **AC:** tạo/đảm bảo 7 thư mục dưới `settings.data_dir/dataset/`; `00_raw_restricted` có cờ chỉ-đọc
  (ghi log truy cập); mọi ghi vào `02_clean`/`04_rag`/`05_finetune`/`06_release` phải đi qua sanitizer
  + PII scan. Test: path traversal bị chặn (`../`).

### Task 1.4 — Schema metadata tối thiểu + validator
- **Owner:** team-coder · **Files:** `backend/app/dataset/metadata.py`; test `unit/test_dataset_metadata.py`
- **AC:** Pydantic model đủ trường §2.2; trường bắt buộc thiếu → lỗi; trường không áp dụng = `null`;
  `language ∈ {vi,en,mixed}`; `explanation_origin ∈ {source,expert_authored,ai_assisted}`;
  `rights_status` chưa rõ → `HOLD_RIGHTS`; `publication_year` không xác định → `HOLD_YEAR`.
- **Test:** (a) đủ trường → ok; (b) thiếu `year_evidence` → fail; (c) năm 2027 → fail range 2025–2026;
  (d) tài liệu kỹ thuật không bị giới hạn năm.

### Task 1.5 — State machine trạng thái xử lý
- **Owner:** team-coder · **Files:** `backend/app/dataset/status.py`; test `unit/test_dataset_status.py`
- **AC:** `NEW→COLLECTED→CLEANING→READY_FOR_REVIEW→APPROVED→EXPORTED`; `RETURNED` (kèm reason);
  `HOLD` (kèm reason code); `REJECTED`; chỉ `APPROVED` mới được export; mọi transition ghi `source_events`.
- **Test:** (a) nhảy cóc `NEW→APPROVED` → từ chối; (b) `HOLD_YEAR` chặn vào RAG/fine-tune;
  (c) `REJECTED` không export được; (d) `RETURNED` quay lại `READY_FOR_REVIEW`.

### Task 1.6 — API + UI nhập nguồn
- **Owner:** team-coder (API) + team-integration (UI) · **Files:** `backend/app/api/dataset.py`,
  `frontend/src/components/DatasetPanel.tsx`, `frontend/src/api/client.ts`, `frontend/src/types/api.ts`
- **Skill:** team-integration dùng `frontend-design`, `accessibility`
- **AC:** form nhập đủ metadata bắt buộc; upload PDF/Word/PPTX gắn vào `source_id`; hiển thị trạng thái +
  lịch sử; cảnh báo `HOLD_YEAR`/`HOLD_RIGHTS` ngay trên UI; a11y: label đầy đủ, điều hướng bàn phím.
- **Test:** `integration/test_dataset_api.py` + Playwright `dataset.spec.ts`.

### Task 1.7 — Manifest nguồn + xuất hồ sơ
- **Owner:** team-coder · **Files:** `backend/app/dataset/registry.py`; test `integration/test_dataset_registry.py`
- **AC:** `01_manifest` chứa SHA-256, lịch sử phiên bản, trạng thái, vấn đề; phát hiện trùng file theo hash;
  không lưu bản sao từ nhiều website thành nhiều tài liệu; `source_version` tăng khi sửa nội dung.

---

## GĐ2 — Cleaning nâng lên chuẩn §3

**Dependency:** GĐ1.

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 2.1 | Xóa header/footer/watermark lặp | team-coder | `< 5%` nội dung học bị mất trên fixture; test theo bố cục |
| 2.2 | Chuẩn hóa tiếng Việt + bảng cặp ký tự dễ nhầm (`0/O,1/l/I,x/×,-/–,≤/<,≥/>`) | team-coder | phát hiện + gắn cảnh báo, KHÔNG tự sửa khi là nội dung cần học sinh nhận biết |
| 2.3 | PII engine: mở rộng pattern + mask trong content + nhãn `[NGUOI_nn]` + quét docx properties/comment/tracked-changes + QR + chữ trong ảnh | team-coder | diff test: content sạch PII; nhãn nhất quán 1↔1; không xóa tên định lý/tên hư cấu |
| 2.4 | `REQUIRES_VISUAL` + chép nhãn/công thức trong hình ra text/LaTeX | team-integration | trang phụ thuộc hình gắn cờ + ra khỏi luồng text-only |
| 2.5 | Ingest **Word (.docx)** + **PPTX** (đoạn, bảng, phương trình, slide notes) | team-integration | `python-docx`/`python-pptx`; giữ thứ tự slide; bỏ hiệu ứng trang trí |
| 2.6 | Bảng không flatten: giữ cột/đơn vị/giá trị; `table_not_simple` khi phức tạp | team-coder | bảng so sánh colspan/rowspan → không flatten |
| 2.7 | Liên kết ngữ liệu bài đọc tiếng Anh (`context_id`) | team-integration | câu hỏi giữ `context_id`; export giữ ngữ cảnh chung |
| 2.8 | Audio/nghe thiếu → `HOLD_MISSING_CONTEXT` | team-coder | không tạo transcript giả |

**AC giai đoạn:** fixture bộ §3.1–3.4 phủ hết; test PII âm/dương; không hồi quy 189 test cũ.

---

## GĐ3 — JSON đề thi theo chuẩn §4

**Dependency:** GĐ1, GĐ2.

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 3.1 | JSON Schema (`backend/app/exams/schema/exam.schema.json`) | team-coder | ràng buộc trường bắt buộc, enum `question_type`, trường theo loại câu |
| 3.2 | Builder blocks → exam object (`exam_id`, `metadata`, `questions[]`, `contexts[]`) | team-coder | `options` là list `{id,text}`, KHÔNG dùng vị trí mảng làm đáp án |
| 3.3 | Validator quan hệ | team-coder | `option_ids ⊂ options`; tổng điểm khớp; không ID trùng; reject placeholder/công thức lỗi |
| 3.4 | Export `.md` (lý thuyết) + `.json` (câu hỏi) liên kết `source_id` cho đề cương | team-coder | cùng `source_id`; JSON escape `\\frac` đúng (test parse lại) |
| 3.5 | UI xem/sửa câu hỏi + đáp án + giải thích | team-integration | render KaTeX; đánh dấu `SOURCE_ERROR` |

**AC giai đoạn:** ví dụ §4.2 của SOP parse + pass schema; 4 loại câu (single/multi/essay/true_false-ý) hoạt động.

---

## GĐ4 — Review workflow & cổng duyệt §5

**Dependency:** GĐ1–GĐ3.

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 4.1 | Vai trò + ràng buộc người duyệt ≠ người làm sạch | team-coder | transition APPROVED fail nếu cùng actor |
| 4.2 | Bản ghi duyệt + lý do `RETURNED`/`HOLD`/`REJECTED` | team-coder | mọi quyết định lưu vết bất biến |
| 4.3 | Issue sheet đủ trường §9.3 + báo cáo lô | team-coder | `issue_id, source_id, version, vị trí, loại, mức, mô tả, người nhận, hạn, bằng chứng` |
| 4.3b | Issue tracker module + API (SOP §9.3 chi tiết) | team-coder | Migration v6 `source_issues` table; `backend/app/dataset/issue_tracker.py` + `backend/app/api/issues.py`; severity BLOCKER/HIGH/MEDIUM/LOW; status open/in_progress/resolved/wont_fix; location JSON; kiểm tra blockers |
| 4.4 | UI duyệt/từ chối + checklist §5.4 | team-integration | 100% mục checklist phải tick mới cho APPROVED |
| 4.5 | Cổng nghiệm thu GĐ1 (§5.4) tự động | team-coder | không tính HOLD/RETURNED vào tiến độ |

---

## GĐ5 — Chunking sliding window §6

**Dependency:** GĐ1–GĐ4 (chỉ nhận tài liệu APPROVED).

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 5.1 | Parser đơn vị ngữ nghĩa (đoạn/định nghĩa/công thức+ví dụ/bảng/câu hỏi trọn) | team-coder | không cắt giữa câu |
| 5.2 | Windower 500–800 token, overlap 15–20%, không overlap qua chủ đề | team-coder | luôn có ≥1 đơn vị mới; ví dụ §6.3 `[A B C][C D E][E F]` |
| 5.3 | Tokenizer THẬT của model nhúng + chunk manifest | team-coder | `chunk_id, source_id, source_version, section_path, order, token_count, content_hash, prev/next_chunk_id, chunker_version` |
| 5.4 | QA máy 100% + người 10% + pilot 100% | team-reviewer | không mất LaTeX; truy về bản sạch được; ngoại lệ được review |
| 5.5 | Khối đặc biệt: đề thi, bài đọc Anh, giáo án, khối quá dài | team-coder | không nhúng JSON rời rạc; giữ `parent_id` |

---

## GĐ6 — RAG BGE-M3 + Qdrant §7

**Dependency:** GĐ5. **Cần quyết định hạ tầng (Qdrant local/Docker/cloud).**

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 6.1 | Embedding service BGE-M3, pin revision/model/tokenizer | team-coder | 1024 chiều; không NaN/Inf/toàn 0; batch retry idempotent |
| 6.2 | Qdrant collection `thpt_rag_v1` (size 1024, Cosine) + payload index | team-coder | point id = UUID từ `source_id+version+chunk_id` |
| 6.3 | Upsert theo batch + vô hiệu hóa chunk cũ khi đổi version | team-coder | cùng ID → update, không nhân bản |
| 6.4 | Pilot ≥60 query (≥10/ô môn×lớp) + báo cáo Hit@5 | team-coder + team-reviewer | Hit@5 ≥ 90%, báo riêng từng ô; query diễn đạt lại/công thức/lọc lớp |
| 6.5 | Manifest chỉ mục + khả năng tái tạo | team-coder | số point khớp số chunk sau khử trùng; không batch lỗi |

---

## GĐ7 — Bộ 5000 mẫu fine-tune §8

**Dependency:** GĐ1–GĐ4 (nguồn sạch + duyệt). **Không phụ thuộc Qdrant.**

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 7.1 | Sample builder (question, answer, metadata) | team-coder | 1 mẫu = 1 yêu cầu độc lập + 1 đáp án hoàn chỉnh |
| 7.2 | Chấm chất lượng thang 100 + lỗi loại trực tiếp | team-coder | ≥90/100 mới chọn; reject sai đáp án/thiếu lời giải/PII/thiếu nguồn |
| 7.3 | Dedup exact + gần trùng (gom nhóm biến thể) | team-coder | hash chuẩn hóa + so khớp ngữ đoạn/cấu trúc câu hỏi |
| 7.4 | Split 4500/250/250 theo nhóm nguồn, chống rò rỉ | team-coder | không xé nhóm; test overlap nhóm = 0 |
| 7.5 | Export `.json` chuẩn + `.jsonl` messages + đếm token model đích | team-coder | `question→user.content`, `answer→assistant.content`; không cắt mất đáp án |
| 7.6 | Kiểm 100% output tác vụ tạo đề | team-reviewer | parse JSON, đúng số câu/tổng điểm/thời lượng |

**Cơ cấu bắt buộc:** 2500 Toán + 2500 Anh; 800/800/900 theo lớp 10/11/12;
2000 giải bài · 1250 tạo đề · 1000 giải thích kiến thức · 750 soạn hoạt động/giáo án.

---

## GĐ8 — Pilot & phát hành §9, §10

| Task | Nội dung | Owner | AC ngắn |
|---|---|---|---|
| 8.1 | Pilot 12 tài liệu trải 6 ô môn×lớp, đủ 3 nhóm, đủ PDF/Word/PPTX | team-manager điều phối | đo thời gian/trang, tỷ lệ RETURNED, lỗi OCR, chất lượng chunk, tốc độ nhúng, kết quả truy xuất |
| 8.2 | Chốt cấu hình sau pilot + ghi version | team-manager | thay quy tắc phải nêu rõ phần cần chạy lại |
| 8.3 | Checklist phát hành nội dung + kỹ thuật (§10.1/10.2) | team-reviewer | 100% mục phải có bằng chứng |
| 8.4 | Release manifest + changelog + hướng dẫn tái chạy | team-coder | người khác xác định được nguồn, đã sửa gì, ai duyệt, cách tái tạo 2 luồng |

---

## Thứ tự thực thi & song song

```
GĐ0 (BLOCKER) ─┬─> GĐ1 ──> GĐ2 ──> GĐ3 ──> GĐ4 ──┬─> GĐ5 ──> GĐ6
               │                                   └─> GĐ7
               └─> (song song) Task 0.6 C4 cần người dùng
                                                    GĐ8 sau cùng
```
- GĐ5 và GĐ7 **có thể chạy song song** sau GĐ4 (khác file, khác đầu ra).
- Trong mỗi giai đoạn: team-coder làm backend, team-integration làm UI/ingest **chỉ khi khác file**.
- team-reviewer review độc lập cuối mỗi giai đoạn; BLOCKER/HIGH phải đóng trước khi sang giai đoạn kế.
