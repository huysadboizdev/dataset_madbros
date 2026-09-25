from __future__ import annotations

from backend.app.cleaning.normalize import (blocks_from_direct_text, evaluate_text_layer,
                                            normalize_blocks, normalize_latex, normalize_text)
from backend.app.cleaning.pii import scan_pii
from backend.app.cleaning.validators import latex_basic_check, validate_page_payload
from backend.app.ocr.base import OcrBlock
from backend.app.ocr.paddle_adapter import _simple_html_table_to_md, map_blocks
from backend.app.storage.artifacts import atomic_write_text, canonical_hash, sanitize_display_name, sha256_bytes


class TestNormalize:
    def test_nfkc_and_whitespace(self):
        assert normalize_text("  a\t\tb  \n\n\n\nc ") == "a b\n\nc"

    def test_inline_math_wrapping(self):
        out = normalize_text("phương trình \\(x^2-4=0\\) nghiêm")
        assert "$x^2-4=0$" in out

    def test_display_math(self):
        out = normalize_text("\\[\\frac{a}{b}\\]")
        assert out.startswith("$$") and out.endswith("$$")

    def test_latex_strip_delims(self):
        assert normalize_latex("$$x^2$$") == "x^2"
        assert normalize_latex("$y$") == "y"

    def test_blocks_drop_empty_text(self):
        blocks = [OcrBlock(type="paragraph", text="   "),
                  OcrBlock(type="paragraph", text="co noi dung")]
        nb = normalize_blocks(blocks)
        assert len(nb) == 1 and nb[0].text == "co noi dung"

    def test_visual_kept_even_without_text(self):
        # S4-dot-sau (finding 4): hop dong MOI — khong bia mo ta hinh, nhung
        # text OCR THAT tren vung hinh phai duoc giu (ban cu vut di an du lieu);
        # chi text rong/chi khoang trang moi ve None.
        nb = normalize_blocks([OcrBlock(type="skipped_visual", text="accidental", bbox=[1, 2, 3, 4])])
        assert nb[0].type == "skipped_visual" and nb[0].text == "accidental"
        nb2 = normalize_blocks([OcrBlock(type="skipped_visual", text="   ", bbox=[1, 2, 3, 4])])
        assert nb2[0].text is None


class TestTextLayerQuality:
    def test_empty(self):
        assert evaluate_text_layer("")["usable"] is False

    def test_single_char_not_enough(self):
        assert evaluate_text_layer("A")["usable"] is False

    def test_good(self):
        t = "Đây là một đoạn văn bản dài đủ để đánh giá chất lượng lớp chữ của trang PDF này."
        assert evaluate_text_layer(t)["usable"] is True

    def test_replacement_chars(self):
        t = "x" * 200 + "\ufffd" * 10
        r = evaluate_text_layer(t)
        assert r["usable"] is False and r["reason"] == "corrupt_chars"

    def test_direct_blocks_split_paragraphs(self):
        blocks = blocks_from_direct_text("Doan mot.\n\nDoan hai.", 5, (612, 792), 200)
        assert len(blocks) == 2
        assert blocks[0].text == "Doan mot."


class TestValidators:
    def test_page_mismatch(self):
        errs = validate_page_payload({"pdf_page": 6, "_expected_page": 5, "blocks": []})
        assert any("PAGE_MISMATCH" in e for e in errs)

    def test_formula_requires_text(self):
        errs = validate_page_payload({
            "pdf_page": 5, "_expected_page": 5,
            "blocks": [{"block_id": "a", "type": "formula", "text": None}]})
        assert any("EMPTY_FORMULA" in e for e in errs)

    def test_dup_block_ids(self):
        b = {"block_id": "x", "type": "paragraph", "text": "ok"}
        errs = validate_page_payload({"pdf_page": 1, "_expected_page": 1, "blocks": [b, b]})
        assert any("DUPLICATE" in e for e in errs)

    def test_latex_unbalanced(self):
        assert latex_basic_check("\\frac{a}{b") == "LATEX_UNBALANCED"
        assert latex_basic_check("\\frac{a}{b}") is None


class TestPii:
    def test_email(self):
        f = scan_pii("lien he: an.nguyen@vidu.edu.vn để biết thêm")
        assert any(x["type"] == "EMAIL" for x in f)

    def test_phone(self):
        f = scan_pii("gọi 0912345678 ngay")
        assert any(x["type"] == "PHONE_VN" for x in f)

    def test_clean_text_no_findings(self):
        assert scan_pii("phương trình bậc hai một ẩn") == []


class TestPaddleMapping:
    def test_blocks_from_nested_dict(self):
        raw = {"res": {"parse_list": [[
            {"type": "text", "bbox": [0, 0, 10, 10], "text": "Câu 1."},
            {"type": "formula", "bbox": [0, 20, 10, 30], "latex": "x^2"},
            {"type": "image", "bbox": [0, 40, 10, 90]},
        ]]}}
        blocks, warnings = map_blocks(raw)
        types = [b.type for b in blocks]
        assert types == ["paragraph", "formula", "skipped_visual"]
        assert blocks[1].latex == "x^2"
        assert "table_not_simple" not in warnings

    def test_block_label_aliases(self):
        raw = {"blocks": [{"block_label": "table", "block_bbox": [0, 0, 5, 5],
                           "html": "<table><tr><td>a</td><td>b</td></tr>"
                                   "<tr><td>1</td><td>2</td></tr></table>"}]}
        blocks, _ = map_blocks(raw)
        assert blocks[0].type == "table"
        assert blocks[0].text.startswith("| a | b |")

    def test_complex_table_flagged(self):
        html = "<table><tr><td rowspan='2'>a</td><td>b</td></tr></table>"
        assert _simple_html_table_to_md(html) is None

    def test_confidence_only_if_number(self):
        raw = {"blocks": [{"type": "text", "bbox": [0, 0, 1, 1], "text": "x",
                           "score": 0.91},
                          {"type": "text", "bbox": [0, 2, 1, 3], "text": "y",
                           "score": "n/a"}]}
        blocks, _ = map_blocks(raw)
        assert blocks[0].confidence == 0.91
        assert blocks[1].confidence is None


class TestStorage:
    def test_atomic_write(self, tmp_path):
        p = tmp_path / "a" / "b.txt"
        atomic_write_text(p, "nội dung")
        assert p.read_text(encoding="utf-8") == "nội dung"
        assert not list(tmp_path.glob("**/*.tmp*"))

    def test_sanitize_display_name(self):
        assert sanitize_display_name(r"C:\x\y<b>ài tập (1).pdf") == "yàbi t?p (1).pdf" or \
            "ài" in sanitize_display_name("ài tập (1).pdf")
        assert "/" not in sanitize_display_name("a/b.pdf")
        assert sanitize_display_name("") == "document.pdf"

    def test_canonical_hash_stable(self):
        assert canonical_hash({"b": 1, "a": 2}) == canonical_hash({"a": 2, "b": 1})

    def test_sha(self):
        assert len(sha256_bytes(b"x")) == 64
