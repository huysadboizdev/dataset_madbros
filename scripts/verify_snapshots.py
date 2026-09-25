# -*- coding: utf-8 -*-
"""KIEM TRA DOC LAP hai manifest (khong import hash_evidence/hash_source):
- doc tung dong 'sha256  path', hash lai file bang hashlib, so khop;
- kiem tra AGGREGATE trong file ghi trong ACCEPTANCE_REPORT.md (SOURCE);
- kiem tra EVIDENCE tham chieu SOURCE (mot chieu) va khong tu hash chinh no.
Thoat 0 neu TAT CA khop; thoat 1 neu lech bat ky."""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def aggregate(manifest: Path) -> tuple[str, int]:
    comb = hashlib.sha256()
    n = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith("AGGREGATE"):
            continue
        if "  " not in line:
            continue  # dong khong phai entry (header/ghi chu)
        digest, rel = line.split("  ", 1)
        if rel.endswith(manifest.name):
            print(f"LOI: {manifest.name} TU HASH CHINH NO: {rel}")
            sys.exit(1)
        got = sha(ROOT / rel)
        if got != digest:
            print(f"LECH: {rel}\n  manifest={digest}\n  that    ={got}")
            sys.exit(1)
        comb.update(rel.encode("utf-8"))
        comb.update(got.encode("utf-8"))
        n += 1  # tham chieu chieu sang snapshot kia VAN duoc hash + cong vao aggregate
        # (giong dung cach hash_evidence/hash_source tinh aggregate)
    return comb.hexdigest(), n


def check(name: str) -> None:
    m = ROOT / "docs" / name
    if not m.exists():
        print(f"THIEU: docs/{name}")
        sys.exit(1)
    agg, n = aggregate(m)
    print(f"{name}: {n} file, moi entry khop byte that; AGGREGATE = {agg}")
    text = m.read_text(encoding="utf-8")
    m2 = re.search(r"AGGREGATE sha256[^0-9a-f]*([0-9a-f]{64})", text)
    if not m2 or m2.group(1) != agg:
        print(f"LECH aggregate ghi trong file vs tinh lai: {m2.group(1) if m2 else None} vs {agg}")
        sys.exit(1)


check("SOURCE_SNAPSHOT.sha256")
check("EVIDENCE_SNAPSHOT.sha256")

# one-way reference: EVIDENCE liet ke SOURCE (hash no), nguoc lai SOURCE khong liet ke EVIDENCE
src = (ROOT / "docs" / "SOURCE_SNAPSHOT.sha256").read_text(encoding="utf-8")
ev = (ROOT / "docs" / "EVIDENCE_SNAPSHOT.sha256").read_text(encoding="utf-8")
assert "SOURCE_SNAPSHOT.sha256" in ev, "EVIDENCE phai tham chieu SOURCE"
assert "EVIDENCE_SNAPSHOT" not in src, "SOURCE KHONG duoc tham chieu EVIDENCE (one-way)"
print("one-way reference: OK (EVIDENCE -> SOURCE)")

# aggregate SOURCE ghi trong bao cao phai trung
report = (ROOT / "docs" / "ACCEPTANCE_REPORT.md").read_text(encoding="utf-8")
m = re.search(r"AGGREGATE = `([0-9a-f]{64})`", report)
_, n_src = None, 0
comb = hashlib.sha256()
for line in (ROOT / "docs" / "SOURCE_SNAPSHOT.sha256").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#") or line.startswith("AGGREGATE") or "  " not in line:
        continue
    d, rel = line.split("  ", 1)
    if rel.endswith("SOURCE_SNAPSHOT.sha256"):
        continue
    comb.update(rel.encode("utf-8")); comb.update(d.encode("utf-8"))
if m and m.group(1) == comb.hexdigest():
    print(f"bao cáo khop SOURCE AGGREGATE: {m.group(1)}")
else:
    print(f"LECH: bao cao {m.group(1) if m else None} vs thuc te {comb.hexdigest()}")
    sys.exit(1)
print("VERIFY HOAN TAT: TAT CA KHOP")