# TASKS — pdf-cleaner-tool → chuẩn SOP Dataset

Plan chi tiết: `docs/plans/2026-09-25-dataset-sop-roadmap.md`
Đánh giá gap: `.ai-team/REVIEW.md` · Quyết định: `.ai-team/DECISIONS.md`

Trạng thái: ⬜ chưa làm · 🟨 đang làm · ✅ xong · ⛔ blocked

## GĐ0 — Đóng nợ kỹ thuật (BLOCKER)
> ⛔ **BLOCKED 2026-09-25**: dispatch team-coder thất bại do **hết credit** của nhà cung cấp model:
> `credit insufficient balance: balance=14772 required=23400` (task F2+F1) và `required=16590` (task F3).
> Cần nạp credit hoặc user cho phép manager tự implement inline.

| ID | Task | Owner | Dep | Files | AC | Status |
|---|---|---|---|---|---|---|
| 0.1 | F1: verify đủ shard index | team-coder | - | `ocr/model_identity.py:118-175` | thiếu shard → `status != ok` | ⛔ blocked: credit |
| 0.2 | F2: pin identity không nhận weight đã đổi | team-coder | 0.1 | `ocr/paddle_adapter.py:125-145`, `services/job_service.py` | đổi byte ngoài sample bị phát hiện | ⛔ blocked: credit |
| 0.3 | F3: tách hash/sanitize + sanitizer an toàn | team-coder | - | `scripts/hash_evidence.py`, `cleaning/export_sanitize.py` | URL/LaTeX nguyên vẹn; ZIP hỏng fail-closed | ⛔ blocked: credit |
| 0.4 | F4 + đồng bộ báo cáo/snapshot | manager + reviewer | 0.1-0.3 | `docs/ACCEPTANCE_REPORT.md`, `docs/IMPLEMENTATION_STATUS.md`, 2 snapshot | 2 báo cáo khớp; `verify_snapshots.py` pass | ⬜ |
| 0.5 | Chạy lại verification toàn bộ | team-reviewer | 0.1-0.4 | — | pytest ≥189, tsc, build, Playwright 6, ops hardkill | ⬜ |
| 0.6 | C4: công thức trên SGK thật | manager (cần user) | — | `scripts/verify_formula_ocr.py` | exit 0 + user đối chiếu nghĩa | ⛔ chờ user chọn trang |

## GĐ1 — Dataset core (SOP §1, §2)
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 1.1 | Migration DB v4: sources/source_events/source_files | team-coder | GĐ0 | ⬜ |
| 1.2 | Sinh source_id + tên file chuẩn | team-coder | - | ⬜ |
| 1.3 | Bố cục 00_raw_restricted…06_release | team-coder | - | ⬜ |
| 1.4 | Schema metadata tối thiểu + validator | team-coder | 1.1 | ⬜ |
| 1.5 | State machine trạng thái xử lý | team-coder | 1.1 | ⬜ |
| 1.6 | API + UI nhập nguồn | coder + integration | 1.1-1.5 | ⬜ |
| 1.7 | Manifest nguồn + xuất hồ sơ | team-coder | 1.1-1.4 | ⬜ |

## GĐ2 — Cleaning chuẩn §3
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 2.1 | Xóa header/footer/watermark lặp | team-coder | GĐ1 | ⬜ |
| 2.2 | Chuẩn hóa tiếng Việt + cặp ký tự dễ nhầm | team-coder | GĐ1 | ⬜ |
| 2.3 | PII engine mở rộng + mask trong content + `[NGUOI_nn]` | team-coder | GĐ1 | ⬜ |
| 2.4 | `REQUIRES_VISUAL` + chép nhãn/công thức trong hình | team-integration | GĐ1 | ⬜ |
| 2.5 | Ingest Word + PPTX | team-integration | GĐ1 | ⬜ |
| 2.6 | Bảng không flatten | team-coder | GĐ1 | ⬜ |
| 2.7 | Liên kết ngữ liệu bài đọc Anh (`context_id`) | team-integration | GĐ1 | ⬜ |
| 2.8 | Audio thiếu → `HOLD_MISSING_CONTEXT` | team-coder | 1.5 | ⬜ |

