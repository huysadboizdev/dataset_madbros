# PDF Cleaner — trích xuất OCR sang Markdown / JSON

Ứng dụng Windows chạy **local hoàn toàn** (không API key, không gửi file lên cloud):
mở PDF → chọn đúng trang cần lấy → OCR local bằng PaddleOCR-VL → xem/sửa kết quả →
tải Markdown/JSON/ZIP **bản nháp**. Xử lý hết danh sách trang đã chọn thì **dừng**,
không tự chạy phần còn lại của tài liệu.

## Yêu cầu máy

- Windows 10/11, RAM ≥ 16 GB khuyến nghị (OCR CPU một trang tại một thời điểm).
- Môi trường Python 3.13 có PaddleOCR, trỏ qua biến `PDFCLEANER_PY` hoặc venv dự án
  (paddlepaddle 3.3.0, paddleocr 3.7.0, paddlex 3.7.2 — xem `requirements.lock.txt`).
- Model đã cache trong `%USERPROFILE%\.paddlex\official_models\`
  (PaddleOCR-VL-1.6 + PP-DocLayoutV3). Nếu thiếu, chạy một lần lệnh demo của PaddleOCR
  để tải model chính thức — sau đó mọi việc là local.
- Node.js chỉ cần khi BUILD giao diện; người dùng phổ thông không cần.

## Cài đặt

```bat
setup.cmd
```

## Dùng (5 bước)

1. **Mở tool:** nhấp đúp `Open_Tool.cmd` (trình duyệt tự mở `http://127.0.0.1:8765`).
2. **Chọn PDF:** kéo thả hoặc bấm `Chọn PDF` (thêm file KHÔNG tự chạy OCR).
3. **Chọn trang:** `Từ trang … đến trang …`, hoặc danh sách kiểu `5-10,15,20-22`,
   hoặc chủ động tick `Toàn bộ tài liệu`. Ô tóm tắt hiện chính xác số trang sẽ chạy;
   nút ghi `Xử lý N trang`. Mặc định KHÔNG chọn cả cuốn.
4. **Theo dõi:** bảng trạng thái từng trang (đang nạp model / đang OCR / đã xong),
   ETA chỉ hiện sau vài trang đo được; có `Tạm dừng sau trang này`, `Dừng ngay`,
   `Thử lại` trang lỗi. Xong đúng N trang thì job kết thúc.
5. **Xem & tải:** ảnh trang gốc cạnh Markdown (công thức render bằng KaTeX);
   sửa theo block rồi `Lưu sửa` (revision mới, không ghi đè bản cũ);
   `Hoàn tác về bản OCR`, `OCR lại trang này` (tạo revision mới để so sánh).
   Tải `Markdown` / `JSON` / `ZIP`; nếu chưa đủ trang, nút ghi rõ
   `Tải bản nháp x/N trang`.

Đóng tool: `Stop_Tool.cmd` (chỉ dừng đúng tiến trình của tool). Kết quả đã lưu nằm ở
`data/jobs/`, file xuất ở `data/exports/`, PDF gốc ở `data/raw/`.

## Lệnh kiểm thử

```bat
python scripts\check_environment.py
python -m pytest backend\app\tests -q
cd frontend && npm run typecheck && npm run build && npm run test:e2e
```
(Trong các lệnh trên, `python` là interpreter 3.13 của venv đã cấu hình ở `setup.cmd`.)

Benchmark OCR thật trên vài trang (không bao giờ tự chạy cả cuốn):

```bat
python scripts\benchmark_pages.py --input "input\test.pdf" --pages "5-7" --device cpu
```

## Hạn chế đã biết (bản nháp)

- Tốc độ CPU trên i5-12400F: khoảng **3,5–7 phút/trang SGK** (xem `docs/BENCHMARK.md`);
  lần đầu còn tốn ~50–60s nạp model. Chưa thử GTX 1650 4 GB.
- Vùng hình bị BỎ QUA có chủ đích: được ghi nhận `skipped_visual` kèm toạ độ,
  không mô tả/suy luận nội dung hình; trang phụ thuộc hình sẽ cần người xem lại.
- Đầu ra là **bản trích xuất nháp**: không tự nhận "đúng 100%", không tự giải bài,
  không gắn nhãn APPROVED theo SOP dataset.
- PDF có mật khẩu: không vượt mật khẩu — hãy cung cấp bản mở được.
