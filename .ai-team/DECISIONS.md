# DECISIONS — pdf-cleaner-tool / SOP Dataset

| # | Ngày | Quyết định | Lý do | Alternative bị loại | Agent đề xuất |
|---|---|---|---|---|---|
| D1 | 2026-09-25 | Giữ nguyên tool FastAPI+SQLite+React, **mở rộng theo lớp** thay vì viết lại thành pipeline mới | Tool hiện có 189 test pass, revision/issue/export/checksum đã nghiệm thu; viết lại = mất toàn bộ bằng chứng | (a) Viết service mới tách rời; (b) chuyển sang Airflow/Prefect | team-manager |
| D2 | 2026-09-25 | Tầng dataset mới đọc từ tầng job/revision cũ, **không đổi format export cũ** | `content.md/json/manifest.json` là hợp đồng đã nghiệm thu (B4/B5); đổi = hồi quy | Đổi luôn content.json sang exam schema | team-manager |
| D3 | 2026-09-25 | Làm **GĐ0 (đóng F2/F3 BLOCKER)** trước khi mở rộng dataset | Mở rộng trên nền còn lỗ hổng identity/sanitize = tích lũy nợ, đặc biệt nguy hiểm khi PII/docx/pptx vào pipeline | Song song GĐ0 + GĐ1 | team-manager |
| D4 | 2026-09-25 | `source_id` là **danh tính chuẩn**; `document_id` hiện có chỉ là định danh file kỹ thuật nội bộ | SOP §2.1 yêu cầu `source_id` ổn định + `source_version`; đổi tên file không tạo danh tính mới | Tái dùng `document_id` làm source_id | team-manager |
| D5 | 2026-09-25 | Trạng thái SOP tách khỏi JobState hiện có | JobState mô tả *tiến trình OCR*, SOP status mô tả *vòng đời dữ liệu* (APPROVED/EXPORTED). Gộp = sai ngữ nghĩa | Map JobState→SOP status | team-manager |
| D6 | 2026-09-25 | Bổ sung dependency: `jsonschema`, `python-docx`, `python-pptx`, `qdrant-client`, BGE-M3 runtime, tokenizer | Bắt buộc bởi SOP §3.2/§4/§7/§8 | Tự viết parser docx/pptx (rủi ro cao) | team-manager |
| D7 | 2026-09-25 | **CHỐT** — Qdrant chạy **local Docker** (giữ tới GĐ6) | User chốt; dữ liệu ở local, không tốn phí cloud | Qdrant Cloud; embedded local mode | user |
| D8 | 2026-09-25 | **CẦN USER QUYẾT** — mô hình đích cho fine-tune (context length, tokenizer) | SOP §8.5 yêu cầu "chốt mô hình đích trước khi xuất"; không suy ra được từ repo | — | team-manager |
| D9 | 2026-09-25 | **CẦN USER QUYẾT** — nguồn dữ liệu thật + quyền sử dụng (SOP §1.1/§1.3) | Không thể tự quyết về bản quyền/phạm vi; là điều kiện tiếp nhận nguồn | — | team-manager |
| D10 | 2026-09-25 | **CẦN USER QUYẾT** — 3–5 trang SGK thật có công thức để đóng gate C4 | `test.pdf` hiện tại là mục lục/thống kê, không có phân số/căn | — | team-manager |

| D11 | 2026-09-25 | **CHỐT phạm vi đợt này: GĐ0 + GĐ1 + GĐ2** | User chốt. Đây là nền bắt buộc trước mọi thứ khác; không cần hạ tầng ngoài | GĐ0-only; GĐ0–GĐ4; toàn bộ GĐ0–GĐ8 | user |
| D12 | 2026-09-25 | **Repo KHÔNG phải git repo** → không commit/PR; lưu bằng chứng bằng file + snapshot SHA-256 | `git rev-parse` → "not a git repository"; không có `rtk` | Khởi tạo git mới (ngoài phạm vi, cần user đồng ý) | team-manager |

## Câu hỏi mở cần con người

1. ~~Phạm vi thực thi ngay~~ → **ĐÃ CHỐT: GĐ0 + GĐ1 + GĐ2**.
2. Qdrant: local Docker, Qdrant Cloud, hay embedded local mode?
3. Mô hình đích fine-tune (tên + context length) để đếm token và xuất JSONL?
4. Danh sách nguồn dữ liệu + tình trạng quyền sử dụng (SOP §1.3) — nếu chưa có, GĐ1 vẫn code được nhưng phải để `HOLD_RIGHTS`.
5. Trang SGK thật để chạy C4.
