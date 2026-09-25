from __future__ import annotations

"""S3: sanitize metadata dau ra theo CAU TRUC (dict/list long nhau), khong chi lop bac.
Kem chan false-positive: checksum hex va so lieu toan hoc KHONG bi doi thanh [PHONE]."""

from backend.app.cleaning.export_sanitize import has_private_leak, sanitize_public

SHA = "a" * 64


def test_strips_nested_paths_and_keeps_hashes():
    meta = {
        "dir": "C:\\Users\\huy\\.paddlex\\official_models\\PaddleOCR-VL-1.6",
        "engine": "paddleocr_vl",
        "model_fp": {
            "PaddleOCR-VL-1.6": {
                "config_sha256": {"config.json": SHA},
                "weights": {"model.safetensors": {"size": 1917255968, "sha256": SHA}},
            }
        },
        "user": {"notes": "lam tai /home/an/work/pdf", "subject": "Toán"},
    }
    out = sanitize_public(meta)
    blob = str(out)
    assert "Users" not in blob and "/home/" not in blob
    # key bi cam (dir/*path) loai bo, nhung hash ben trong gia tri dict van giu
    assert "dir" not in out
    assert out["engine"] == "paddleocr_vl"
    assert out["model_fp"]["PaddleOCR-VL-1.6"]["config_sha256"]["config.json"] == SHA
    assert out["user"]["subject"] == "Toán"
    # duong dan trong CHUOI gia tri -> PATH_REDACTED
    assert out["user"]["notes"] == "[PATH_REDACTED]"
    assert has_private_leak(out) == []


def test_email_phone_redacted_but_not_math_or_checksum():
    meta = {
        "contact": "a@x.com",
        "hotline": "gọi 0912345678 để nhận file",   # phone trong van ban -> redact
        "checksum": SHA,                 # hex dai -> GIU (khong phai dien thoai)
        "figure": "1234567890",          # so toan hoc thuan -> GIU, khong chan nham phone
        "grade": "10",
        "ratio": 0.85,
        "count": 42,
    }
    out = sanitize_public(meta)
    assert out["contact"].startswith("[EMAIL")
    assert "[PHONE_VN_REDACTED]" in out["hotline"]
    assert "0912345678" not in out["hotline"]
    assert out["checksum"] == SHA
    assert out["figure"] == "1234567890"   # khong bi chan nham la dien thoai
    assert out["grade"] == "10" and out["ratio"] == 0.85 and out["count"] == 42
    assert has_private_leak(out) == []


def test_windows_drive_letter_and_unc_detected():
    for p in [r"D:\OCR_Local\secret.pdf", r"\\server\share\x", "/var/tmp/y/z"]:
        assert has_private_leak({"v": p}) or sanitize_public({"v": p})["v"] != p, p


def test_empty_and_scalars_passthrough():
    assert sanitize_public({}) == {}
    assert sanitize_public([1, 2, "Toán"]) == [1, 2, "Toán"]
    assert sanitize_public(None) is None


def test_root_named_boolean_key_is_NOT_dropped():
    """Regresion: khoa `model_root_present` (bool) co chua 'root' KHONG bi sanitize xoá.
    Key path that su (dir/path) + gia tri la duong dan -> moi bi loai."""
    meta = {
        "model_root_present": True,
        "model_fp": {"PP-DocLayoutV3": {"config_sha256": {"config.json": SHA},
                                         "weights": {"model.safetensors": {"size": 10, "sha256": SHA}}}},
        "dir": "/home/secret/model",           # key path + gia tri path -> bo
        "some_path": "C:\\Users\\me\\x.pdf",   # gia tri path -> PATH_REDACTED
        "device": "cpu",
    }
    out = sanitize_public(meta)
    assert out.get("model_root_present") is True          # bool van giu du
    assert out["model_fp"]["PP-DocLayoutV3"]["config_sha256"]["config.json"] == SHA
    assert "dir" not in out                              # key path that su bi loai
    assert out["some_path"] == "[PATH_REDACTED]"
    assert out["device"] == "cpu"
    assert has_private_leak(out) == []
