from __future__ import annotations

import pytest

from backend.app.services.page_selection import (SelectionError, parse_from_to,
                                                 parse_page_expression)

PC = 138


def ok(expr, page_count=PC, **kw):
    return parse_page_expression(expr, page_count, **kw)


class TestValidSelections:
    def test_single_range(self):
        assert ok("5-10") == [5, 6, 7, 8, 9, 10]

    def test_mixed_list_dedupe_sorted(self):  # P02
        assert ok("1,5-7,7,138") == [1, 5, 6, 7, 138]

    def test_spaces_normalized(self):
        assert ok(" 5 - 7 , 7 , 10 ") == [5, 6, 7, 10]

    def test_vn_word_den(self):
        assert ok("5 đến 7, 10") == [5, 6, 7, 10]

    def test_en_dash(self):
        assert ok("5–7") == [5, 6, 7]

    def test_first_page(self):
        assert ok("1") == [1]

    def test_last_page(self):
        assert ok(str(PC)) == [PC]

    def test_all_active(self):
        assert ok("*", allow_all=True) == list(range(1, PC + 1))

    def test_all_requires_active(self):
        with pytest.raises(SelectionError) as e:
            ok("*", allow_all=False)
        assert e.value.code == "ALL_NOT_ALLOWED"

    def test_duplicates_single(self):
        assert ok("7,7,7") == [7]


class TestInvalidSelections:  # P03
    @pytest.mark.parametrize("expr", ["0", "0-5", "5-0"])
    def test_zero(self, expr):
        with pytest.raises(SelectionError) as e:
            ok(expr)
        assert e.value.code in ("NON_POSITIVE", "REVERSED_RANGE")

    def test_negative(self):
        with pytest.raises(SelectionError) as e:
            ok("-5")
        assert e.value.code in ("NON_POSITIVE", "BAD_RANGE", "NOT_INT")

    def test_reversed_range(self):
        with pytest.raises(SelectionError) as e:
            ok("10-5")
        assert e.value.code == "REVERSED_RANGE"

    def test_decimal(self):
        with pytest.raises(SelectionError) as e:
            ok("5.5")
        assert e.value.code == "NOT_INT"

    def test_letters(self):
        with pytest.raises(SelectionError) as e:
            ok("abc")
        assert e.value.code == "NOT_INT"

    def test_empty_item(self):
        with pytest.raises(SelectionError) as e:
            ok("5,,7")
        assert e.value.code == "EMPTY_ITEM"

    def test_out_of_range_not_clamped(self):
        with pytest.raises(SelectionError) as e:
            ok("139")
        assert e.value.code == "OUT_OF_RANGE"
        assert "139" in e.value.message

    def test_empty_expression(self):  # P04
        with pytest.raises(SelectionError) as e:
            ok("")
        assert e.value.code == "MISSING"

    def test_none_expression(self):
        with pytest.raises(SelectionError) as e:
            parse_page_expression(None, PC)
        assert e.value.code == "MISSING"


class TestFromTo:
    def test_inclusive(self):
        assert parse_from_to(5, 7, PC) == [5, 6, 7]

    def test_equal(self):
        assert parse_from_to(5, 5, PC) == [5]

    def test_reversed(self):
        with pytest.raises(SelectionError) as e:
            parse_from_to(10, 5, PC)
        assert e.value.code == "REVERSED_RANGE"

    def test_missing_side(self):
        with pytest.raises(SelectionError):
            parse_from_to(None, 5, PC)

    def test_out_of_range(self):
        with pytest.raises(SelectionError) as e:
            parse_from_to(1, 139, PC)
        assert e.value.code == "OUT_OF_RANGE"

    def test_bool_rejected(self):
        with pytest.raises(SelectionError):
            parse_from_to(True, 5, PC)


class TestFingerprint:
    def test_stable(self):
        from backend.app.services.page_selection import pages_fingerprint
        assert pages_fingerprint([1, 5, 6, 7, 138]) == "1,5,6,7,138"
