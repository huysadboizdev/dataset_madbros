import json
import sys

sys.path.insert(0, r"D:\OCR_Local\pdf-cleaner-tool")
from paddleocr import PaddleOCRVL
p = PaddleOCRVL(device="cpu", use_doc_orientation_classify=False,
                use_doc_unwarping=False, use_chart_recognition=False,
                use_seal_recognition=False, use_ocr_for_image_block=False)
cfg = p._merged_paddlex_config
print(json.dumps(cfg, ensure_ascii=False, indent=1, default=str))
