from __future__ import annotations

"""S4 (muc 3 cua dot nay): kiem GIOI HAN cua sample-fingerprint va rang cache dung
FULL SHA-256 nen chan duoc byte ngoai vung sample, cung kich thuoc + cung mtime.

F1 (dot 5): `*.index.json` tham chieu shard/artifact BAT BUOC — thieu/khong doc duoc/
chua duoc hash -> `status='incomplete'` (KHONG duoc tra 'ok')."""

import os
from pathlib import Path
from typing import Optional

from backend.app.ocr import model_identity as mi
from backend.app.ocr.model_identity import _sample_fingerprint, _sha_file
import json


def _fake_root(tmp_path: Path, blob: bytes) -> Path:
    root = tmp_path / "models"
    d = root / "PP-DocLayoutV3"; d.mkdir(parents=True)
    (d / "config.json").write_text('{"v":1}', encoding="utf-8")
    (d / "model.safetensors").write_bytes(blob)
    return root


def test_sample_fingerprint_misses_out_of_window_byte(tmp_path):
    # cua so 1KB tren tep 12KB: head[0:1K], mid~[5.5K:6.5K], tail[11K:12K]
    blob = bytearray(b"\x00" * 12_288)
    p = tmp_path / "w.safetensors"; p.write_bytes(bytes(blob))
    size0 = p.stat().st_size
    mtime0 = p.stat().st_mtime_ns
    fp_before = _sample_fingerprint(p, window=1024)
    sha_before = _sha_file(p)
    # doi byte tai offset 3000 (NGOAII ca 3 vung head/mid/tail), giu kich thuoc
    blob[3000] = 0xFF
    p.write_bytes(bytes(blob))
    os.utime(p, ns=(mtime0, mtime0))  # giu nguyen mtime
    assert p.stat().st_size == size0, "kich thuoc phai khong doi"
    assert p.stat().st_mtime_ns == mtime0, "mtime phai khong doi"
    assert _sample_fingerprint(p, window=1024) == fp_before, "sample KHOONG phat hien (gioi han)"
    assert _sha_file(p) != sha_before, "FULL SHA-256 phai phat hien"


def test_full_fingerprint_catches_out_of_window_and_same_size(tmp_path):
    blob = bytearray(b"\x00" * 12_288)
    root = _fake_root(tmp_path, bytes(blob))
    fp_a = mi.model_fingerprint("PP-DocLayoutV3", root, full=True)
    sha_a = fp_a["weights"]["model.safetensors"]["sha256"]
    # doi byte ngoai vung sample, cung kich thuoc
    blob[3000] = 0xFF
    (root / "PP-DocLayoutV3" / "model.safetensors").write_bytes(bytes(blob))
    fp_b = mi.model_fingerprint("PP-DocLayoutV3", root, full=True)
    sha_b = fp_b["weights"]["model.safetensors"]["sha256"]
    assert sha_a != sha_b, "full SHA-256 phai phat hien noi dung doi du ngoai vung sample"
    assert fp_b["weights"]["model.safetensors"]["size"] == 12_288, "kich thuoc giu nguyen"
    # va identity_hash(full) doi -> cache tag doi -> cache cu bi vo hieu hoa
    assert mi.identity_hash(["PP-DocLayoutV3"], root, full=True) != mi.identity_hash(
        ["PP-DocLayoutV3"], root)  # sample khac full; ca hai deu doi khi noi dung doi


def test_identity_hash_full_is_path_independent(tmp_path):
    blob = b"\x11" * 4096
    r1 = _fake_root(tmp_path / "a", blob)
    r2 = _fake_root(tmp_path / "b", blob)
    assert mi.identity_hash(["PP-DocLayoutV3"], r1, full=True) == \
        mi.identity_hash(["PP-DocLayoutV3"], r2, full=True)


