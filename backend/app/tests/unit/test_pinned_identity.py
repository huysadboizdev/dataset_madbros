from __future__ import annotations

"""F2 (dot 5): identity pin -> worker phai la CUNG MOT identity da full-verify.

- JobManager full-hash DUNG MOT LAN roi pin + ghi identity file.
- Worker (adapter) nhan identity pin va re-check DAY DU (FULL SHA-256 moi artifact ke
  ca weight) truoc khi dung — KHONG dung sample fingerprint nhu bang chung toan ven.
  Chi phi that: doc lai weights mot lan nua luc worker load (da do trong bao cao);
  day la gia phai tra de khong bao gio chay bang model khac identity da pin.
- Model doi (ke ca byte NGOAI vung sample, cung kich thuoc/mtime), ten/dir lech hoac
  file pin hong -> `ModelChangedSincePin` (fail ro rang), KHONG fallback.
- Standalone (khong pin): tu full-hash DUNG MOT LAN, model_rev tu identity_from_fps.
"""

import json
import os
from pathlib import Path

import pytest

from backend.app.ocr import model_identity as mi
from backend.app.ocr.paddle_adapter import ModelChangedSincePin, _model_identity


class _FakePipeline:
    """Gia lap cai adapter thuc su doc tu _merged_paddlex_config."""

    def __init__(self, layout="PP-DocLayoutV3", vl="PaddleOCR-VL-1.6"):
        self._merged_paddlex_config = {
            "pipeline_name": "PaddleOCR-VL",
            "SubModules": {
                "LayoutDetection": {"model_name": layout, "threshold": 0.5},
                "VLRecognition": {"model_name": vl},
            },
        }


def _fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    for name, w in (("PP-DocLayoutV3", b"\x00" * 8192),
                    ("PaddleOCR-VL-1.6", b"\x01" * 8192)):
        d = root / name
        d.mkdir(parents=True)
        (d / "config.json").write_text(f'{{"m": "{name}"}}', encoding="utf-8")
        (d / "inference.yml").write_text("a: 1\n", encoding="utf-8")
        (d / "model.safetensors").write_bytes(w)
    return root


def _names():
    return ["PP-DocLayoutV3", "PaddleOCR-VL-1.6"]


@pytest.fixture()
def _hash_spy(monkeypatch):
    """Dem moi lan _sha_file duoc goi va tren file nao (duong dan tuyet doi chi
    dung de assert trong test, khong roi vao ket qua identity)."""
    calls = []

    real = mi._sha_file

    def spy(path):
        calls.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(mi, "_sha_file", spy)
    return calls


def test_pinned_verify_rehashes_weights_and_matches_tag(tmp_path, _hash_spy):
    """F2: duong pin re-check bang FULL SHA-256 (moi artifact) va tag tra ve TRUNG
    tag job da pin. Chi phi duoc ghi ro: moi weight bi doc lai dung 1 lan o buoc nay."""
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    tag = mi.identity_from_fps(list(fps.values()))
    _hash_spy.clear()
    ident = _model_identity(_FakePipeline(), pinned={"fps": fps, "tag": tag}, root=root)
    assert ident["identity_source"] == "pinned_job"
    assert ident["model_rev"] == tag, "rev tu pin phai trung tag job da pin"
    assert ident["recheck"] == "inventory+size+full_sha256_all_artifacts"
    assert _hash_spy.count("model.safetensors") == 2, (
        "F2: re-check pin phai FULL SHA-256 lai weights (1 lan/model), thay "
        + str(sorted(_hash_spy)))


