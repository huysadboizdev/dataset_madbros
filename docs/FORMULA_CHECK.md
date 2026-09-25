# Nghiệm thu công thức THẬT (fixture set bằng matplotlib mathtext)

Ngày chạy thật: 15/09/2026 (lần chạy `live OCR` đóng dấu sau đợt sửa model-identity). Lệnh: `python scripts\verify_formula_ocr.py --pages "1-3" --report docs\FORMULA_CHECK.md` · **mã thoát = 0**. Log stdout/stderr: `docs\formula_run0915.log`, `docs\formula_run0915.err` (bản sanitize nằm trong `docs\sanitized_logs\`, được hash ở EVIDENCE_SNAPSHOT). Raw per-page + verify + `model_meta.json` (SHA-256 weights **của cả 2 model**, gồm `inference.pdiparams` layout): `docs\formula_fixture\`.

Engine thật: `PP-DocLayoutV3` + `PaddleOCR-VL-1.6-0.9B` (paddleocr 3.7.0) · DPI render 220 · mode=`live OCR` · Model config: `docs/formula_fixture/model_meta.json` · raw per-page: `docs/formula_fixture/ocr_raw/`

Đối chiếu bằng `backend/app/cleaning/math_verify.verify_all`: **GIỮ** toán tử (=,<,>,≥,≤,+,−,^) và cấu trúc (\frac, √, ^); chỉ chuẩn hoá \dfrac→\frac… đã định nghĩa; bắt buộc đủ CẢ display VÀ inline; substring rời rạc không phải bằng chứng duy nhất.

| Trang | Block formula | Display OK | Inline OK | Ký hiệu thiếu | Kết luận |
|---|---|---|---|---|---|
| 1 | True | True | True | — | ĐẠT (cú pháp+hiện diện) |
| 2 | True | True | True | — | ĐẠT (cú pháp+hiện diện) |
| 3 | True | True | True | — | ĐẠT (cú pháp+hiện diện) |

## Trang 1: `$\dfrac{2x-1}{x+3} \geq 5$` + inline `Căn thức $\sqrt{x}$ xác định khi $x \geq 0$.`

- Block formula bắt được: **True** (thiếu block KHÔNG phải bằng chứng duy nhất).
- ✅ display: `$\dfrac{2x-1}{x+3} \geq 5$` → OK
- ✅ inline: `Căn thức $\sqrt{x}$ xác định khi $x \geq 0$.` → OK
- OCR trả về THẬT (đã gộp block):
  - `paragraph`: `Giá trị nhỏ nhất của biểu thức là 3.`
  - `formula`: `$$ \frac{2x-1}{x+3}\geq5 $$`
  - `paragraph`: `Căn thức  $ \sqrt{x} $ xác định khi  $ x \geq 0 $.`

## Trang 2: `$\sqrt{a^{2}+b^{2}} = \sqrt{5}$` + inline `Nếu $a^{2}+b^{2}=c^{2}$ thì tam giác vuông tại C.`

- Block formula bắt được: **True** (thiếu block KHÔNG phải bằng chứng duy nhất).
- ✅ display: `$\sqrt{a^{2}+b^{2}} = \sqrt{5}$` → OK
- ✅ inline: `Nếu $a^{2}+b^{2}=c^{2}$ thì tam giác vuông tại C.` → OK
- OCR trả về THẬT (đã gộp block):
  - `paragraph`: `Độ dài cạnh huyền bằng căn hai của 5.`
  - `formula`: `$$ \sqrt{a^{2}+b^{2}}=\sqrt{5} $$`
  - `paragraph`: `Nếu  $ a^{2} + b^{2} = c^{2} $ thì tam giác vuông tại C.`

## Trang 3: `$\frac{3x-1}{2} < x + 4$` + inline `Tập nghiệm $S = (-\infty;\, 9)$.`

- Block formula bắt được: **True** (thiếu block KHÔNG phải bằng chứng duy nhất).
- ✅ display: `$\frac{3x-1}{2} < x + 4$` → OK
- ✅ inline: `Tập nghiệm $S = (-\infty;\, 9)$.` → OK
- OCR trả về THẬT (đã gộp block):
  - `paragraph`: `Nghiệm của bất phương trình:`
  - `formula`: `$$ \frac{3x-1}{2}<x+4 $$`
  - `paragraph`: `Tập nghiệm $S = (-\infty; 9)$.`

## Kết luận

ĐẠT: mọi biểu thức (display VÀ inline) khớp về ký hiệu + toán tử + cấu trúc; LaTeX round-trip JSON nguyên ven (xem test_formula_pipeline); cú pháp basic-check sạch. Engine chuẩn hoá \dfrac→\frac (cùng phân số, không mất nội dung).

_Đây là LẦN GỌI ENGINE THẬT (không mock, không lấy log FAIL cũ làm bằng chứng PASS). Raw per-page + model_meta đã lưu kèm. ĐỐI CHIẾU Ý NGHĨA toán học CẦN NGƯỜI duyệt._