def test_identity_from_fps_equals_identity_hash(tmp_path):
    """Job pin tag tu fingerprint da tinh (identity_from_fps) phai TRUNG voi
    identity_hash doc lap -> tag cache khong doi khi refactor (backward compatible)."""
    blob = b"\x22" * 8192
    root = _fake_root(tmp_path, blob)
    names = ["PP-DocLayoutV3"]
    parts = [mi.model_fingerprint(n, root, full=True) for n in sorted(names)]
    assert mi.identity_from_fps(parts) == mi.identity_hash(names, root, full=True)
    parts_sample = [mi.model_fingerprint(n, root, full=False) for n in sorted(names)]
    assert mi.identity_from_fps(parts_sample) == mi.identity_hash(names, root)


def test_paddle_pdiparams_weights_are_hashed(tmp_path):
    """Loi thuc te phat hien dot nay: PP-DocLayoutV3 dung inference.pdiparams
    (khong phai .pdparams). Ngoai whitelist -> weight 130MB khong bao gio hash
    -> doi layout weights cung config = cache KHONG vo hieu hoa."""
    root = tmp_path / "models"
    d = root / "PP-DocLayoutV3"
    d.mkdir(parents=True)
    (d / "inference.yml").write_text("a: 1\n", encoding="utf-8")
    (d / "inference.pdiparams").write_bytes(b"\x00" * 5000)
    fp = mi.model_fingerprint("PP-DocLayoutV3", root, full=True)
    assert "inference.pdiparams" in fp["weights"], "weight .pdiparams phai duoc hash"
    assert "inference.yml" in fp["config_sha256"]
    tag_before = mi.identity_hash(["PP-DocLayoutV3"], root, full=True)
    (d / "inference.pdiparams").write_bytes(b"\x01" * 5000)  # cung kich thuoc
    tag_after = mi.identity_hash(["PP-DocLayoutV3"], root, full=True)
    assert tag_after != tag_before, "doi noi dung .pdiparams phai doi cache tag"


# ---- Regression S4-dot-sau: inventory inventory THEO QUY TAC (finding 1) ----

def _hf_style_dir(d):
    """Mo phong thu muc model HF-style THAT: du artifact tien xu ly/tokenizer
    (chinh la nhung file bi thieu trong _SMALL_CFG cu)."""
    d.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "generation_config.json", "tokenizer.json",
                 "tokenizer_config.json", "special_tokens_map.json",
                 "preprocessor_config.json", "processor_config.json",
                 "model.safetensors.index.json"):
        (d / name).write_text(f'{{"f": "{name}"}}', encoding="utf-8")
    (d / "tokenizer.model").write_bytes(b"tok-model-bytes")
    (d / "model.safetensors").write_bytes(b"\x00" * 8192)
    sub = d / "sub"; sub.mkdir()
    (sub / "vocab.txt").write_text("abc\ndef\n", encoding="utf-8")
    # file KHONG anh huong inference:
    (d / "README.md").write_text("readme", encoding="utf-8")
    (d / "LICENSE.txt").write_text("lic", encoding="utf-8")
    (d / "optimizer.pt").write_bytes(b"opt-state")
    (d / ".gitignore").write_text("*.tmp", encoding="utf-8")
    runs = d / "runs"; runs.mkdir()
    (runs / "events.out").write_bytes(b"tb")
    return d


def test_preprocessor_config_change_changes_identity(tmp_path):
    """Finding 1: doi preprocessor_config.json (cung kich thuoc) PHAI doi identity
    -> cache stale; ban cu chi hash 5 ten hardcode nen khong bat duoc."""
    root = tmp_path / "models"
    d = _hf_style_dir(root / "PaddleOCR-VL-1.6")
    tag_a = mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=True)
    # doi noi dung preprocessor_config.json, GIU NGUYEN kich thuoc
    p = d / "preprocessor_config.json"
    old = p.read_text(encoding="utf-8")
    p.write_text(old.replace("f", "F"), encoding="utf-8")
    assert p.stat().st_size == d.joinpath("preprocessor_config.json").stat().st_size
    tag_b = mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=True)
    assert tag_a != tag_b, "doi preprocessor_config.json phai lam cache stale"
    # va ca fast mode (config luon duoc hash FULL) cung phai bat duoc
    assert mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=False) != tag_a


