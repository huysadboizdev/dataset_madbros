from __future__ import annotations

"""Negative tests cho S2: nhung bien doi sai PHAI bi phat hien.
Khong can engine OCR — kiem thuat toan doi chieu. Ne'u thuat toan 'xoa toan tu'
(cu) thi cac test nay THAT BAI; phien ban math_verify GIU toan tu nen chan duoc."""

from backend.app.cleaning.math_verify import normalize_math, verify_all, verify_expression


class TestNormalizationOnlyDefinedEquivalents:
    def test_dfrac_equals_frac(self):
        assert normalize_math(r"\dfrac{1}{2}") == normalize_math(r"\frac{1}{2}")

    def test_ge_variants_equal(self):
        assert normalize_math(r"x \geq 5") == normalize_math(r"x \ge 5") == normalize_math("x ≥ 5")

    def test_operators_are_NOT_stripped(self):
        # toan tu co nghia phai con sau chuan hoa (khong thanh chuoi rong nhu _norm cu)
        for op in ["=", "<", ">", "≥", "≤", "+", "-", "×", "÷"]:
            assert op in normalize_math(f"a {op} b"), op

    def test_superscript_brace_flattened_keeps_operator(self):
        assert normalize_math(r"a^{2}") == "a^2"


class TestPositiveBasics:
    def test_exact_display_passes(self):
        r = verify_expression(r"\frac{3x-1}{2} < x + 4",
                              r"$$ \frac{3x-1}{2}<x+4 $$")
        assert r["ok"], r

    def test_empty_expected_never_auto_passes(self):
        r = verify_expression("", "bat ky gi")
        assert not r["ok"] and r["reason"] == "EMPTY_EXPECTED"

    def test_empty_captured_fails(self):
        assert not verify_expression(r"x=1", "")["ok"]


class TestRequiredNegatives:
    """Moi ca duoi day LA mot 'phai bi phat hien' theo yeu cau."""

    def test_flip_lt_to_gt_detected(self):
        r = verify_expression(r"\frac{3x-1}{2} < x + 4",
                              r"\frac{3x-1}{2} > x + 4")
        assert not r["ok"] and any("op:<" in m for m in r["missing"]), r

    def test_flip_plus_to_minus_detected(self):
        r = verify_expression(r"a + b = c", r"a - b = c")
        assert not r["ok"] and any("op:+" in m for m in r["missing"]), r

    def test_missing_denominator_detected(self):
        r = verify_expression(r"\frac{3x-1}{2}", r"\frac{3x-1}")
        assert not r["ok"] and any("num:2" in m for m in r["missing"]), r

    def test_missing_exponent_detected(self):
        r = verify_expression(r"\sqrt{a^{2}+b^{2}}", r"\sqrt{a+b}")
        # mat so mu ^ va cac so 2 -> that bai
        assert not r["ok"], r
        assert any("struct:exp" in m or "num:2" in m for m in r["missing"]), r

    def test_missing_equals_detected(self):
        r = verify_expression(r"\sqrt{5} = c", r"\sqrt{5} c")
        assert not r["ok"] and any("op:=" in m for m in r["missing"]), r

    def test_ge_becomes_gt_detected(self):
        r = verify_expression(r"\frac{2x-1}{x+3} \geq 5",
                              r"\frac{2x-1}{x+3} > 5")
        assert not r["ok"] and any("op:≥" in m for m in r["missing"]), r


class TestFullCoverageDisplayAndInline:
    def test_display_ok_but_inline_missing_fails(self):
        res = verify_all(
            expected_display=[r"\sqrt{a^{2}+b^{2}}=\sqrt{5}"],
            expected_inline=[r"a^{2}+b^{2}=c^{2}"],
            display_captured=r"$$ \sqrt{a^{2}+b^{2}}=\sqrt{5} $$",
            inline_captured="Nếu thì tam giác vuông tại C",  # inline math mat hoan toan
        )
        assert not res["ok"]
        assert any(rr["kind"] == "inline" and not rr["ok"] for rr in res["results"])

    def test_both_present_passes(self):
        res = verify_all(
            expected_display=[r"\sqrt{a^{2}+b^{2}}=\sqrt{5}"],
            expected_inline=[r"a^{2}+b^{2}=c^{2}"],
            display_captured=r"$$ \sqrt{a^{2}+b^{2}}=\sqrt{5} $$",
            inline_captured=r"Nếu $ a^{2} + b^{2} = c^{2} $ thì vuông.",
        )
        assert res["ok"], res["failed"]
