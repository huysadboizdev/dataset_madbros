from __future__ import annotations

"""CLI sinh PDF fixture co dau cho Playwright va thu cong cu khac.

Vi du: python backend/app/tests/fixtures/make_pdf_gen_cli.py path/to/out.pdf [so_trang]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.app.tests.fixtures.make_pdf import make_simple_pdf  # noqa: E402

if __name__ == "__main__":
    out = sys.argv[1]
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 140
    make_simple_pdf(Path(out), page_count=pages, text_pages={1, 20}, formula_pages={138})
    print(f"da sinh {out} ({pages} trang)")