def test_inventory_includes_all_inference_artifacts_and_excludes_noise(tmp_path):
    """Inventory phai theo QUY TAC: moi file inference deu duoc hash (kể cả nested),
    loai ro rang README/LICENSE/optimizer/.git/runs."""
    root = tmp_path / "models"
    d = _hf_style_dir(root / "PaddleOCR-VL-1.6")
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    files = set(fp["files"])
    for rel in ("config.json", "tokenizer.json", "tokenizer_config.json",
                "special_tokens_map.json", "preprocessor_config.json",
                "processor_config.json", "model.safetensors.index.json",
                "tokenizer.model", "model.safetensors", "sub/vocab.txt",
                "generation_config.json"):
        assert rel in files, f"thieu artifact inference: {rel}"
    for noise in ("README.md", "LICENSE.txt", "optimizer.pt", ".gitignore", "runs/events.out"):
        assert noise not in files, f"file khong-inference khong duoc vao inventory: {noise}"
    assert fp["status"] == "ok"
    assert "model.safetensors" in fp["weights"] and "sub/vocab.txt" not in fp["weights"]


def test_model_without_weights_is_incomplete_not_ok(tmp_path):
    """Model dir khong co weight -> status='incomplete' (ban cu tra 'ok' voi
    identity chi-goi-config -> co the dung cache vo giuoc)."""
    root = tmp_path / "models"
    d = root / "PP-DocLayoutV3"; d.mkdir(parents=True)
    (d / "config.json").write_text("{}", encoding="utf-8")
    fp = mi.model_fingerprint("PP-DocLayoutV3", root, full=True)
    assert fp["status"] == "incomplete", "thieu weight phai khong-duoc-xac-minh"


def test_rename_remove_add_artifact_changes_identity(tmp_path):
    root = tmp_path / "models"
    d = _hf_style_dir(root / "PaddleOCR-VL-1.6")
    tag0 = mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=True)
    # them artifact moi (vi du file shard thu hai)
    (d / "model-00002.safetensors").write_bytes(b"\x01" * 4096)
    tag1 = mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=True)
    assert tag1 != tag0, "them artifact phai doi identity"
    # doi ten (rename) artifact nho
    (d / "sub" / "vocab.txt").rename(d / "sub" / "vocab_new.txt")
    tag2 = mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=True)
    assert tag2 != tag1, "rename artifact phai doi identity (key = duong dan tuong doi)"
    # xoa artifact
    (d / "processor_config.json").unlink()
    tag3 = mi.identity_hash(["PaddleOCR-VL-1.6"], root, full=True)
    assert tag3 != tag2, "xoa artifact phai doi identity"


def _sharded_dir(root: Path, *, shards: int = 2, declared: int = 2):
    """Model HF-style co `*.safetensors.index.json` tham chieu cac shard.

    `shards` = so shard TAO THAT tren dia; `declared` = so shard INDEX tham chieu.
    """
    d = root / "PaddleOCR-VL-1.6"
    d.mkdir(parents=True)
    (d / "config.json").write_text('{"m": "vl"}', encoding="utf-8")
    weight_map = {}
    for i in range(1, declared + 1):
        name = f"model-{i:05d}-of-{declared:05d}.safetensors"
        weight_map[f"layer{i}"] = name
        if i <= shards:
            (d / name).write_bytes(bytes([i]) * 2048)
    (d / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": 2048 * declared},
                    "weight_map": weight_map}), encoding="utf-8")
    return d


