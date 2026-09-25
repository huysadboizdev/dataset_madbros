from __future__ import annotations

"""Sinh manifest SHA-256 cac FILE NGUON + CAU HINH anh huong hanh vi, de gan bang
chung nghiem thu voi mot snapshot ma, KHONG can Git (phat hien S8).

Bao gom: backend/, frontend/src/, scripts/, setup.cmd, Open_Tool.cmd, Stop_Tool.cmd,
requirements.lock.txt, frontend/package.json + package-lock.json, vite/tsconfig/playwright
config, index.html, config.example.json (ma hoa sanitized).

KHONG bao gom: config.json runtime (duong dan may nguoi dung), data/, *.env, key/secret,
node_modules, dist, cache. Khong tu hash chinh manifest nay (khong co vong quy).

  python scripts/hash_source.py --out docs/SOURCE_SNAPSHOT.sha256
"""

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("backend/app", "frontend/src", "scripts")
EXCLUDE_PARTS = {"__pycache__", "node_modules", ".venv", "dist", ".pytest_cache",
                 "test-results", "test_results"}
SUFFIXES = {".py", ".ts", ".tsx", ".css", ".html"}

# Cac file dinh + cau hinh anh huong hanh vi (KHONG gom config.json runtime)
EXPLICIT_FILES = (
    "setup.cmd", "Open_Tool.cmd", "Stop_Tool.cmd",
    "requirements.lock.txt", "config.example.json", "pyproject.toml", "README.md",
    "frontend/package.json", "frontend/package-lock.json",
    "frontend/vite.config.ts", "frontend/tsconfig.json", "frontend/tsconfig.app.json",
    "frontend/tsconfig.node.json", "frontend/playwright.config.ts", "frontend/index.html",
    "backend/app/tests/fixtures/formula_blocks.json",
    "backend/app/tests/fixtures/make_pdf.py", "backend/app/tests/fixtures/make_pdf_gen_cli.py",
    "frontend/tests/flow.spec.ts", "frontend/tests/formula.spec.ts",
    "frontend/tests/fixtures/formula_blocks.json",
)


def _iter_sources():
    seen = set()
    for d in SOURCE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in SUFFIXES:
                continue
            if EXCLUDE_PARTS & set(p.parts):
                continue
            yield p
            seen.add(p)
    for rel in EXPLICIT_FILES:
        p = ROOT / rel
        if p.is_file() and p not in seen:
            yield p


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "SOURCE_SNAPSHOT.sha256"))
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(set(_iter_sources()), key=lambda p: str(p.relative_to(ROOT)))
    lines = ["# Snapshot FILE NGUON + cau hinh hanh vi — PDF Cleaner Tool (khong can Git)",
             f"# {len(files)} file · sinh boi scripts/hash_source.py",
             "# LOAI: config.json runtime, data/, node_modules, dist, cache, secret/key.",
             "# Khong tu hash chinh file nay (khong co vong quy)."]
    combined = hashlib.sha256()
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        digest = _sha(p)
        lines.append(f"{digest}  {rel}")
        combined.update(rel.encode("utf-8")); combined.update(digest.encode("utf-8"))
    lines.append("")
    lines.append(f"AGGREGATE sha256 (thứ tự ổn định) = {combined.hexdigest()}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"da ghi {len(files)} file -> {out}")
    print("AGGREGATE:", combined.hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
