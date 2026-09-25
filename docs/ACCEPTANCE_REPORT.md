# Báo cáo nghiệm thu — PDF Cleaner (MVP v1.1) — TRẠNG THÁI HIỆN HÀNH

Cập nhật: 15/09/2026 (**đợt 4** — đóng 4 finding kiểm toán "S4-dot-sau"). Môi trường: Windows 10, i5-12400F, 16 GB, chạy **CPU** (không GPU).

**Đợt 4 làm gì:** (1) **F1** — inventory model identity đổi từ 5 tên file hardcode sang **quy tắc** (mọi artifact inference de quy đều được hash; thiếu weight → `incomplete`, cấm dùng identity một phần tra cache); (2) **F2** — bỏ full-hash trùng: job pin identity 1 lần/job, worker nhận identity file và chỉ **re-check nhanh** (inventory + size + sha file nhỏ + sample_fp), lệch → `ModelChangedSincePin` fail rõ ràng; (3) **F3** — sanitizer mở rộng MD + JSON lồng + ZIP member (tái tạo checksum), decode strict (không `errors='replace'`), validator **fail-closed trên toàn docs/**; (4) **F4** — sửa trích dẫn P14 (B4 trang 6 → **B3 trang 7**, snapshot 14/09) + hợp đồng mới: text OCR thật trên vùng hình được **bảo toàn**, không nhân đôi khi render/export. Thêm **17 test regression mới** (5 model_identity + 6 pinned identity + 6 visual text). **C3 (nghiệm thu desktop bởi người dùng thật) và C4 (đối chiếu công thức trên SGK thật) vẫn CHƯA đóng.**

**Phân biệt ngay từ đầu:** phần *sửa mã + kiểm thử tự động + bằng chứng chạy lại* bên dưới đã được
đo **lệnh chạy THẬT** trên máy này ở đợt 3 (A2–A4, nhóm B) và đợt 4 (A1, nhóm B không chạy lại OCR thật —
không đổi đường load model theo cách ảnh hưởng kết quả nhận dạng; chỉ 1-page live check không cần vì
model-load path được kiểm bằng 22 test unit không mock engine). Phần *nghiệm thu sản phẩm* (người dùng thật thao tác
desktop — C3, đối chiếu công thức trên SGK thật — C4) **CHƯA hoàn thành**; báo cáo này **không**
kết luận MVP đã được nghiệm thu, chỉ kết luận các hạng mục tự động là ĐẠT theo bằng chứng ghi kèm.
Mọi số liệu cũ không còn là hiện hành đều nằm trong mục LỊCH SỬ cuối file.

## Snapshot mã nguồn (bằng chứng gắn với đúng bản sửa)

- `docs/SOURCE_SNAPSHOT.sha256` — **97 file** nguồn + cấu hình hành vi
  (backend/app, frontend/src, scripts, `setup.cmd`, `Open_Tool.cmd`, `Stop_Tool.cmd`,
  `requirements.lock.txt`, `frontend/package.json`, `package-lock.json`, vite/tsconfig/playwright
  config, `config.example.json`, fixtures test, *.spec.ts, README).
  **AGGREGATE = `d4a5fde70804ed97aa93cc3bdbdf91cae41eb8a8e549ee790de8b1bd7f01fb02`**
  (đợt 4: `e038109b…` → đợt 5 đã đo lại sau khi sửa F1–F4: `scripts/hash_evidence.py`
  tách prepare/hash + test mới; **không** giữ aggregate cũ làm hiện hành).
  Bước kiểm **độc lập**: `python scripts/verify_snapshots.py` hash lại từng entry
  của cả hai manifest bằng code xác minh riêng (không dùng code path sinh manifest),
  kiểm tra one-way reference và đối chiếu aggregate ghi trong báo cáo này.
- `docs/EVIDENCE_SNAPSHOT.sha256` — **21 file** artifact/log-báo cáo đã sanitize
  (SOURCE_SNAPSHOT, ACCEPTANCE_REPORT, FORMULA_CHECK, benchmark_dump, benchmark_dump_skg2,
  formula_fixture/ocr_raw + model_meta, e2e_real_export.zip, **4 log chạy OCR thật**
  trong `docs/sanitized_logs/`),
  **tham chiếu một chiều** tới SOURCE_SNAPSHOT. Hai manifest **không** vòng tham chiếu nhau;
  mỗi manifest **không tự hash chính nó**. (Không ghi aggregate của EVIDENCE vào chính báo cáo
  này — vì EVIDENCE có hash báo cáo → sẽ là vòng tự tham chiếu; chỉ cần mở file để đối chiếu.)
- LOẠI khỏi snapshot: `config.json` runtime (đường dẫn máy người dùng), `data/`, `node_modules`,
  `dist`, cache, mọi secret. Bản sanitized tham số hành vi = `config.example.json`.
- Log OCR chạy THẬT **không được đưa vào evidence ở dạng thô** (chứa `[PATH]<me>\…`);
  bản `docs/sanitized_logs/*.sanitized` do `scripts/hash_evidence.py` sinh bằng **regex cơ chế**
  (Windows drive `[PATH], UNC `[PATH], Unix `/home|users|var|tmp|…`, `[PATH], không phân biệt
  hoa/thường, nhận cả hai loại slash) kèm **bước kiểm tra fail-closed**: nếu sau sanitize còn
  mẫu đường dẫn/username (username chỉ tính khi đứng cạnh sep trong ngữ cảnh path — không
  chặn nhầm từ tiếng Việt) thì tool **từ chối ghi manifest**. Đã chạy thật: cơ chế bắt đúng một
  vụ còn sót trước khi sửa.

## Cấu hình môi trường đã dùng

| Thành phần | Giá trị |
|---|---|
| Python | 3.13.14 — venv 64-bit trỏ bởi `PDFCLEANER_PY` (`[PATH] mặc định KHÔNG dùng) |
| paddlepaddle/paddleocr/paddlex | 3.3.0 / 3.7.0 / 3.7.2 (khóa ở `requirements.lock.txt`) |
| Model | **resolve thật**: `PP-DocLayoutV3` + `PaddleOCR-VL-1.6-0.9B` (cache `[PATH]) |
| Danh tính model (đo đợt 3) | `disk_identity` (FULL SHA-256, pin 1 lần/job) = `016497b2031dd90f`; `model_rev` (sample nhanh, chỉ provenance/health, **không** quyết định cache) = `1980363cdecc8ee8`. **Đợt 4:** worker nhận identity pin qua file (`jobs_dir/<job>.pinned_identity.json`) và chỉ re-check nhanh (inventory + size + sha file nhỏ + sample_fp weight) — **không full-hash lại weights**; lệch → job FAIL rõ ràng thay vì gắn identity cũ cho engine khác |
| Weights SHA-256 thật | VL `model.safetensors` = `85a479d506a1…` (1 917 255 968 B); layout `inference.pdiparams` = `70bd316b05…` (130 806 572 B) |
| Node/npm | v24.20.0 / 11.19.0 (chỉ build UI) |
| pypdfium2 | 5.13.0 |

---

## NHÓM A — Kiểm thử tự động (fixture/mock; KHÔNG phải bằng chứng PaddleOCR thật)

| # | Lệnh | Kết quả |
|---|---|---|
| A1 | `pytest backend/app/tests -q` | **189 passed / 189 collected** (đo thật đợt 5 sau khi sửa F1–F4; đợt 4 là 154, đợt 3 là 137). Đợt 4–5 thêm **52 test** (F1: unit model_identity shard/index; F2: `test_pinned_identity` 6 + integration `test_identity_pin_cache` + `test_model_shard_verification`; F3: **14** `test_hash_evidence` — prepare/hash tách, regex không phá URL/LaTeX/tiếng Việt, ZIP fail-closed, file tam; F4: 6 `test_visual_text_preservation`) và cập nhật test cũ theo hợp đồng mới (`test_launcher_env` yêu cầu đủ 2 model cho `ocr_ready`, `test_cleaning::test_visual_kept_even_without_text` theo P14) — toàn bộ xanh. **Không** giữ số cũ làm hiện hành (xem LỊCH SỬ) |
| A2 | `npm run typecheck` (TS strict) | pass (đo lại đợt 3) |
| A3 | `npm run build` (vite) | pass → `frontend/dist` (index.js 423.83 kB, KaTeX font tự chứa; đo lại đợt 3) |
| A4 | `npm run test:e2e` (Playwright chromium, **6 spec**) | **6 passed** (đo lại đợt 3 trên backend sau sửa; `flow.spec` 4/4 + `formula.spec` 2/2) |
| A5 | `test_ops_hardkill.py` (fake engine, data tạm riêng) | **OPS TEST PASS** (đo lại đợt 3) |

**Bằng chứng định lượng (mỗi số đếm bằng `pytest --co`, đo thật đợt 4, tổng = 154)**:

| File test mới cho các phát hiện | Số test | Phát hiện |
|---|---|---|
| `unit/test_math_verify.py` | 15 | S2 (6 negative bắt buộc) |
| `unit/test_export_sanitize.py` | 5 | S3 (+1 regression chống xóa nhầm key) |
| `unit/test_model_identity.py` | 5 | **S4** (giới hạn sample vs full hash; `.pdiparams`; `identity_from_fps`) |
| `unit/test_direct_extract.py` | 6 | S2/P11 |
| `integration/test_issue_resolution_revision.py` | 4 | S1 |
| `integration/test_ops_lifecycle.py` | 6 | S5 (fault injection) |
| `integration/test_launcher_env.py` | 4 | S6 |
| `integration/test_scope_guard.py` | 3 | S7 |
| `integration/test_formula_pipeline.py` | 3 | S1–S3 (edit→revision→export→mở lại, JSON escaping) |
| `integration/test_ops_restore.py` | 1 | S5 (backup/restore **bản lạnh**) |
| `integration/test_findings.py` | 10 | S1/S3/**S4** (gồm 2 test S4 nêu dưới) |
| `unit/test_model_identity.py` (+5 đợt 4) | 10 | **F1** (inventory theo quy tắc: preprocessor/processor/tokenizer config + nested; thiếu weight → `incomplete`; rename/add/remove đổi identity; không đường dẫn tuyệt đối) |
| `unit/test_pinned_identity.py` | 6 | **F2** (pin → re-check không full-hash lại weights; đổi weight/artifact sau pin → `ModelChangedSincePin`; self-path hash đúng 1 lần/weight; mismatch tên model có flag) |
| `unit/test_visual_text_preservation.py` | 6 | **F4** (text OCR thật trên vùng hình được giữ; không bịa; text rỗng → `None`; markdown 1 lần, không nhân đôi) |

> Hai test S4 đã xác minh **có thật, được thu thập và pass** (`pytest -k` + full suite):
> `test_config_or_model_change_invalidates_cache` — job 2 cùng model → `method=cached`; đổi **nội
> dung** weights giữ nguyên kích thước → job 3 `method=ocr`, không có `cache_hit`, file cache tag
> cũ **bị xóa**; và `test_model_config_content_change_detected` — đổi `inference.yml` → identity
> đổi; xóa thư mục model → `unresolved`.

> `RecordingFakeEngine` chỉ bật trong test (`PDFCLEANER_E2E=1`); production launcher dùng engine `paddle`.
> Phạm vi trang được chứng minh bằng **cả hai**: `engine_dispatch.log` (recording adapter ghi số trang engine
> THỰC nhận) VÀ `dispatch_log.jsonl` của job — không chỉ JSON cuối.

## NHÓM B — PaddleOCR THẬT trên máy này (không mock)

| # | Lệnh | Kết quả |
|---|---|---|
| B1 | `check_environment.py` | đo lại đợt 3: du dieu kien — paddleocr 3.7.0, model cache đủ, đĩa 742.3 GB, 12 luồng |
| B2 | `verify_formula_ocr.py --pages 1-3 --report docs/FORMULA_CHECK.md` → **mã thoát 0** (chạy lại đợt 3; log `docs/formula_run0915.log/.err`, kiểm mã thoát bằng `--help` trước khi chạy) | **OCR THẬT — LẦN GỌI ENGINE THẬT** (`mode=live OCR`, không phải `--reverify`), fixture toán set thật (matplotlib mathtext): cả 3 trang tạo **block formula LaTeX đúng** và giữ **inline `$…$`**; `\dfrac→\frac` (không mất). Comparator `math_verify` **giữ toán tử** → phát hiện `<→>`, `+→−`, mất `=`, mất mẫu số/số mũ (15 unit test negative chứng minh). `ocr_raw/*.json` + `model_meta.json` (nay có SHA-256 weights **cả 2 model**) lưu kèm |
| B3 | `benchmark_pages.py --pages 6` trên SGK | đo ngày **14/09** (chưa chạy lại đợt 3; số liệu lịch sử gần nhất): model load 52.5s; trang 6 230.7s; 4 blocks; tiếng Việt đúng (`CHƯƠNG VI. THỐNG KÊ`); RAM ~8.6 GB. Chi tiết `docs/BENCHMARK.md` |
| B4 | `e2e_real_page.py --input data\raw\doc_2eefaa19dc65.pdf --page 6` | **FULL STACK THẬT, chạy lại đợt 3** (file nguồn = đúng PDF đã lưu trong library; `input/` đã trống nên dùng lại bản trong `data/raw`): **mã thoát 0**, ~300s, `method=ocr` (không cache), export `exp_452bd35909f8` checksum `8652bb324ead…`, ZIP ghi tại `docs/e2e_real_export.zip`; log `docs/e2e_real_run0915.log/.err` |
| B5 | Mở lại `e2e_real_export.zip` (bản B4 mới) + tính SHA-256 từ byte thực + quét chuỗi nhạy cảm | **TOT** (đo lại đợt 3): mọi checksum file trong `checksums_sha256` khớp byte thật; manifest **không tự hash**; **KHÔNG có** `dir`/`Users`/`[PATH] dẫn drive ở bất kỳ file nào trong ZIP; `engine_meta.model_fp` chứa **SHA-256 weights THẬT của CẢ HAI model** (lỗi "layout `weights:{}`" đã sửa — xem S4); `resolved_vl_model=PaddleOCR-VL-1.6-0.9B`; manifest có `included_pages=[6]`, `missing_pages=[]`, `status=draft`, `disk_identity`; **trường `partial:false` KHÔNG nằm trong manifest.json mà nằm trong `content.json` và trong response API export** (`export_service` dòng dựng content + dòng trả JSON) — ghi đúng vị trí, không mô tả như thể manifest có trường này |

## NHÓM C — GUI / UAT Windows

| # | Mục | Trạng thái |
|---|---|---|
| C1 | Playwright luồng chính (upload→chọn 5–7→Xử lý 3 trang→xem→tab JSON→tải ZIP đúng tên) | **PASS** (A4, `flow.spec` 4/4 — đo lại đợt 3) |
| C2 | Playwright công thức: mở trang có công thức → **KaTeX THAT render** (`span.katex`, không lỗi parse) → sửa công thức qua UI → lưu revision → export MD → **mở lại** thấy bản sửa còn nguyên | **PASS** (`formula.spec` 2/2 — đo lại đợt 3) |
| C3 | Người dùng THẬT nhấp đúp `Open_Tool.cmd` trên desktop + bấm hết luồng 5 bước | ⏳ **CHƯA NGHIỆM THU** (agent không thay bạn thao tác desktop). Đã smoke launcher qua `launch.py`/HTTP/`stop.py` + `stop` chỉ giết PID đúng danh tính tool |
| C4 | Đối chiếu **công thức hiển thị trên SGK thật** (3–5 trang phù hợp) | ⏳ **CHƯA NGHIỆM THU** — `test.pdf` trang đã OCR (5–7) là mục lục/chuyển chương/thống kê, không có phân số/căn hiển thị. Cần bạn chỉ trang nhiều công thức → chạy B2/app trên đúng trang đó |
| C5 | (Tùy chọn, SAU nghiệm thu mẫu nhỏ) Lô 10 trang + ngưỡng duyệt | ⏸ **CHƯA CHỌN THỰC HIỆN** — theo kế hoạch là bước mở rộng sau khi bạn duyệt mẫu nhỏ, **không phải gate blocker** của MVP |

---

## P01–P20 đánh giá lại theo bằng chứng

| Ca | Tiêu chí | Trạng thái | Bằng chứng |
|---|---|---|---|
| P01 | chỉ đúng trang chọn rồi dừng | PASS | A5 hard-kill (đo lại), `test_scope_guard`, `test_p01` |
| P02 | `1,5-7,7,138`→[1,5,6,7,138] | PASS | `test_api_selection` (range list), e2e "danh sách rời rạc 5-7,9 hiện 4 trang" |
| P03 | nhập sai 422, không cắt ngầm | PASS | `test_p03_invalid_selection_does_not_create_job`, e2e `bao loi khong cat` |
| P04 | không chọn → nút disabled | PASS | e2e `khong chon trang` (C1, đo lại) |
| P05 | upload không tự OCR | PASS | `test_p05_upload_does_not_start_ocr` |
| P06 | pause giữa trang, không bắt đầu trang sau | PASS | `test_p06_pause_then_resume`, `test_scope_guard` |
| P07 | dừng ngay giữ trang xong | PASS | `test_p07_cancel_now_keeps_completed` |
| P08 | restart→INTERRUPTED, resume đúng trang thiếu, **không tự chạy** | PASS | `test_p08_restart_reconcile` + `reconcile_on_boot` (job RUNNING→INTERRUPTED, không auto-restart) + A5 |
| P09 | cache cùng config+model không OCR lại | PASS | `test_p09_cache_same_config`; `test_config_or_model_change_invalidates_cache` (job2 `cached`; đổi weights→OCR lại, cache cũ bị xóa) |
| P10 | reprocess→revision mới, không ghi đè bản sửa | PASS | `test_p10_reprocess_new_revision` |
| **P11** | **direct extraction ≠ OCR scan thật** | **PASS** | `test_p11_direct_text_layer` (đọc text layer, không render) vs `test_p11b` (text+ảnh to→OCR đúng trang) vs `test_p11c` (ảnh nhỏ giữ direct+flag) + `unit/test_direct_extract` 6 ca |
| P12 | trang rỗng hợp lệ→NEEDS_REVIEW+issue | PASS | `test_p12_image_without_text` |
| **P13** | **công thức: block+inline LaTeX THẬT, render KaTeX UI, revision+export+mở lại** | **PARTIAL** | ĐẠT phần tự động + OCR-fixture-thật (B2, chạy lại đợt 3) + C2 (KaTeX+edit+export+mở lại, đo lại). **Còn thiếu**: đối chiếu Ý NGHĨA công thức trên **SGK thật** nhiều công thức (C4) → giữ PARTIAL, chưa đóng |
| **P14** | **vùng hình bỏ qua: GIỮ nguyên chữ, ĐÁNH DẤU hình bỏ qua (`skipped_visual`), KHÔNG bịa mô tả nội dung hình** | **PASS** | `normalize_blocks` giữ `skipped_visual` (type giữ; KHÔNG bịa mô tả); `_commit_page`/`compute_validator_issues` sinh issue `VISUAL_SKIPPED` + bbox; `validate_page_payload` không tính `skipped_visual` là nội dung (`test_p12`). **Sửa lỗi trích dẫn (đợt 4, xác thực lại bằng dữ liệu thật đợt 5):** bằng chứng "engine trả `skipped_visual`, `text=null`, kèm bbox" nằm ở **B3 trang 7** (`docs/benchmark_dump/page_0007_blocks.json`, snapshot 14/09 — số liệu lịch sử gần nhất, chưa chạy lại đợt 3; kiểm trực tiếp đợt 5: 2 block `skipped_visual`, bbox `[273.0, 795.0, 1355.0, 1352.0]` và `[227.0, 1447.0, 299.0, 1515.0]`, text `null`). **B4 trang 6 KHÔNG chứng minh tiêu chí này**: ZIP `e2e_real_export.zip` (content.json trang 6) không chứa block `skipped_visual` nào và không có trường `skipped_visual` ở cấp trang — khẳng định cũ "B4 trang 6 chỉ chứng minh engine trả `skipped_visual` kèm bbox" là **SAI** và đã bỏ. **Hợp đồng mới đợt này:** text OCR thật trên vùng hình được **bảo toàn** (không gán `None` mù quáng — lỗi mất dữ liệu cũ), chỉ text rỗng/khoảng trắng mới về `null`; render/export không nhân đôi text (`map_blocks`, `normalize_blocks`, `export_service._block_markdown`; tests: `test_visual_text_preservation.py` + `test_cleaning.py` đã cập nhật theo hợp đồng mới — bằng chứng cấp **unit test**, chưa có run OCR thật hiện hành cho hợp đồng "giữ text visual"). (Kiểm bảng phức tạp `table_not_simple` là đường KHÁC, không phải tiêu chí P14.) |
| P15 | một trang lỗi→COMPLETED_WITH_ERRORS + retry đúng trang | PASS | `test_p15_real_error_page`, `test_scope_guard` |
| P16 | export một phần honest (included/missing/partial) | PASS | `test_p16_partial_export_honest`, `test_failed_page_not_counted_as_success_and_export_honest`; trường `partial` đặt đúng chỗ: `content.json` + response API (B5) |
| P17 | sửa còn sau mở lại; MD/JSON cùng revision; 409 base cũ | PASS | `test_p17_edit_survives_reload_and_md_json_agree`, `test_formula_pipeline`, C2 |
| P18 | trang rời không nối đoạn | PASS | `test_p18_non_contiguous_pages_kept_separate` |
| P19 | tên có dấu/khoảng trắng + không leak vào ZIP | PASS | `test_p19_diacritic_space_filenames`, `test_pii_filename_not_leaked_into_markdown` (quét ZIP), `test_nested_metadata_path_pii_never_in_exported_zip` |
| P20 | luôn draft, không APPROVED | PASS | `test_p20_always_draft_no_approved_label` + B5 `status=draft` |

**Tổng cộng — đếm từ từng dòng bảng trên, không chỉnh tổng trước**:
**PASS 19 · PARTIAL 1 (P13) · CHƯA ĐỦ 0** = 20 ✓.
Gate **CHƯA NGHIỆM THU** nằm ở C3 (UAT desktop do người dùng) và C4 (SGK thật) — KHÔNG nằm trong
P01–P20. C5 (lô 10 trang) là bước mở rộng tự chọn, chưa được chọn thực hiện, **không phải blocker**.
**MVP chưa được kết luận hoàn thành** vì C3/C4 còn mở và P13 PARTIAL.

---

## 8 phát hiện → file/hàm · tái hiện · bản sửa · test · kết quả

**S1 — resolution theo revision + content fingerprint.**
File: `revision_service.py::apply_resolution/compute_validator_issues/block_content_fp/resolve_issue`,
`job_service.py::_commit_page`, `db.py`(migration v3 `issues.content_fp`), `api/results.py`, `client.ts`/`App.tsx`.
Tái hiện cũ: resolve FORMULA_REVIEW block A ở R1 → sửa block A thành lỗi khác ở R2 → issue cũ tự đóng (sai).
Sửa: mỗi issue lưu `content_fp` (SHA-256 nội dung liên quan); `apply_resolution` chỉ kế thừa khi **fp bằng nhau**;
fp đổi → issue MỚI OPEN, giữ lịch sử resolved cũ; resolve bắt `base_revision_id`, lệch → **409 CONFLICT**.
Test: `test_issue_resolution_revision.py` (4). **ĐẠT**.

**S2 — công thức thật.** File: `cleaning/math_verify.py`(mới), `scripts/verify_formula_ocr.py`,
`frontend/tests/formula.spec.ts`, `scripts/run_e2e_server.py`, `fixtures/formula_blocks.json`.
Tái hiện cũ: `_norm` bỏ `[^0-9a-zA-Z]` → `=`/`<`/`>`/`≥` thành rỗng → luôn khớp → không phát hiện `<→>`.
Sửa: giữ nguyên toán tử+cấu trúc, chỉ chuẩn hoá \dfrac→\frac… đã định nghĩa; expected rỗng→FAIL; bắt đủ display và inline;
không dùng substring rời rạc một mình. Test: 15 unit (6 negative bắt buộc) + C2 KaTeX render/edit/export/reopen. **ĐẠT (tự động)+B2 thật**.

**S3 — không lộ đường dẫn local.** File: `ocr/model_identity.py`(mới, hash path-free), `paddle_adapter.py::_model_identity`
(bỏ `dir`), `cleaning/export_sanitize.py::sanitize_public`(mới), `export_service.py`(áp sanitize cho manifest+issues).
Tái hiện cũ: `engine_meta.model_rev.{name}.dir = [PATH]<me>\…` vào manifest.
Sửa: identity không chứa đường dẫn; sanitize cấu trúc mọi metadata đầu ra (bỏ key-loại-đường-dẫn/`dir`/home, redact
đường dẫn giá trị + email/phone trong text, GIỮ hex/số toán học).
**Bug thật phát hiện + sửa trong đợt 3**: regex khóa `blocked key` dùng `search` không neo → mọi key **chứa** con
`path`/`dir`/`root` bị xóa cả key (test `test_root_named_boolean_key_is_NOT_dropped` FAIL thật khi xác minh lại).
Sửa: `_BLOCKED_KEYS` **khớp chính xác toàn bộ tên** (`^…$`) → `some_path` giữ key + giá trị `[PATH_REDACTED]`,
`dir`/`raw_path`… vẫn bị loại; giá trị đường dẫn luôn bị redact bất kể tên key nên không giảm an toàn.
Test: `test_export_sanitize.py` (5) + `test_nested_metadata_path_pii_never_in_exported_zip` + B5. **ĐẠT**.

**S4 — model identity + cache.** File: `model_identity.py`, `job_service.py::_current_model_fp/_process_page`.
**Truy vết thứ tự thật (đợt 3)**: `start`/`_run_job` → `_current_model_fp()` đọc đĩa **1 lần/job** với SHA-256 **ĐẦY ĐỦ**
weights+config → `pin` (`_pinned_fp`, dưới khóa `_mu`; reprocess cũng pin trước khi xử lý trang) → MỖI trang chỉ dùng
tag đã pin để tra cache (`_process_page` bước 2); `tag="unresolved"` (model thiếu/lỗi đọc đĩa) → **cấm cache READ**;
OCR xong ghi cache dưới tag pin + **xóa** file cache tag khác của cùng trang. Kết luận: **cache hit không dựa trên
sample-fingerprint hay identity cũ** — sample-fp chỉ dùng cho `model_rev` provenance + `ocr_ready` health.
Hai sửa thật trong đợt 3:
(a) `_current_model_fp` trước đây hash đầy đủ **2 lần/job** (`fps` rồi `identity_hash` đọc lại model) → refactor
`identity_from_fps` để **xác minh đầy dung DUNG MỘT lần** rồi pin (giá trị tag bất biến, có test tương thích);
(b) whitelist phần mở rộng weight **thiếu `.pdiparams`** — file weight THẬT của `PP-DocLayoutV3`
(`inference.pdiparams`, 130 806 572 B) chưa từng được hash → đổi weights layout không làm đổi tag cache
(manifest ZIP cũ lộ đúng chỗ hỏng: `weights:{}`). Đã thêm `.pdiparams` + `inference.json` (cấu trúc network)
vào diện hash; **bằng chứng sau sửa**: ZIP B4 mới có SHA-256 của cả hai model (B5).
Cơ chế/giả định/giới hạn (chính xác): full SHA tính 1 lần/job nên **không** hash nhiều GB mỗi trang; giả định
weights không đổi giữa chừng trong lúc job chạy (identity pin theo job); giới hạn: file weight có phần mở rộng
ngoài whitelist sẽ không được hash; sample-fingerprint (head/mid/tail+size) **không** phát hiện byte đổi ngoài
3 cửa sổ — chứng minh bằng unit test, nhưng cache không dùng nó để quyết định. Test đổi byte **ngoài vùng sample,
giữ nguyên kích thước và mtime** (dùng model giả nhỏ, KHÔNG đụng model thật): có sẵn
(`test_sample_fingerprint_misses_out_of_window_byte` + `test_full_fingerprint_catches_out_of_window_and_same_size`)
+ mới thêm `test_paddle_pdiparams_weights_are_hashed`, `test_identity_from_fps_equals_identity_hash`. Test cũ
**không** còn sửa `model_identity.json` giả lập nữa. **ĐẠT** (tự động + provenance thật B4/B5).

**S5 — temp/upload/finalize.** File: `api/documents.py`(stream 413/507, rollback rename, rollback DB, hash-race),
`job_service.py::cleanup_orphan_artifacts`, `main.py`(startup cleanup), `_render_page_png` (tmp `<page>_<attempt>`).
Tái hiện: hard-kill → PNG sót `job/tmp`; `.part`/raw orphan khi lỗi.
Sửa: reconcile-then-cleanup dọn tmp của job KHÔNG chạy (giữ job RUNNING), dọn `.part`, dọn raw orphan **chỉ khi**
không document nào tham chiếu; DB commit fail → rollback raw; rename fail → dọn `.part`, 507.
Test: `test_ops_lifecycle.py` (6 fault injection). **ĐẠT**.

**S6 — setup/launcher.** File: `scripts/check_interpreter.py`(mới), `setup.cmd`(validate interpreter 3.13/64bit/paddle
thay vì `if exist`), `main.py::health`(`ocr_ready`), `App.tsx`(banner OCR chưa sẵn sàng).
Tái hiện: `PDFCLEANER_PY` trước chỉ kiểm file tồn tại; thiếu model → app vẫn 'sẵn sàng' giả.
Sửa: kiểm interpreter **thực chạy được + đúng 3.13 + 64-bit + import paddleocr**; `npm ci` khi có lock; thiếu model →
`/api/health.ocr_ready=false` + banner, app **vẫn mở** (xem kết quả cũ/direct extraction), trang cần OCR báo MODEL_FAILED rõ.
Test: `test_launcher_env.py` (4). **ĐẠT**; double-click desktop = C3 (chờ bạn).

**S7 — bảo toàn chọn trang.** File: test `test_scope_guard.py`; dùng `engine_dispatch.log` + `dispatch_log.jsonl`.
**ĐẠT**: 5–7 → engine chỉ {5,6,7}; retry/cache/resume/cancel/trang-lỗi không vượt tập; export included/missing đúng.

**S8 — snapshot nguồn/bằng chứng tách bạch, không vòng lặp, không lộ máy.**
File: `scripts/hash_source.py`, `scripts/hash_evidence.py`.
Lỗi cũ: bằng chứng nghiệm thu gắn với bản mã không xác định (không có manifest nguồn), và có nguy cơ đưa log thô
(chứa `[PATH]<me>\…`, đường dẫn dự án tuyệt đối) vào gói chia sẻ; báo cáo trích số liệu/aggregate không khớp
manifest thực tế.
Sửa/cách tách: **SOURCE_SNAPSHOT** gom mã + launcher + lockfile + cấu hình hành vi (`config.example.json`, fixtures,
`*.spec.ts`) bằng danh sách thư mục/đuôi + explicit files, **loại** `config.json` runtime, `data/`, cache, secrets,
`node_modules`, `dist`; không tự hash chính nó. **EVIDENCE_SNAPSHOT** gom báo cáo/artifact/`ocr_raw`/ZIP + **log đã
sanitize** (cơ chế regex fail-closed — xem mục Snapshot), liệt kê `SOURCE_SNAPSHOT.sha256` như một entry bình thường
→ tham chiếu **một chiều** evidence→source; source không chứa bất kỳ tham chiếu nào ngược lại; aggregate chỉ tính trên
danh sách file đã loại chính file manifest. Cách kiểm chứng đã chạy thật: đọc trực tiếp 2 manifest (số file 91/21,
không có dòng trỏ tới chính nó), **quét case-sensitive toàn bộ file trong manifest** tìm chuỗi đường dẫn/username THẬT
(mẫu: username máy, `[PATH]<user>\`, `[PATH]<user>/`, đường dẫn dự án drive-letter) — phát hiện `BENCHMARK.md` + `benchmark_dump/summary.json` (bản 14/09,
sinh trước khi sửa S3) còn leak `dir = [PATH] → đã sanitize bổ sung và ghi chú trong chính file (đường dẫn
`tường thuật/<placeholder>`, `dir → [PATH]`; số đo không đổi). Quét lại: **sạch** (chỉ còn ví dụ masked `<me>` và
chính chuỗi pattern được nêu làm mô tả). Chạy `hash_evidence.py` ra file tạm kiểm exit 0 trước khi ghi manifest thật;
đối chiếu aggregate ghi trong báo cáo này bằng cách mở trực tiếp `SOURCE_SNAPSHOT.sha256`. Kết quả đếm file lấy
**từ manifest cuối**, không mặc định đổi số cũ.

---

## Hạn chế còn mở (trung thực)

1. UAT desktop bởi người dùng thật (C3). 2. Công thức hiển thị trên SGK thật 3–5 trang (C4).
3. Lô 10 trang + ngưỡng duyệt (C5 — chưa chọn, không phải blocker). 4. Tốc độ CPU ~3.5–7 phút/trang; chưa thử GTX 1650.
5. Detector PII không tương đương chứng nhận sạch PII. 6. B3 là số đo 14/09 (chưa chạy lại ở đợt 3).
7. `input/test.pdf` đã bị dọn khỏi thư mục `input/`; B4 đợt 3 chạy trên đúng file đã lưu `data/raw/doc_2eefaa19dc65.pdf`.
8. `e2e_real.log/.err` ở thư mục gốc (chạy 14:26 hôm nay) thuộc lần chạy ZIP **cũ** (trước sửa `.pdiparams`) — đã được
   supersede bởi `docs/e2e_real_run0915.*`; giữ file gốc cho bạn tự quyết định xóa.

## Vị trí dữ liệu / vận hành

`data/raw` nguồn, `data/jobs` artifact theo trang/revision, `data/cache/ocr` (theo doc-hash+page+config+**model-tag
đĩa đã verify**), `data/exports` ZIP/MD/JSON, `data/app.db`.
**Backup = copy nguyên `data/` CHỈ KHI TOOL ĐÃ DỪNG HOÀN TOÀN** (chạy `Stop_Tool.cmd`, xác nhận không còn server/worker
nào ghi — SQLite + file artifact đang mở bản sao có thể lệch thời điểm). `test_ops_restore.py` kiểm restore cho
**bản copy lạnh** đó; **không** có cơ chế backup-nóng được kiểm thử, nên copy thư mục đang chạy **không được coi là
backup an toàn**.
Mở: `Open_Tool.cmd`. Đóng: `Stop_Tool.cmd` (chỉ PID của tool). Kiểm môi trường: `check_environment.py`;
kiểm interpreter: `check_interpreter.py <python>`.

---

## LỊCH SỬ (kết quả cũ — không còn là trạng thái hiện hành)

**Đợt 2 (15/09/2026):** ghi "131 passed" và sau đó "134 passed" — **cả hai không phản ánh đúng** lần chạy cuối
(đầu đợt 3 xác minh: suite có 1 FAILED — sanitizer xóa nhầm key; bug đã sửa + 2 test S4 mới → 137). Phép cộng
cũ "93 → 131 = +38" đúng số học nhưng dựa trên số chốt sai; **bãi bỏ**, chỉ còn số hiện hành **137**.
ZIP/e2e/model_meta của đợt 2 mang identity **thiếu weights layout** (`.pdiparams`) — superseded bởi B4/B5 đợt 3.

**OC00–OC08 (14/09/2026, bản đầu):** dựng dự án, schema/chọn trang, kho tài liệu+preview, adapter OCR thật+benchmark
(model 49.3s, p5 395.9/p6 216.6/p7 228.1s), job dispatcher+checkpoint, làm sạch+revision+export, UI React+TS strict,
launcher Windows, nghiệm thu **73 passed**, e2e OCR thật trang 6. (Chi tiết: `IMPLEMENTATION_STATUS.md` mục lịch sử.)

**Rà soát đợt 1 (15/09/2026):** xác minh 8 phát hiện; sửa `engine_meta` mixed-export, nhãn `needs_visual_review`;
nâng cấp fixture công thức từ vẽ tay→toán set; thêm `hash_source.py`; **93 passed**, Playwright 4/4. (Superseded.)