def test_pinned_recheck_detects_out_of_sample_byte_change(tmp_path):
    """COUNTEREXAMPLE cua kiem toan F2 (ban cu tra 'ACCEPTED=YES').

    Weight 20 MB: doi 1 byte tai offset 6 MB (ngoai ca 3 cua so sample head/mid/tail),
    GIU NGUYEN kich thuoc va mtime -> pin cu KHONG con dung -> ModelChangedSincePin.
    """
    root = tmp_path / "models"
    for name in ("PP-DocLayoutV3", "PaddleOCR-VL-1.6"):
        d = root / name
        d.mkdir(parents=True)
        (d / "config.json").write_text('{"m": "%s"}' % name, encoding="utf-8")
    w = root / "PP-DocLayoutV3" / "model.safetensors"
    blob = bytearray(b"\x00" * (20 * 1024 * 1024))
    w.write_bytes(bytes(blob))
    (root / "PaddleOCR-VL-1.6" / "model.safetensors").write_bytes(b"\x01" * 4096)
    mtime0 = w.stat().st_mtime_ns
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    tag = mi.identity_from_fps(list(fps.values()))

    blob[6 * 1024 * 1024] = 0xFF              # NGOAI vung sample (4 MB moi vung)
    w.write_bytes(bytes(blob))
    os.utime(w, ns=(mtime0, mtime0))          # giu nguyen mtime
    assert w.stat().st_size == 20 * 1024 * 1024
    assert w.stat().st_mtime_ns == mtime0

    with pytest.raises(ModelChangedSincePin) as ei:
        _model_identity(_FakePipeline(), pinned={"fps": fps, "tag": tag}, root=root)
    assert "SHA-256 day du" in str(ei.value)


def test_pinned_recheck_detects_weight_content_change(tmp_path, _hash_spy):
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    # doi noi dung weight GIU kich thuoc (sample window phat hien vi file nho)
    w = root / "PaddleOCR-VL-1.6" / "model.safetensors"
    w.write_bytes(b"\x02" * 8192)
    with pytest.raises(ModelChangedSincePin):
        _model_identity(_FakePipeline(), pinned={"fps": fps}, root=root)


def test_pinned_recheck_detects_added_and_removed_artifact(tmp_path):
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    # them artifact tien xu ly moi sau khi pin
    (root / "PaddleOCR-VL-1.6" / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ModelChangedSincePin) as ei:
        _model_identity(_FakePipeline(), pinned={"fps": fps}, root=root)
    assert "inventory" in str(ei.value)
    # xoa config sau khi pin
    (root / "PP-DocLayoutV3" / "config.json").unlink()
    with pytest.raises(ModelChangedSincePin):
        _model_identity(_FakePipeline(), pinned={"fps": fps}, root=root)


def test_self_path_hashes_weights_exactly_once(tmp_path, _hash_spy):
    """Khong pin (standalone): moi weight artifact phai full-hash DUNG 1 lan
    (ban cu: model_fingerprint full + identity_hash doc lai = 2 lan)."""
    root = _fake_root(tmp_path)
    ident = _model_identity(_FakePipeline(), root=root)
    assert ident["identity_source"] == "engine_load_self"
    n_weight_hash = _hash_spy.count("model.safetensors")
    assert n_weight_hash == 2, (
        f"2 model x 1 weight: moi weight dung 1 lan, thay {n_weight_hash}")


def test_pinned_name_mismatch_raises_not_fallback(tmp_path):
    """F2 (finding 3.2): pin lech ten/model -> FAIL ro rang. Ban cu dat co
    `pinned_mismatch` roi tu self-hash — worker dung model khac identity da pin ma van
    tra ket qua => tai hien duoc dung loi B4 that."""
    root = _fake_root(tmp_path)
    fps = {"Other-Model": mi.model_fingerprint("PP-DocLayoutV3", root, full=True)}
    with pytest.raises(ModelChangedSincePin) as ei:
        _model_identity(_FakePipeline(), pinned={"fps": fps}, root=root)
    assert "khong co fingerprint pin" in str(ei.value)


def test_pinned_file_tag_mismatch_raises(tmp_path):
    """File pin bi sua (tag khong khop fingerprint) -> fail, khong dung tag do."""
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    with pytest.raises(ModelChangedSincePin) as ei:
        _model_identity(_FakePipeline(),
                        pinned={"fps": fps, "tag": "deadbeefdeadbeef"}, root=root)
    assert "KHONG khop fingerprint" in str(ei.value)


def test_pinned_sample_only_fingerprint_is_rejected(tmp_path):
    """F2: fingerprint pin tinh bang sample (khong co SHA-256 day du cho weight)
    KHONG duoc coi la tuong duong -> phai fail, khong duoc dung lam bang chung."""
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=False) for n in _names()}
    with pytest.raises(ModelChangedSincePin) as ei:
        _model_identity(_FakePipeline(), pinned={"fps": fps}, root=root)
    assert "khong co fingerprint pin" in str(ei.value) or \
        "thieu SHA-256 day du" in str(ei.value)


