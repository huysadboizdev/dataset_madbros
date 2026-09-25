import sys
from pathlib import Path
sys.path.insert(0, r"D:\OCR_Local\pdf-cleaner-tool")
from backend.app.tests.fixtures.make_pdf import make_simple_pdf
from backend.app.services import pdf_service as ps
from backend.app.cleaning.normalize import evaluate_text_layer

p = Path(r"D:\OCR_Local\pdf-cleaner-tool\docs\_probe3.pdf")
make_simple_pdf(p, page_count=4, text_pages={2, 3, 4}, image_pages={3}, small_image_pages={4})
with ps.PdfDoc(p) as d:
    for i in (2, 3, 4):
        prof = d.page_content_profile(i)
        q = d.extract_page_text(i)
        usable, flags, reasons = ps.decide_direct_or_ocr(evaluate_text_layer(q), prof)
        print(f"p{i}: usable={evaluate_text_layer(q)['usable']} imgs={prof['image_objects']} "
              f"maxfrac={prof['max_image_page_frac']} -> direct={usable} flags={flags} reasons={reasons}")
p.unlink(missing_ok=True)
