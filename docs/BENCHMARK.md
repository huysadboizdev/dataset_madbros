# Kết quả benchmark OCR thật (OC03)

Ngày đo: 14/09/2026 · Máy: Windows 10, i5-12400F, RAM 16 GB, GTX 1650 (chạy **CPU**).
Lệnh tái hiện:

```
python scripts\benchmark_pages.py ^
  --input "input\test.pdf" --pages "5-7" --device cpu --dump docs\benchmark_dump
```
(`python` = interpreter venv 3.13 cấu hình qua `PDFCLEANER_PY`; đường dẫn đã sanitize — xem ghi chú cuối file)

Script dùng đúng `page_selection.parse_page_expression` và `PaddleVLAdapter` của ứng dụng —
không có pipeline phụ, nên không thể OCR ngoài phạm vi trang chọn.

## Cấu hình đã khóa

| Thành phần | Phiên bản |
|---|---|
| Python | 3.13.14 (venv 64-bit, `PDFCLEANER_PY`) |
| paddlepaddle | 3.3.0 |
| paddleocr | 3.7.0 |
| paddlex | 3.7.2 |
| pypdfium2 | 5.13.0 |
| Model nhận dạng | PaddleOCR-VL-1.6 (`%USERPROFILE%\.paddlex\official_models\PaddleOCR-VL-1.6`) |
| Model bố cục | PP-DocLayoutV3 (mặc định pipeline v1.6) |
| DPI render trang | 200 |

Lưu ý API thực tế: **không** truyền `vl_rec_model_name`/`layout_detection_model_name`
vào `PaddleOCRVL` trên paddleocr 3.7.0 — đường dẫn đó báo
`No engine bindings registered for model 'PaddleOCR-VL-1.6'`. Giá trị mặc định
của `pipeline_version='v1.6'` đã trỏ đúng model đã cache. Adapter đã làm theo.

## Số đo trên 3 trang thật của test.pdf (138 trang, không có lớp chữ — 0 ký tự PDF text)

| Trang PDF | Thời gian OCR | Số block | Ký tự | Vùng hình bỏ qua | RAM đỉnh |
|---|---|---|---|---|---|
| Nạp model (một lần) | 49,3 s | — | — | — | — |
| 5 (Mục lục) | 395,9 s | 4 | 835 | 0 | ~8,7 GB |
| 6 | 216,6 s | 4 | 557 | 0 | (đã tính chung) |
| 7 (Chương I mở đầu) | 228,1 s | 15 | 1.188 | 2 | |

Không có cảnh báo engine trả về; confidence không có (engine không xuất → để null, không bịa số).

## Đối chiếu chất lượng (người đọc kiểm tra nhanh file `page_000X_blocks.json`)

- Tiếng Việt **có dấu nhận đúng**: `Mục lục`, `Chương I. MỆNH ĐỀ VÀ TẬP HỢP`,
  `Bài 1. Mệnh đề`, `Các phép toán trên tập hợp`…
- Bố cục: heading tách khỏi paragraph; 2 vùng hình ở trang 7 được phân loại
  `skipped_visual` với bbox pixel, không suy luận nội dung hình.
- Trang 5 nhận diện tiêu đề mục lục + khối nội dung lớn + số trang — thứ tự đọc đúng.
- Hạn chế ghi nhận: block TOC trang 5 gộp nhiều dòng vào một paragraph (chấp nhận được
  cho bản nháp, người dùng sửa theo block trong UI); có lỗi nhỏ nhận dạng ở trang 7
  ("MÊNH ĐỀ" thay vì "MỆNH ĐỀ" ở một heading) → đúng tinh thần **bản nháp cần kiểm tra**.

## Hệ quả thiết kế (đã áp dụng)

1. CPU ~3,5–7 phút/trang → UI **bắt buộc** hiển thị ETA tách riêng thời gian nạp model
   (đã làm: `model_phase`, ETA chỉ hiện sau ≥2 trang đo được).
2. Không cam kết tốc độ; không promise xử lý nhanh cả cuốn.
3. Model nạp 1 lần/worker cho cả job (`WorkerSupervisor` giữ process sống giữa các trang).
4. RAM đỉnh ~8,7 GB trên nền 16 GB → chỉ 1 worker, 1 trang; không prefetch.
5. Chưa thử GTX 1650 4 GB; theo kế hoạch, GPU chỉ cân nhắc sau khi bản CPU đạt.

Kết luận OC03: **engine thật hoạt động, đầu ra có văn bản Việt ngữ đối chiếu được** —
không phải mock, không phải "chỉ tạo file". Chất lượng mức nháp, cần người duyệt.

> **Ghi chú sanitize (đợt 3, 15/09/2026):** bản gốc 14/09 chứa đường dẫn tuyệt đối kèm
> username máy đo (`[PATH]) và đường dẫn venv — do lỗi S3 chưa sửa vào lúc đó. Các
>chuỗi này đã thay bằng `%USERPROFILE%`/tường thuật; số liệu đo không đổi. File
> `benchmark_dump/summary.json` gốc cũng có field `dir` leak tương tự → đã redact giá trị
> `dir` thành `[PATH]` (artifact của mã TRƯỚC bản sửa S3, giữ làm bằng chứng lỗi cũ).