def test_resolved_name_differs_from_declared_name_but_same_dir(tmp_path):
    """NGUYEN NHAN THAT cua F2 tren may that: config khai 'PaddleOCR-VL-1.6', con
    pipeline resolve 'PaddleOCR-VL-1.6-0.9B' (cung 1 thu muc). Ban cu so sanh TEN ->
    'pinned_mismatch' gia -> worker self-hash -> cache ghi duoi tag khac identity.
    Nay identity chuan hoa theo TEN THU MUC -> khong mismatch, tag TRUNG pin."""
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    tag = mi.identity_from_fps(list(fps.values()))
    ident = _model_identity(
        _FakePipeline(layout="PP-DocLayoutV3", vl="PaddleOCR-VL-1.6-0.9B"),
        pinned={"fps": fps, "tag": tag}, root=root)
    assert ident["identity_source"] == "pinned_job"
    assert ident["model_rev"] == tag
    assert ident["resolved_vl_model"] == "PaddleOCR-VL-1.6-0.9B"
    assert mi.model_key(root, "PaddleOCR-VL-1.6-0.9B") == "PaddleOCR-VL-1.6"


def test_pinned_identity_matches_job_tag(tmp_path):
    """identity ghi trong model_meta phai trung tag cache da pin — neu khong,
    provenance xuat ra se khac cache key (loi dung da co trong B4 cu)."""
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    tag = mi.identity_from_fps([fps[n] for n in sorted(_names())])
    ident = _model_identity(_FakePipeline(), pinned={"fps": fps, "tag": tag}, root=root)
    assert ident["model_rev"] == tag
    payload = json.dumps(ident["model_fp"])  # xuat duoc, khong chua Path object
    assert "models" not in payload


# ---------- F2: quyet dinh tag cache duoc phep GHI (phia MANAGER, khong phai worker) ----------

def _worker_meta(fps, rev=None, **extra):
    meta = {"model_fp": fps, "identity_source": "pinned_job"}
    meta["model_rev"] = rev if rev is not None else mi.identity_from_fps(list(fps.values()))
    meta.update(extra)
    return meta


def test_cache_tag_for_write_accepts_matching_worker_identity(tmp_path):
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    pin = mi.identity_from_fps(list(fps.values()))
    tag, err = mi.cache_tag_for_write(pin, _worker_meta(fps))
    assert err is None and tag == pin


def test_cache_tag_for_write_rejects_mismatch_with_pin(tmp_path):
    """Worker dung model KHAC pin -> (None, error): ben goi TUYET DOI khong duoc ghi
    cache duoi tag cu."""
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    pin = mi.identity_from_fps(list(fps.values()))
    other = json.loads(json.dumps(fps))          # copy sau
    other["PP-DocLayoutV3"]["files"]["config.json"]["sha256"] = "f" * 64
    other["PP-DocLayoutV3"]["config_sha256"]["config.json"] = "f" * 64
    tag, err = mi.cache_tag_for_write(pin, _worker_meta(other))
    assert tag is None and err == "pinned_worker_identity_mismatch"


def test_cache_tag_for_write_requires_full_verified_worker_identity(tmp_path):
    root = _fake_root(tmp_path)
    fps = {n: mi.model_fingerprint(n, root, full=True) for n in _names()}
    # 1) khong bao identity
    assert mi.cache_tag_for_write("abc", {"engine": "fake_recording"}) == \
        (None, "worker_identity_unverified")
    # 2) bao loi doc metadata
    assert mi.cache_tag_for_write("abc", {"model_fp": fps, "model_rev_error": "boom"}) == \
        (None, "worker_identity_unverified")
    # 3) model_rev khong khop fingerprint (worker bao sai)
    assert mi.cache_tag_for_write("abc", _worker_meta(fps, rev="0" * 16)) == \
        (None, "worker_identity_unverified")
    # 4) fingerprint chi co sample (khong SHA-256 day du) -> khong phai full-verify
    sample = {n: mi.model_fingerprint(n, root, full=False) for n in _names()}
    assert mi.cache_tag_for_write("abc", _worker_meta(sample)) == \
        (None, "worker_identity_unverified")
    # 5) worker tu full-verify trong khi pin 'unresolved' -> dung tag worker tra ve
    tag, err = mi.cache_tag_for_write("unresolved", _worker_meta(fps))
    assert err is None and tag == mi.identity_from_fps(list(fps.values()))