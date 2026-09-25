# Note kiểm toán finding còn mở — PDF Cleaner MVP v1.1

Ngày kiểm tra: 15/09/2026  
Phạm vi: đối chiếu mã, test và evidence hiện tại với prompt đóng bốn finding F1–F4.  
Kết luận: **chưa đủ cơ sở tuyên bố “VERIFY HOÀN TẤT — TẤT CẢ KHỚP”.**

Note này chỉ ghi nhận kết quả kiểm toán. Trong lượt kiểm tra này không sửa mã, không sửa báo cáo nghiệm thu và không cập nhật hai snapshot manifest.

## 1. Trạng thái tóm tắt

| Hạng mục | Trạng thái kiểm toán | Kết luận ngắn |
|---|---|---|
| F1 — Inventory model identity | **PARTIAL** | Inventory đệ quy đã tốt hơn bản hardcode, nhưng chưa xác minh tính đầy đủ của model sharded/artifact bắt buộc. |
| F2 — Một lần full-hash mỗi job | **OPEN / BLOCKER** | Re-check bằng sample có thể chấp nhận weight đã đổi; đường fallback có thể ghi cache dưới tag không thuộc model worker thực dùng. |
| F3 — Evidence/path sanitization | **OPEN / BLOCKER** | Hash và sanitize chưa tách; sanitizer phá URL; ZIP không đọc được bị bỏ qua; ZIP bị thay tại chỗ; thiếu test; có file tạm lọt vào evidence. |
| F4 — P14 visual text | **PARTIAL** | Phần mã và unit test phù hợp, nhưng báo cáo vẫn gán bằng chứng `skipped_visual` cho B4 trang 6 dù ZIP B4 không có block đó. |
| Báo cáo/snapshot | **INCONSISTENT** | Snapshot khớp byte nhưng hai báo cáo đang mô tả hai trạng thái khác nhau. |
| C3 / C4 / P13 | **OPEN đúng** | Việc chưa tuyên bố nghiệm thu MVP ở ba gate này là đúng. |

## 2. F1 — Inventory model identity chưa kiểm tra đủ artifact bắt buộc

### Phần đã đúng

- `backend/app/ocr/model_identity.py:118-129` duyệt file đệ quy và dùng đường dẫn tương đối làm key.
- Config, tokenizer, preprocessor, file nested và weight theo extension đều tham gia fingerprint.
- Thêm, xóa, đổi tên hoặc đổi nội dung artifact làm đổi identity.
- Model không có weight nào trả `status='incomplete'`.
- `JobManager._current_model_fp()` dùng `all(status == 'ok')`, không còn chấp nhận identity một phần giữa hai model.

### Lỗi/logic còn thiếu

`model_fingerprint()` tại `backend/app/ocr/model_identity.py:168-171` chỉ kiểm tra điều kiện `weights` có rỗng hay không. Nó không kiểm tra các shard được khai báo trong `*.safetensors.index.json` có tồn tại đầy đủ.

Probe độc lập:

1. Tạo index tham chiếu `model-00001-of-00002.safetensors` và `model-00002-of-00002.safetensors`.
2. Chỉ tạo shard thứ nhất.
3. Gọi `model_fingerprint(full=True)`.

Kết quả:

```text
F1_MISSING_REFERENCED_SHARD_STATUS=ok
F1_INVENTORY=['model-00001-of-00002.safetensors', 'model.safetensors.index.json']
```

Điều này không khớp yêu cầu prompt: thiếu artifact bắt buộc hoặc chưa xác minh đầy đủ thì identity không được hợp lệ. Cache cũ có thể không hit vì inventory đổi, nhưng việc gắn `status='ok'` cho một model không đầy đủ vẫn sai hợp đồng.

### Điều kiện đóng F1

- Kiểm tra mọi shard/file bắt buộc được index/config tham chiếu đều tồn tại và đã hash.
- Thiếu hoặc không đọc được một artifact tham chiếu phải trả `incomplete`/`unresolved`, không trả `ok`.
- Thêm regression test cho index đủ shard, thiếu shard và shard không đọc được.

