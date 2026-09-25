from __future__ import annotations

import re
from typing import Dict, List

PATTERNS: Dict[str, re.Pattern] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE_VN": re.compile(r"(?<!\d)(?:\+?84|0)(?:3|5|7|8|9)\d{8}(?!\d)"),
    "NATIONAL_ID": re.compile(r"(?<!\d)\d{3}\s?\d{3}\s?\d{4}(?!\d)"),
    "BANK_CARD": re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
    "DATE_OF_BIRTH": re.compile(r"(?i)(?:ngày sinh|nsinh|ns|dob)\s*[:\-]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"),
    "HOME_ADDRESS": re.compile(r"(?i)(?:số\s+nà|số\s+nhà|đ/c|dia?ch? chỉ)\s*[:\-]?\s*[^\n]{6,60},\s*[^\n]{3,40}"),
}


def scan_pii(text: str) -> List[Dict[str, str]]:
    """Quét PII cơ bản trên text đầu ra. KHÔNG tương đương chứng nhận sạch PII."""
    findings: List[Dict[str, str]] = []
    if not text:
        return findings
    for label, pat in PATTERNS.items():
        for m in pat.finditer(text):
            snippet = m.group(0)
            findings.append({
                "type": label,
                "suggestion": f"[{label}]",
                "sample_len": str(len(snippet)),
            })
    return findings
