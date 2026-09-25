from __future__ import annotations

"""Doi chieu cong thuc that — khong dung 'xoa toan tu roi substring'.

Dung chung cho `scripts/verify_formula_ocr.py` va don vi test (negative tests).
Triet ly:
- GIU NGUYEN toan tu co nghia (= < > ≤ ≥ ≠ + − × ÷, so mu ^, can √, phan so \\frac).
- Chi chuan hoa CACH VIET tuong duong DA DINH NGHIA ro (\\dfrac/\\tfrac -> \\frac,
  \\geq/\\geqslant/≥ -> ≥, \\left/\\right/spacing bo, ^{k} -> ^k, ...).
- Expected sau chuan hoa khong duoc RONG; rong -> FAIL (khong bao gio 'tu khop').
- PASS can: moi TOAN TU cua expected xuat hien du SO LUONG trong captured, moi
  so/bin so duoc giu, va CAU TRUC (phan so/can/so mu) co mat — substring roi rac
  rieng no KHONG du la bang chung.
"""

import re
import unicodedata
from collections import Counter
from typing import Dict, List, Tuple

# Quy doi cach VIET LaTeX tuong duong -> ky hieu chuan (co y nghia, KHONG xoa).
# KHONG dung \b cuoi: toan tu cua OCR that nhu '\geq5' (lenh dinh ngay chu so) se
# bi \b chan; thay bang thay the dai-nhat (longest-first) khong doi hoi bien.
_EQUIV: List[Tuple[str, str]] = [
    (r"\\d?t?frac", r"\\frac"),
    (r"\\ge(?:qslant|q)?", "≥"),
    (r"\\le(?:qslant|q)?", "≤"),
    (r"\\neq?", "≠"),
    (r"\\approx", "≈"),
    (r"\\pm", "±"),
    (r"\\times", "×"),
    (r"\\cdot", "×"),
    (r"\\div", "÷"),
    (r"\\infty", "∞"),
    (r"\\sqrt", "√"),
    (r"\\sum", "∑"),
    (r"\\int", "∫"),
    (r"\\pi(?![A-Za-z])", "π"),
]
# Bo danh cho ky hieu khong mang y nghia so sanh
_NOISE = [r"\\left", r"\\right", r"\\,", r"\\;", r"\\:", r"\\!", r"\\ ", r"\\quad", r"\\qquad"]
_SUPS = {"\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2074": "4", "\u2075": "5",
         "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9", "\u2070": "0",
         "\u207a": "+", "\u207b": "-"}

OPERATORS = set("=<>≤≥≠+−×÷≈±∫∑√")  # ky hiu toan tu duoc GIU


def normalize_math(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    for pat in _NOISE:
        t = re.sub(pat, "", t)
    for pat, rep in _EQUIV:
        t = re.sub(pat, rep, t)
    # ki tu hoa (superscript unicode) ve dang ^k khi co the
    t = "".join(_SUPS.get(ch, ch) for ch in t)
    # ^{k} / _{k} -> ^k _k (don gian hoa cau truc, giu nham)
    t = re.sub(r"([_^])\{([^{}]+)\}", r"\1\2", t)
    t = t.replace(" ", "")
    return t


def units(norm: str) -> Dict[str, Counter]:
    """Phan tich bieu thuc da chuan hoa thanh cac bo dem co nghia."""
    ops = Counter(c for c in norm if c in OPERATORS)
    # so: gom chuoi ki tu
    nums = Counter(re.findall(r"\d+", norm))
    # bien/ky tu chu (khong phai trong lenh, vi lenh da quy doi het)
    letters = Counter(re.findall(r"[A-Za-z]", norm))
    struct = Counter()
    if "\\frac" in norm:
        struct["frac"] += norm.count("\\frac")
    if "√" in norm:
        struct["sqrt"] += norm.count("√")
    for ch in "^_":
        if ch in norm:
            struct["exp" if ch == "^" else "sub"] += norm.count(ch)
    return {"ops": ops, "nums": nums, "letters": letters, "struct": struct}


def verify_expression(expected: str, captured: str) -> Dict[str, object]:
    """Doi chieu MOT bieu thuc. captured = chuoi da gop (display + inline, da normalize).

    Return dict(ok, reason, missing). Khong dung substring roi rac lam bang chung duy
    nhat: bat buoc du so toan tu + co cau truc + giu so.
    """
    exp_norm = normalize_math(re.sub(r"^\$+|\$+$", "", expected.strip()))
    if not exp_norm:
        return {"ok": False, "reason": "EMPTY_EXPECTED", "missing": ["<expected rỗng>"]}
    cap_norm = normalize_math(captured)
    e = units(exp_norm)
    c = units(cap_norm)

    missing: List[str] = []
    # moi toan tu phai du so luong (khong the < thay =, + thay -)
    for op, n in e["ops"].items():
        if c["ops"][op] < n:
            missing.append(f"op:{op}")
    # cau truc bat buoc (phan so/can/so mu) phai co
    for kind, n in e["struct"].items():
        if c["struct"][kind] < n:
            missing.append(f"struct:{kind}")
    # moi so cua expected phai con
    for num, n in e["nums"].items():
        if c["nums"][num] < n:
            missing.append(f"num:{num}")

    ok = len(missing) == 0 and cap_norm  # captured rong -> that bai tuyet doi
    reason = "OK" if ok else ("MISSING:" + ",".join(sorted(missing)))
    return {"ok": ok, "reason": reason, "missing": sorted(missing),
            "expected_norm": exp_norm, "captured_norm": cap_norm[:300]}


def verify_all(expected_display: List[str], expected_inline: List[str],
               display_captured: str, inline_captured: str) -> Dict[str, object]:
    """KIEM DAY DU ca display va inline. Thieu BAT KY bieu thuc bat buoc nao -> FAIL."""
    results = []
    for ex in expected_display:
        r = verify_expression(ex, display_captured)
        results.append({"kind": "display", "expected": ex, **r})
    for ex in expected_inline:
        r = verify_expression(ex, inline_captured)
        results.append({"kind": "inline", "expected": ex, **r})
    # mot bieu thuc khong bat buoc (vi du inline co the nam trong display cua cung
    # mot trang) -> cung cho phep khop o nguoi kia tru khi bi coi la thiet yeu
    all_ok = all(r["ok"] for r in results)
    return {"ok": all_ok, "results": results,
            "failed": [r for r in results if not r["ok"]]}