## 3. F2 — Cơ chế pin chưa bảo toàn correctness

### 3.1. Sample re-check bỏ sót thay đổi weight

`backend/app/ocr/paddle_adapter.py:125-145` chỉ so sánh inventory, size, full SHA của file nhỏ và `sample_fp` head/mid/tail cho weight. Đây không tương đương full identity đã pin.

Probe độc lập:

1. Full-hash weight 20 MB để tạo pin.
2. Đổi một byte tại offset 6 MB, nằm ngoài ba cửa sổ sample.
3. Giữ nguyên size và mtime.
4. Gọi `_model_identity()` bằng pin cũ.

Kết quả:

```text
F2_OUTSIDE_SAMPLE_ACCEPTED=YES
identity_source=pinned_job
model_rev_still_old=True
```

Worker có thể dùng dữ liệu model khác identity/cache tag mà manager đã pin. Điều này vi phạm yêu cầu “full-hash đúng một lần/job nhưng không được giảm correctness”.

Test `backend/app/tests/unit/test_pinned_identity.py:80-87` chỉ dùng weight 8 KB; file nhỏ nằm trọn trong sample nên không bắt được lỗi thực tế này. Test khác tại `test_model_identity.py` chỉ chứng minh full hash bắt được byte ngoài sample, không chứng minh đường manager → worker re-check bắt được.

### 3.2. Fallback self-hash không được đối chiếu trước khi ghi cache

- `backend/app/services/job_service.py:427-431` nuốt `OSError` khi ghi pinned identity.
- `backend/app/worker/process.py:38-45` bỏ pin hỏng và fallback sang self-full-hash.
- `backend/app/services/job_service.py:509-521` chỉ log `identity_self_hashed`, sau đó vẫn ghi cache bằng `tag` manager đã pin.

Không có kiểm tra bắt buộc `engine_meta.model_rev == tag`. Vì vậy pin file thiếu/hỏng, pin lệch tên model hoặc worker tự resolve model khác có thể tạo cache gắn sai identity.

### 3.3. Test chưa đúng mức end-to-end prompt yêu cầu

Sáu test mới chủ yếu gọi trực tiếp `_model_identity()` với fake pipeline. Chưa có test chứng minh đầy đủ:

- cache miss qua `JobManager → WorkerSupervisor → process → PaddleVLAdapter.load`;
- cache hit không khởi tạo/hash model thừa;
- job nhiều trang chỉ dùng một full identity;
- engine reuse/restart giữ metadata đúng;
- pin file thiếu/hỏng hoặc `pinned_mismatch` không thể ghi cache bằng tag cũ;
- byte đổi ngoài sample giữa pin và load bị chặn.

### Điều kiện đóng F2

- Thiết kế lại điểm sở hữu identity để model worker thực dùng và cache tag luôn là cùng một identity đã full-verify.
- Nếu fallback self-hash xảy ra, manager phải dùng tag worker trả về hoặc fail job; tuyệt đối không ghi dưới tag pin khác.
- Không dùng sample fingerprint như bằng chứng toàn vẹn tương đương SHA-256 đầy đủ.
- Bổ sung các test cache-miss, cache-hit, multi-page, engine reuse và failure/fallback nêu trên.

## 4. F3 — Evidence sanitizer/hash chưa đáp ứng prompt

### 4.1. Hash và sanitize vẫn trộn chung

`scripts/hash_evidence.py:365-395` mặc định gọi `sanitize_docs_in_place()` rồi mới validate/hash. Ngay cả `--no-sanitize`, `_collect()` vẫn gọi `build_sanitized_logs()` và ghi lại file trong `docs/sanitized_logs/`.

Do đó thao tác được gọi là hash/verify vẫn có thể thay đổi nguồn evidence. Điều này trái yêu cầu tách rõ:

1. chuẩn bị/sanitize;
2. hash/validate read-only.

### 4.2. Regex Windows path phá URL

Regex tại `scripts/hash_evidence.py:57` không có ranh giới đầu chuỗi phù hợp và nhận nhầm phần `s:/` hoặc `p:/` trong URL là đường dẫn ổ đĩa.

Probe:

