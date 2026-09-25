from __future__ import annotations

"""Danh tinh model doc LAP DUONG DAN — dung cho CA cache key lan provenance xuat.

Nguyen tac (S4 — phien ban 3, sau finding F1/F2 dot 5):
- KHONG bao gio dua duong dan tuyet doi / home / username vao ket qua (chi hash + ten).
- 'hash' phai la SHA-256 THAT cua artifact, khong phai kich thuoc byte.
- INVENTORY THEO QUY TAC, KHONG theo danh sach ten hardcode: moi file trong thu muc
  model (de quy, key = duong dan TUONG DOI) deu tham gia fingerprint, TRU cac mau
  `_EXCLUDE_*` duoc ghi ro ly do (khong anh huong inference). Diem quan trong:
  preprocessor_config.json / processor_config.json / tokenizer_config.json /
  special_tokens_map.json / tokenizer.model / *.safetensors.index.json ... deu duoc
  hash vi chung thay doi CACH TIEN XU LY TOKEN/ANH — doi no phai lam cache stale.
- F1: moi shard/artifact BAT BUOC duoc `*.index.json` tham chieu phai TON TAI va DA
  HASH; thieu/khong doc duoc -> status='incomplete' (KHONG duoc coi la 'ok').
- F2: identity duoc CHUAN HOA theo TEN THU MUC THAT tren dia (`model_key`) va sap xep
  noi bo, nen ben pin (JobManager, ten khai bao trong config) va ben dung (worker, ten
  do pipeline tu resolve, vi du 'PaddleOCR-VL-1.6-0.9B') tinh ra CUNG mot tag khi va
  chi khi cung mot thu muc model. Re-check khi worker load la FULL SHA-256 (khong dung
  sample fingerprint nhu bang chung toan ven — xem `recheck_problem`).
- Weight file co the >1 GB: full mode tinh SHA-256 DAY DU; sample_fp chi de so sanh
  nhanh/health, KHONG tuong duong SHA-256 day du.
- Model dir KHONG co artifact weight nao -> status='incomplete' (KHONG duoc coi la ok).
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Chan muc doc de lay mau (khong doc het 1.9GB moi lan kiem cache).
_SAMPLE_WINDOW = 4 * 1024 * 1024  # 4 MB moi vung

# Extension co the la WEIGHT (so khop theo suffix, khong phai ten cu the —
# .pdiparams la ten THAT cua weight PaddleX 3.x; .safetensors la HF).
_WEIGHT_EXTS = (".safetensors", ".bin", ".pb", ".pdiplomamodel", ".pdparams",
                ".pdiparams", ".msgpack", ".npz", ".pdmodel", ".onnx", ".pt", ".pth")

# File KHONG anh huong inference -> loai KHOI inventory (ly do ghi ro):
# - tai lieu mo ta (README/LICENSE/NOTICE, *.md), anh card mo ta model;
# - trang thai TRAINING (optimizer/scheduler/rng/training_args) — resume training
#   khong phai inference;
# - metadata he dieu hanh / git.
_EXCLUDE_NAME_EXACT = {"training_args.bin", "optimizer.pt", "scheduler.pt",
                       "rng_state.pth", "scaler.pt",
                       ".ds_store", "thumbs.db", ".gitattributes", ".gitignore",
                       ".gitkeep", ".gitmodules"}
_EXCLUDE_NAME_PREFIX = ("readme", "license", "licence", "notice", ".git")
_EXCLUDE_EXTS = (".md", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                 ".log", ".tmp", ".bak", ".swp")
# Thu muc khong bao gio la artifact inference (tensorboard/state cu).
_EXCLUDE_DIR_PARTS = {".git", "runs", "__pycache__"}


def _excluded(rel_parts: tuple, name: str) -> bool:
    """rel_parts = cac thanh phan duong dan tuong doi (khong co ten file cuoi)."""
    low = name.lower()
    if low in _EXCLUDE_NAME_EXACT or any(low.startswith(p) for p in _EXCLUDE_NAME_PREFIX):
        return True
    if Path(low).suffix in _EXCLUDE_EXTS:
        return True
    if any(part.lower() in _EXCLUDE_DIR_PARTS for part in rel_parts):
        return True
    return False


def model_key(root: Path, model_name: str) -> str:
    """Khoa ON DINH cua mot model = TEN THU MUC THAT tren dia.

    F2: ben pin dung ten KHAI BAO trong config ('PaddleOCR-VL-1.6'), con worker dung
    ten do chinh pipeline tu resolve ('PaddleOCR-VL-1.6-0.9B'). Ca hai tro cung mot
    thu muc -> phai tinh ra CUNG mot tag, neu khong se co 'pinned_mismatch' gia va
    cache bi ghi duoi tag khac identity thuc dung.
    """
    d = resolve_model_dir(root, model_name)
    return d.name if d is not None else str(model_name)


def _index_references(d: Path, hashed_rel: Iterable[str]) -> Dict[str, List[str]]:
    """Artifact BAT BUOC theo `*.index.json` (safetensors shard index) — F1.

    Moi file duoc index tham chieu PHAI (a) ton tai tren dia va (b) nam trong inventory
    DA HASH. Index khong doc duoc cung la loi: khong the xac minh tinh day du.
    """
    hashed = set(hashed_rel)
    out: Dict[str, List[str]] = {"indexes": [], "missing": [], "not_hashed": [],
                                 "unreadable": []}
    for p in sorted(d.rglob("*.index.json")):
        if not p.is_file():
            continue
        rel = p.relative_to(d).as_posix()
        if _excluded(tuple(Path(rel).parts[:-1]), p.name):
            continue
        out["indexes"].append(rel)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            out["unreadable"].append(f"{rel} ({type(e).__name__})")
            continue
        wm = data.get("weight_map") if isinstance(data, dict) else None
        refs = sorted({str(v) for v in wm.values()}) if isinstance(wm, dict) else []
        for r in refs:
            rr = PurePosixPath(str(r).replace("\\", "/")).as_posix()
            if rr.startswith("../") or rr.startswith("/") or ":" in rr:
                out["unreadable"].append(f"{rel}->{rr} (duong dan khong hop le)")
                continue
            if not (d / rr).is_file():
                out["missing"].append(f"{rel}->{rr}")
            elif rr not in hashed:
                out["not_hashed"].append(f"{rel}->{rr}")
    return out


def official_root() -> Path:
    """Thu muc model chuan; cho phep override bang env (test dung thu muc gia lap)."""
    r = os.environ.get("PDFCLEANER_MODEL_ROOT")
    if r:
        return Path(r)
    return Path.home() / ".paddlex" / "official_models"


class ModelChangedSincePin(RuntimeError):
    """Model tren dia KHONG con dung identity da pin cho job.

    F2: day KHONG phai loi metadata vui ve — khong duoc nuot loi nay, khong duoc
    "roi ve self-hash roi van ghi cache duoi tag cu". Phai fail ro rang (worker bao
    model_failed) thay vi gan identity cu cho engine khac.
    Thong bao KHONG chua duong dan tuyet doi.
    """


def resolve_model_dir(root: Path, model_name: str) -> Optional[Path]:
    """Khop ten that cua thu muc model (prefix dai nhat), khong log duong dan ra ngoai."""
    if not root.exists():
        return None
    direct = root / model_name
    if direct.exists() and direct.is_dir():
        return direct
    best: Optional[Path] = None
    for d in root.iterdir():
        if not d.is_dir():
            continue
        if model_name.startswith(d.name) or d.name.startswith(model_name):
            if best is None or len(d.name) > len(best.name):
                best = d
    return best


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ten cu giu de tuong thim voi code hien co; ham nay la diem spy trong test.
_sha_file = sha_file


def _sample_fingerprint(path: Path, window: int = _SAMPLE_WINDOW) -> str:
    """SHA-256 tren (kich thuoc + head + mid + tail). Bat duoc NOI DUNG doi du cung
    kich thuoc (yeu cau S4), ma khong phai doc ca tep lon moi lan."""
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode("ascii"))
    try:
        with open(path, "rb") as f:
            head = f.read(window)
            h.update(head)
            if size > 2 * window:
                f.seek(max(0, size // 2 - window // 2))
                h.update(f.read(window))
                f.seek(max(0, size - window))
                h.update(f.read(window))
    except OSError:
        return f"unreadable:{size}"
    return h.hexdigest()


def _artifact_inventory(d: Path) -> List[Path]:
    """Tat ca file tham gia fingerprint (da loai cac mau khong anh huong inference),
    sap xep theo duong dan tuong doi -> thu tu ONN DINH."""
    out: List[Path] = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(d)
        if _excluded(tuple(rel.parts[:-1]), p.name):
            continue
        out.append(p)
    return out


def model_fingerprint(model_name: str, root: Optional[Path] = None,
                      full: bool = False) -> Dict[str, object]:
    """Chu ky model du de phat hien thay doi, KHONG chua duong dan tuyet doi.

    full=True -> SHA-256 day du cho weight (cham; goi DUNG 1 lan/job luc pin) +
                 sample_fp luu kem de worker re-check khong phai hash lai.
    full=False -> weight chi dung sample fingerprint (nhanh).
    File KHONG phai weight luon duoc hash FULL (nho, chi phi ~0).
    Model khong co weight -> status='incomplete' (tuyet doi khong 'ok').
    """
    root = root or official_root()
    d = resolve_model_dir(root, model_name)
    if d is None:
        return {"status": "missing", "model": model_name}
    weights: Dict[str, object] = {}
    configs: Dict[str, str] = {}
    files: Dict[str, Dict[str, object]] = {}
    for p in _artifact_inventory(d):
        rel = p.relative_to(d).as_posix()
        size = p.stat().st_size
        if p.suffix.lower() in _WEIGHT_EXTS:
            if full:
                entry = {"size": size, "sha256": _sha_file(p),
                         "sample_fp": _sample_fingerprint(p)}
            else:
                entry = {"size": size, "sample_fp": _sample_fingerprint(p)}
            weights[rel] = entry
        else:
            sha = _sha_file(p)
            entry = {"size": size, "sha256": sha}
            configs[rel] = sha
        files[rel] = entry
    info: Dict[str, object] = {"model": model_name,
                               # ten THU MUC THAT -> khoa identity on dinh (F2)
                               "model_dir_name": d.name,
                               "config_sha256": configs,
                               "weights": weights,
                               "files": files}
    # F1: artifact tham chieu boi *.index.json phai ton tai + da hash.
    refs = _index_references(d, files)
    if any(refs.values()):
        info["referenced"] = refs
    unreadable = sorted(rel for rel, e in files.items()
                        if str(e.get("sha256", "")).startswith("unreadable:")
                        or str(e.get("sample_fp", "")).startswith("unreadable:"))
    if unreadable:
        info["unreadable"] = unreadable
    if not weights:
        info["status"] = "incomplete"
        info["status_reason"] = "khong co artifact weight nao"
    elif refs["missing"] or refs["not_hashed"] or refs["unreadable"] or unreadable:
        info["status"] = "incomplete"
        info["status_reason"] = ("artifact tham chieu boi index thieu / khong doc duoc / "
                                 "chua duoc hash")
    else:
        info["status"] = "ok"
    return info


_CANON_FIELDS = ("status", "config_sha256", "weights", "files", "unreadable", "referenced")


def fp_canonical(fp: Dict[str, object]) -> Dict[str, object]:
    """Tap con ON DINH cua fingerprint de tinh identity (F2).

    - Chi giu du lieu anh huong inference / toan ven (SHA-256, size) — khong co duong
      dan tuyet doi.
    - Ten KHAI BAO duoc THAY bang ten THU MUC THAT tren dia (`model_dir_name`), nen
      ben pin (ten trong config) va ben dung (ten pipeline tu resolve) ra CUNG tag.
    """
    out: Dict[str, object] = {"model": fp.get("model_dir_name") or fp.get("model") or ""}
    for k in _CANON_FIELDS:
        v = fp.get(k)
        if v in (None, {}, []):
            continue
        if k == "referenced" and isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if vv}
            if not v:
                continue
        out[k] = v
    return out


def identity_from_fps(fps: List[Dict[str, object]]) -> str:
    """Hash ON DINH cua BO fingerprint DA TINH SAN (khong doc lai model).

    - Chuan hoa tung fingerprint (`fp_canonical`) va SAP XEP noi bo theo khoa model ->
      thu tu tham so goi vao KHONG con anh huong tag (F2: manager sap theo ten khai bao,
      worker sap theo ten resolve, van ra cung tag).
    - Khong chua duong dan tuyet doi -> an toan de xuat.
    """
    canon = sorted((fp_canonical(f) for f in fps if isinstance(f, dict)),
                   key=lambda c: (str(c.get("model")),
                                  json.dumps(c, sort_keys=True, default=str)))
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def identity_hash(model_names: List[str], root: Optional[Path] = None,
                  full: bool = False) -> str:
    """Hash ONN DINH cua bo fingerprint model — dung lam cache tag / provenance id.
    Khong thuoc thuoc duong dan (chi co SHA-256 + ten model, khong co duong dan).
    Luu y: goi ham NAY se doc lai model; neu vua tinh model_fingerprint xong thi
    dung identity_from_fps(de hash DAY DU DUNG MOT LAN/job)."""
    root = root or official_root()
    parts = [model_fingerprint(n, root, full=full)
             for n in sorted(filter(None, model_names))]
    return identity_from_fps(parts)


def recheck_problem(fp_pinned: Dict[str, Any], root: Path, name: str,
                    full: bool = True) -> Optional[str]:
    """So model TREN DIA voi fingerprint DA PIN (F2).

    full=True (MAC DINH): SHA-256 DAY DU moi artifact ke ca weight -> bat ca byte doi
    NGOAI vung sample (head/mid/tail) khi cung kich thuoc. Chi phi THAT: doc lai toan bo
    weight MOT lan luc worker load (job co OCR) — da do va ghi trong
    `docs/ACCEPTANCE_REPORT.md`; day la gia phai tra de khong dung model khac identity.
    full=False: chi inventory + size + sample_fp — KHONG tuong duong SHA-256 day du, chi
    dung cho health/so sanh nhanh, KHONG duoc dung lam bang chung toan ven.
    Tra None neu khop; nguoc lai chuoi mo ta artifact lech (khong chua duong dan tuyet doi).
    """
    key = model_key(root, name)
    cur = model_fingerprint(name, root, full=True if full else False)
    if cur.get("status") != "ok":
        ref = cur.get("referenced") or {}
        extra = sorted(set(list(ref.get("missing", [])) + list(ref.get("not_hashed", []))
                           + list(ref.get("unreadable", []))
                           + list(cur.get("unreadable") or [])))[:3]
        return f"{key}: status={cur.get('status')} {extra}"
    pin_files = dict(fp_pinned.get("files") or {})
    cur_files = dict(cur.get("files") or {})
    if not pin_files:
        return f"{key}: pinned fingerprint khong co inventory"
    if set(pin_files) != set(cur_files):
        only_pin = sorted(set(pin_files) - set(cur_files))[:3]
        only_cur = sorted(set(cur_files) - set(pin_files))[:3]
        return f"{key}: inventory changed (them={only_cur}, bot={only_pin})"
    for rel, pe in sorted(pin_files.items()):
        ce = cur_files.get(rel) or {}
        if pe.get("size") != ce.get("size"):
            return f"{key}/{rel}: size changed"
        if full:
            ps, cs = pe.get("sha256"), ce.get("sha256")
            if not ps:
                return f"{key}/{rel}: pinned fingerprint thieu SHA-256 day du"
            if ps != cs:
                return (f"{key}/{rel}: content changed (SHA-256 day du, "
                        "ke ca byte ngoai vung sample)")
        elif "sample_fp" in pe and pe.get("sample_fp") != ce.get("sample_fp"):
            return f"{key}/{rel}: sample window changed"
    return None


def verify_pinned(pinned: Dict[str, Any], root: Path, names: List[str],
                  full_recheck: bool = True) -> Tuple[Dict[str, Any], str, str]:
    """Model engine THUC DUNG co dung identity da pin khong? (F2)

    -> (fps theo ten engine resolve, tag, recheck_note). Raise `ModelChangedSincePin` khi:
    thieu fingerprint pin tuong ung (ten/dir lech), pin khong 'ok', tag trong file pin
    khong khop fingerprint (file pin hong/bi sua), hoac noi dung lech khi re-check.
    KHONG bao gio "roi ve self-hash roi van dung tag cu" — ben goi phai fail ro rang.
    """
    pinned = pinned or {}
    pin_fps = dict(pinned.get("fps") or {})
    by_key: Dict[str, Dict[str, Any]] = {}
    for k, fp in pin_fps.items():
        if isinstance(fp, dict):
            by_key.setdefault(model_key(root, str(k)), fp)
    problems: List[str] = []
    fps: Dict[str, Any] = {}
    for name in names:
        key = model_key(root, name)
        fp = by_key.get(key)
        if fp is None:
            problems.append(f"{key}: khong co fingerprint pin tuong ung")
            continue
        if fp.get("status") != "ok":
            problems.append(f"{key}: pinned status={fp.get('status')}"
                            f" ({fp.get('status_reason')})")
            continue
        fps[name] = fp
    if not problems:
        pin_tag = pinned.get("tag")
        if pin_tag:
            cur = identity_from_fps(list(fps.values()))
            if str(pin_tag) != cur:
                problems.append("pin: tag trong file KHONG khop fingerprint "
                                "(file pin hong hoac bi sua)")
    if not problems:
        for name in names:
            p = recheck_problem(fps[name], root, name, full=full_recheck)
            if p:
                problems.append(p)
    if problems:
        raise ModelChangedSincePin("; ".join(problems))
    note = ("inventory+size+full_sha256_all_artifacts" if full_recheck
            else "inventory+size+sample_fp (KHONG tuong duong SHA-256 day du)")
    return fps, identity_from_fps(list(fps.values())), note


def worker_verified_tag(engine_meta: Dict[str, Any]) -> Optional[str]:
    """Tag tu identity do CHINH WORKER full-verify (F2).

    Tra None neu worker khong bao identity, bao loi, mot model khong 'ok', khong co
    SHA-256 day du cho weight, hoac `model_rev` khong khop fingerprint — trong moi
    truong hop do KHONG duoc dung lam cache tag.
    """
    if not isinstance(engine_meta, dict):
        return None
    fps = engine_meta.get("model_fp")
    if not isinstance(fps, dict) or not fps:
        return None
    if engine_meta.get("model_rev_error"):
        return None
    for fp in fps.values():
        if not isinstance(fp, dict) or fp.get("status") != "ok":
            return None
        weights = fp.get("weights") or {}
        if not weights or not any("sha256" in (w or {}) for w in weights.values()):
            return None  # khong co SHA-256 day du -> khong phai full-verify
    tag = identity_from_fps(list(fps.values()))
    rev = engine_meta.get("model_rev")
    if rev and str(rev) != tag:
        return None
    return tag


def cache_tag_for_write(pinned_tag: Optional[str],
                        engine_meta: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """TAG duoc phep dung khi GHI cache OCR (F2) -> (tag | None, error | None).

    Bat buoc: tag GHI = identity do worker THUC DUNG tu full-verify. Neu pin da resolved
    thi tag nay PHAI TRUNG tag da pin; lech -> tra error va ben goi TUYET DOI khong duoc
    ghi cache duoi tag cu (phai fail ro rang / danh dau chua xac minh).
    """
    wtag = worker_verified_tag(engine_meta)
    if wtag is None:
        return None, "worker_identity_unverified"
    if pinned_tag and str(pinned_tag) != "unresolved" and str(pinned_tag) != wtag:
        return None, "pinned_worker_identity_mismatch"
    return wtag, None
