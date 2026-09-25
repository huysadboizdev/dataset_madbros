import sys
from pathlib import Path
sys.path.insert(0, r"D:\OCR_Local\pdf-cleaner-tool")
import pypdfium2
from backend.app.tests.fixtures.make_pdf import make_simple_pdf

tmp = Path(r"D:\OCR_Local\pdf-cleaner-tool\docs\_probe2.pdf")
make_simple_pdf(tmp, page_count=2, text_pages={1})
doc = pypdfium2.PdfDocument(tmp)
page = doc[0]
for o in page.get_objects():
    print("class:", type(o).__name__, "attrs:",
          [a for a in dir(o) if not a.startswith("_") and ("get" in a or "raw" in a)][:12])
    try:
        print("  bbox:", o.get_pos(), o.get_size())
    except Exception as e:
        print("  pos err:", e)
doc.close()