```text
https://example.com/a => http[PATH]
http://example.com/x  => htt[PATH]
```

Hậu quả đã xuất hiện trong evidence hiện tại, ví dụ nhiều log trong `docs/` chứa `http[PATH]`. Prompt yêu cầu sanitizer không phá URL, LaTeX và đường dẫn tương đối; yêu cầu này chưa đạt.

### 4.3. ZIP/encoding không fail-closed

- `sanitize_zip_members()` tại `scripts/hash_evidence.py:205-210` giữ nguyên member không decode được và tiếp tục.
- `validate_docs_clean()` tại `scripts/hash_evidence.py:323-329` cũng bỏ qua member đó.

Probe với ZIP chứa member byte không phải UTF-8 trả:

```text
F3_UNKNOWN_ZIP_VALIDATION=PASSED_SILENTLY
```

Đây là fail-open, trái yêu cầu file/định dạng không xác minh được phải báo rõ và chặn phát hành.

`_decode_strict()` còn thử `cp1252` cho mọi byte không phải UTF-8. Việc decode thành công về mặt codec không chứng minh encoding nguồn thực sự là cp1252; cần khai báo nguồn/encoding rõ thay vì đoán.

### 4.4. ZIP bị thay tại chỗ, không có bản gốc tách biệt

`sanitize_zip_members()` tạo ZIP mới rồi `replace(path)` tại `scripts/hash_evidence.py:218-225`. Không có thư mục/bản lưu original riêng như prompt yêu cầu khi cần sửa ZIP evidence.

### 4.5. Atomic write để lại file tạm trong evidence

`_atomic_write()` tại `scripts/hash_evidence.py:229-248` gọi `tempfile.mkstemp()` nhưng không đóng file descriptor `fd`. Trên Windows, `replace()` có thể thất bại vì chính descriptor này còn mở; fallback ghi file đích nhưng không xóa temp.

`docs/EVIDENCE_SNAPSHOT.sha256:22-28` hiện chứa bảy file `tmp*.tmp`, đều là bản sao của artifact JSON. Như vậy tổng “28 evidence” đã bị phình bởi file trung gian, không phải 28 artifact độc lập có chủ đích.

### 4.6. Thiếu regression test F3

Không có test gọi `sanitize_text`, `sanitize_json_text`, `sanitize_zip_members`, `validate_docs_clean` hoặc CLI hash evidence. Con số “17 test mới” thực tế là 5 F1 + 6 F2 + 6 F4; F3 có 0 test mới dù prompt yêu cầu test cho:

- Windows/UNC/POSIX path;
- URL và đường dẫn tương đối không bị phá;
- LaTeX/JSON escape không bị nhận nhầm;
- JSON lồng nhiều tầng;
- ZIP member và CRC mới;
- encoding lỗi/định dạng không xác minh được phải fail;
- hash/validator không làm thay đổi input.

### Điều kiện đóng F3

- Tách CLI prepare/sanitize có mutation khỏi CLI hash/verify read-only.
- Sửa regex và có regression test URL/LaTeX/relative path.
- Unknown/binary/encoding không xác minh được phải fail hoặc được phân loại rõ theo allowlist, không `continue` im lặng.
- Giữ ZIP original riêng trước sanitize; validate lại member, CRC và central directory.
- Đóng descriptor, xóa temp an toàn và loại toàn bộ temp khỏi evidence manifest.
- Chạy test F3 đầy đủ rồi tái tạo evidence sạch.

## 5. F4 — Mã phù hợp nhưng báo cáo còn suy diễn sai evidence

### Phần mã đã đúng

- `backend/app/cleaning/normalize.py:58-63` giữ text OCR thật của `skipped_visual`; chỉ text rỗng về `None`.
- `backend/app/services/export_service.py:35-46` xuất ghi chú chưa xác thực và text đúng một lần, không bịa mô tả hình.
- Sáu test `test_visual_text_preservation.py` bao phủ giữ text, text rỗng, normalize và không nhân đôi khi xuất Markdown.

### Báo cáo còn sai