## GĐ3 — Exam JSON §4
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 3.1 | JSON Schema đề thi | team-coder | GĐ2 | ⬜ |
| 3.2 | Builder blocks → exam object | team-coder | 3.1 | ⬜ |
| 3.3 | Validator quan hệ | team-coder | 3.1 | ⬜ |
| 3.4 | Export .md + .json liên kết source_id | team-coder | 3.2-3.3 | ⬜ |
| 3.5 | UI xem/sửa câu hỏi + đáp án | team-integration | 3.2 | ⬜ |

## GĐ4 — Review workflow §5
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 4.1 | Vai trò, reviewer ≠ cleaner | team-coder | GĐ3 | ⬜ |
| 4.2 | Bản ghi duyệt + lý do RETURNED/HOLD/REJECTED | team-coder | 1.5 | ⬜ |
| 4.3 | Issue sheet đủ trường + báo cáo lô | team-coder | 4.2 | ⬜ |
| 4.4 | UI duyệt + checklist §5.4 | team-integration | 4.2 | ⬜ |
| 4.5 | Cổng nghiệm thu GĐ1 tự động | team-coder | 4.1-4.4 | ⬜ |

## GĐ5 — Chunking §6
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 5.1 | Parser đơn vị ngữ nghĩa | team-coder | GĐ4 | ⬜ |
| 5.2 | Windower 500–800 / overlap 15–20% | team-coder | 5.1 | ⬜ |
| 5.3 | Tokenizer thật + chunk manifest | team-coder | 5.2 | ⬜ |
| 5.4 | QA máy 100% + người 10% | team-reviewer | 5.3 | ⬜ |
| 5.5 | Khối đặc biệt (đề thi/bài đọc/giáo án/khối dài) | team-coder | 5.1 | ⬜ |

## GĐ6 — RAG BGE-M3 + Qdrant §7
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 6.1 | Embedding BGE-M3 pin revision | team-coder | GĐ5 | ⬜ |
| 6.2 | Qdrant collection + payload index | team-coder | 6.1 | ⬜ |
| 6.3 | Upsert batch + vô hiệu hóa chunk cũ | team-coder | 6.2 | ⬜ |
| 6.4 | Pilot ≥60 query + Hit@5 ≥90% | coder + reviewer | 6.3 | ⬜ |
| 6.5 | Manifest chỉ mục + tái tạo | team-coder | 6.3 | ⬜ |

## GĐ7 — Fine-tune 5000 mẫu §8
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 7.1 | Sample builder | team-coder | GĐ4 | ⬜ |
| 7.2 | Chấm chất lượng 100 + lỗi loại trực tiếp | team-coder | 7.1 | ⬜ |
| 7.3 | Dedup exact + gần trùng | team-coder | 7.1 | ⬜ |
| 7.4 | Split 4500/250/250 chống rò rỉ | team-coder | 7.3 | ⬜ |
| 7.5 | Export .json + .jsonl messages | team-coder | 7.4 | ⬜ |
| 7.6 | Kiểm 100% output tạo đề | team-reviewer | 7.5 | ⬜ |

## GĐ8 — Pilot & phát hành §9, §10
| ID | Task | Owner | Dep | Status |
|---|---|---|---|---|
| 8.1 | Pilot 12 tài liệu | manager | GĐ6 hoặc GĐ7 | ⬜ |
| 8.2 | Chốt cấu hình sau pilot | manager | 8.1 | ⬜ |
| 8.3 | Checklist phát hành §10 | team-reviewer | 8.2 | ⬜ |
| 8.4 | Release manifest + changelog + replay guide | team-coder | 8.3 | ⬜ |