def test_all_referenced_shards_present_is_ok(tmp_path):
    """F1: index day du + moi shard co mat va duoc hash -> status='ok'."""
    root = tmp_path / "models"
    _sharded_dir(root, shards=2, declared=2)
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    assert fp["status"] == "ok"
    ref = fp["referenced"]
    assert ref["indexes"] == ["model.safetensors.index.json"]
    assert ref["missing"] == [] and ref["not_hashed"] == [] and ref["unreadable"] == []
    assert "model-00001-of-00002.safetensors" in fp["weights"]
    assert "model-00002-of-00002.safetensors" in fp["weights"]


def test_missing_referenced_shard_is_incomplete_not_ok(tmp_path):
    """COUNTEREXAMPLE cua kiem toan F1 (ban cu tra 'F1_MISSING_REFERENCED_SHARD_STATUS=ok')."""
    root = tmp_path / "models"
    _sharded_dir(root, shards=1, declared=2)     # chi tao shard 1/2
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    assert fp["status"] == "incomplete", "thieu shard duoc index tham chieu -> KHONG 'ok'"
    missing = fp["referenced"]["missing"]
    assert len(missing) == 1
    assert missing[0].endswith("model-00002-of-00002.safetensors")
    assert set(fp["files"]) == {"config.json", "model.safetensors.index.json",
                                "model-00001-of-00002.safetensors"}


def test_referenced_file_not_in_inventory_is_incomplete(tmp_path):
    """File duoc index tham chieu nhung KHONG duoc hash (bi loai khoi inventory) van
    la loi: 'da hash' moi duoc coi la xac minh (F1)."""
    root = tmp_path / "models"
    d = _sharded_dir(root, shards=1, declared=1)
    (d / "README.md").write_text("doc\n", encoding="utf-8")
    data = json.loads((d / "model.safetensors.index.json").read_text(encoding="utf-8"))
    data["weight_map"]["extra"] = "README.md"
    (d / "model.safetensors.index.json").write_text(json.dumps(data), encoding="utf-8")
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    assert fp["status"] == "incomplete"
    assert fp["referenced"]["not_hashed"][0].endswith("README.md")


def test_broken_index_is_incomplete(tmp_path):
    """Index khong doc duoc (JSON hong) -> khong the xac minh -> 'incomplete'."""
    root = tmp_path / "models"
    d = _sharded_dir(root, shards=1, declared=1)
    (d / "model.safetensors.index.json").write_text("{ khong-phai-json", encoding="utf-8")
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    assert fp["status"] == "incomplete"
    assert fp["referenced"]["unreadable"]


def test_unreadable_artifact_is_incomplete(tmp_path, monkeypatch):
    """Artifact khong doc duoc (OSError khi hash) -> 'incomplete', khong 'ok' (F1)."""
    root = tmp_path / "models"
    _sharded_dir(root, shards=2, declared=2)
    real = mi._sha_file

    def fake(path):
        if Path(path).name == "model-00002-of-00002.safetensors":
            return "unreadable:99999"
        return real(path)

    monkeypatch.setattr(mi, "_sha_file", fake)
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    assert fp["status"] == "incomplete"
    assert "model-00002-of-00002.safetensors" in fp["unreadable"]


def test_recheck_problem_flags_incomplete_model(tmp_path):
    """Re-check khi model tren dia thieu shard -> van de ro rang (khong 'ok' im lang)."""
    root = tmp_path / "models"
    _sharded_dir(root, shards=2, declared=2)
    pinned = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    (root / "PaddleOCR-VL-1.6" / "model-00002-of-00002.safetensors").unlink()
    problem = mi.recheck_problem(pinned, root, "PaddleOCR-VL-1.6")
    assert problem and "status=incomplete" in problem


def test_fingerprint_contains_no_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "huy_tester")
    root = tmp_path / "models"
    _hf_style_dir(root / "PaddleOCR-VL-1.6")
    fp = mi.model_fingerprint("PaddleOCR-VL-1.6", root, full=True)
    import json as _json
    blob = _json.dumps(fp, default=str)
    assert str(root) not in blob
    assert "huy_tester" not in blob
    assert "models" not in [k for k in fp["files"]], "key phai la duong dan TUONG DOI"
    assert str(tmp_path) not in blob