`docs/ACCEPTANCE_REPORT.md:134` viết rằng B4 trang 6 “chứng minh engine trả `skipped_visual` kèm bbox”. Kiểm tra trực tiếp `docs/e2e_real_export.zip/content.json` cho thấy B4 chỉ có:

```text
heading: 2
paragraph: 2
skipped_visual: 0
```

Bằng chứng đúng cho `skipped_visual`, `text=null`, bbox là B3 trang 7 tại `docs/benchmark_dump/page_0007_blocks.json`, snapshot ngày 14/09. Không được tiếp tục gán bằng chứng đó cho B4.

### Điều kiện đóng F4

- Sửa câu P14 để B3 trang 7 là nguồn duy nhất cho bằng chứng `skipped_visual` hiện có.
- Ghi rõ B4 trang 6 không chứng minh tiêu chí này.
- Nếu muốn có evidence hiện hành cho hợp đồng “giữ text visual”, chạy lại OCR/evidence phù hợp; không suy diễn từ unit test sang ZIP B4 cũ.

## 6. Báo cáo và snapshot chưa phải single source of truth

`docs/IMPLEMENTATION_STATUS.md` vẫn ghi:

- dòng 3/14: trạng thái hiện hành là đợt 3;
- dòng 6: SOURCE 91 file, aggregate `e27ae846…`;
- dòng 8: EVIDENCE 21 file;
- dòng 27: pytest 137;
- dòng 21: mô tả S4 cũ, chưa phản ánh chính xác logic pin/fallback đợt 4.

Trong khi `docs/ACCEPTANCE_REPORT.md` ghi đợt 4, SOURCE 94, EVIDENCE 28 và pytest 154. Hai tài liệu cùng nằm trong evidence nhưng mâu thuẫn về trạng thái hiện hành.

`scripts/verify_snapshots.py` chạy thành công chỉ chứng minh:

- từng path đang liệt kê khớp byte hiện tại;
- aggregate tính đúng theo danh sách;
- quan hệ EVIDENCE → SOURCE một chiều.

Nó không chứng minh nội dung báo cáo đúng, danh sách evidence có chủ đích, sanitizer không phá dữ liệu hoặc finding đã được đóng.

## 7. Kết quả lệnh kiểm tra hiện có

```text
pytest backend/app/tests -q
154 passed, 1 warning

python scripts/verify_snapshots.py
SOURCE: 94 entry khớp byte
EVIDENCE: 28 entry khớp byte
one-way reference: OK
```

Hai kết quả trên là thật nhưng không phủ các counterexample F1/F2/F3 và lỗi trích dẫn F4 đã nêu trong note.

Frontend không đổi trong đợt 4 nên việc không chạy lại typecheck/Playwright có thể chấp nhận nếu báo cáo tiếp tục ghi rõ số liệu là của đợt 3. C3, C4 và P13 vẫn phải giữ mở.

## 8. Thứ tự xử lý đề xuất

1. **F2:** chặn identity/cache mismatch và loại tính đúng giả từ sample re-check.
2. **F3:** tách sanitize khỏi hash, sửa regex URL, fail-closed ZIP/encoding, bổ sung test và làm sạch temp evidence.
3. **F1:** xác minh shard/artifact bắt buộc được tham chiếu trước khi trả `ok`.
4. **F4/report:** xóa suy diễn sai về B4 và đồng bộ `IMPLEMENTATION_STATUS.md` với trạng thái thật.
5. Chạy lại toàn bộ test liên quan, tái tạo SOURCE/EVIDENCE snapshot, rồi mới cân nhắc đóng F1–F4.

## 9. Verdict được phép dùng ở thời điểm hiện tại

```text
F1 = PARTIAL
F2 = OPEN / BLOCKER
F3 = OPEN / BLOCKER
F4 = PARTIAL (code/test đạt, evidence report chưa đạt)
C3 = OPEN
C4 = OPEN
P13 = PARTIAL
MVP = CHƯA NGHIỆM THU
```

Không nên dùng câu “toàn bộ chuỗi đóng finding đã xong” cho đến khi mọi điều kiện đóng trong note này có bằng chứng tái hiện và regression test tương ứng.
