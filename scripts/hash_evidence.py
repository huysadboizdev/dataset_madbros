from __future__ import annotations

"""Bang chung artifact NGHIEM THU (S8) — TACH RO hai thao tac (finding F3):

  1. `python scripts/hash_evidence.py prepare`  — CHUAN BI/SANITIZE (CO ghi doi file):
     sanitize docs/ tai cho (giu BAN GOC vao `data/evidence_originals/`, ngoai docs/),
     sinh `docs/sanitized_logs/*.sanitized`, don file tam con sot.
  2. `python scripts/hash_evidence.py hash`     — HASH/VERIFY CHI DOC: khong sinh, khong
     sua bat ky file nao trong docs/; chi validate fail-closed + ghi manifest.

Truoc day mot lenh vua sanitize vua hash (mac dinh `--out`) khien "hash/verify" co the
thay doi chinh nguon evidence — da bo.

TACH KHOI SOURCE_SNAPSHOT de tranh tu doi chieu vong tron:
- SOURCE_SNAPSHOT.sha256 : chi ma nguon + cau hinh (khong chua artifact).
- EVIDENCE_SNAPSHOT.sha256: chi artifact/ bao cao + THAM CHIEU mot chieu den
  SOURCE_SNAPSHOT.sha256 (truoc do). EVIDENCE KHONG duoc SOURCE tham chieu nguoc.
- File nay KHONG tu hash chinh no. File TAM (`tmp*.tmp`) KHONG BAO GIO vao manifest.

Khong dua duong dan tuyet doi / secret vao. Log OCR that duoc SANITIZE bang regex
Windows/Unix/UNC (KHONG pha URL/LaTeX/duong dan tuong doi) + kiem tra fail-closed truoc
khi hash (docs/sanitized_logs/).

  python scripts/hash_evidence.py prepare
  python scripts/hash_evidence.py hash --out docs/EVIDENCE_SNAPSHOT.sha256
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
# Ban GOC cua file bi sanitize: de NGOAI docs/ (khong nam trong evidence, khong bi
# validator docs/ chan vi chua duong dan that). Chi ghi khi file sap bi sua lan dau.
ORIGINALS_DIR = ROOT / "data" / "evidence_originals"

# Artifact / bao cao duoc chung minh (ton tai moi duoc dua vao; thieu -> bo, khong loi)
EVIDENCE_PATTERNS = [
    "SOURCE_SNAPSHOT.sha256",          # tham chieu mot chieu den snapshot nguon
    "ACCEPTANCE_REPORT.md",
    "IMPLEMENTATION_STATUS.md",
    "FORMULA_CHECK.md",
    "BENCHMARK.md",
    "e2e_real_export.zip",
    "formula_fixture/formula_fixture.pdf",
    "formula_fixture/model_meta.json",
    "benchmark_dump/summary.json",
    "benchmark_dump/page_0006_blocks.json",
    "benchmark_dump/page_0007_blocks.json",
    "sanitized_logs/formula_run0915.log.sanitized",   # ban sanitized cua log chay that
    "sanitized_logs/formula_run0915.err.sanitized",
    "sanitized_logs/e2e_real_run0915.log.sanitized",
    "sanitized_logs/e2e_real_run0915.err.sanitized",
]
EVIDENCE_DIRS = ["formula_fixture/ocr_raw"]  # raw blocks + verify per page tu verify_formula_ocr
# Log chay that duoc SANITIZE roi moi dua vao evidence (KHONG luu log tho —
# log tho chua duong dan tuyen doi C:\Users\...). San pham sanitize nam o
# docs/sanitized_logs/ va chi ghi de khi qua duoc buoc KIEM TRA sau sanitize.
SANITIZED_LOG_SOURCES = [
    "formula_run0915.log", "formula_run0915.err",
    "e2e_real_run0915.log", "e2e_real_run0915.err",
]
SANITIZED_DIR = "sanitized_logs"

# Duong dan: Windows (C:\... hoac C:/...), UNC (\\srv\...), Unix (diem bat dau = sep).
# Ca hai loai sep, khong phan biet hoa thuong; day la regex co dem du, KHONG phai
# 2 lenh Replace thu cong.
# Ranh gioi dau (`(?<!\w)` — lookbehind UNICODE, khong phai `[A-Za-z0-9_]`): neu dung
# lop ASCII thi tieng Viet bi pha — "sau đây:\na" co `y:\` vi 'â' (U+00E2) khong thuoc
# `[A-Za-z0-9_]` (tim thay that trong page_0030_blocks.json).
#
# THANH PHAN THU BA bat buoc: it nhat 1 ky tu "than path" ([A-Za-z0-9]) NGAY SAU sep
# — khong thi quote/backtick bi hong: `s:/` trong van ban mo ta (backtick truoc 's',
# khong phai \w) se bi coi la drive path; thu "s:/" duoc dung de MINH HOA loi regex
# trong file audit. Mot drive letter khong theo ngay boi ky tu = khong phai duong dan.
_RE_ABS_WIN = re.compile(r"(?<!\w)[A-Za-z]:[\\/][A-Za-z0-9][^\s\"',;)\]}<>]*")
_RE_UNC = re.compile(r"\\\\[A-Za-z0-9][A-Za-z0-9._$-]*[\\/][^\s\"',;)\]}<>]*")
_RE_ABS_UNIX = re.compile(r"(?<![\w])[\\/](?:home|users|usr|var|tmp|root|mnt|media|program files|programdata)[\\/][^\s\"',;)\]}<>]*", re.I)
_RE_HOMETILDE = re.compile(r"~[\\/][^\s\"',;)\]}<>]*")
# Sau sanitize: van con duong dan/username thi FAIL (fail-closed), khong xuat manifest.
# Username chi bi coi la RO khi dang nam trong boi canh duong dan (dinh ngay sau
# sep/truoc sep) — khong chan nham tu tieng Viet chua thanh cua ten (vi du "huyen").
# F3(b): `users`/`home` cung can ranh gioi dau — `https://site/home/x` KHONG phai
# duong dan; chan nham no la fail-closed gia, tuoc man phat hanh vi loi phat hien.
_USER = re.escape(os.environ.get("USERNAME", ""))
_USER_IN_PATH = (rf"(?:[~\\/]|\bpath\s*){_USER}\b" if _USER else r"(?!x)x")
_RE_LEAK = re.compile(
    # 'users' chi tinh la leak khi nam trong boi canh path (/users/...) — tu 'users'
    # trong van mo ta (vd: "Unix /home|users|var") KHONG phai leak.
    # F3.2: cung ranh gioi nhu tren — URL/LaTeX KHONG bi coi la leak (ban cu bao nham
    # `[A-Za-z]:[\\/]` ben trong `https://` va `\\\\` trong LaTeX). Chu y: san pham
    # sau sanitize la `[PATH]` (khong con drive letter) NEN leak-check PHAI chay tren
    # ban GOC (raw) — xem `has_raw_path_leak` — chu khong phai tren ban da thay.
    # (thanh phan thu ba giong _RE_ABS_WIN: `s:/` don le trong van mo ta khong phai leak)
    r"[\\/][A-Za-z]:[\\/][A-Za-z0-9]|(?<!\w)[A-Za-z]:[\\/][A-Za-z0-9]"
    r"|\\\\[A-Za-z0-9][A-Za-z0-9._$-]*[\\/]|(?<!\w)/users/|(?<!\w)/home/"
    + ("|" + _USER_IN_PATH if _USER else ""),
    re.I,
)

# File tam do chinh thao tac nay (atomic write / ghi lai ZIP) de lai: KHONG BAO GIO vao
# manifest evidence va bi don sach o buoc `prepare`.
_TMP_NAME = re.compile(r"^tmp[0-9A-Za-z_]{0,12}\.tmp$", re.I)

# Directory VAN HANH duoi docs/ (roadmap/SOP cua team) — KHONG phai artifact nghiem
# thu, khong bi hash; duoc phep chua duong dan may local (D:\...) vi gia tri su dung
# cua chung la lenh chay truc tiep. NGOAI LE bat buoc: neu file nao trong day duoc
# dua vao EVIDENCE_PATTERNS/EVIDENCE_DIRS (tuc tro thanh chung) thi validator VAN
# phan tich that — xem `validate_docs_clean` must_clean (khong co ao che mien khai).
NON_EVIDENCE_SUBDIRS = ("plans",)

# --- S4-dot-sau (finding 3): san pham sanitize phai COVER MD + JSON LONG + ZIP ---
# File van ban/bao cao trong docs ma qua quet co leak -> duoc sanitize TAI CHO
# (chung la artifact nguoi dung doc / duoc hash trong evidence, khong duoc chua duong dan).
SANITIZE_TEXT_GLOBS = [
    "ACCEPTANCE_REPORT.md",
    "IMPLEMENTATION_STATUS.md",
    "BENCHMARK.md",
    "FORMULA_CHECK.md",
    "formula_fixture/**/*.json",
    "benchmark_dump/**/*.json",
    "benchmark_dump_skg2/**/*.json",
]
# Log THO trong docs van con leak: log thoi diem chay, khong duoc hash (san pham
# hashed la ban .sanitized); van sanitize tai cho de TOAN BO docs/ khong con leak.
_RAW_LOGS = ["formula_run0915.log", "formula_run0915.err",
             "e2e_real_run0915.log", "e2e_real_run0915.err",
             "formula_run.log", "formula_run.err",
             "e2e_real.err", "benchmark_run_page5.err", "benchmark_run_pages.err",
             "bench_skg2.err", "pw_install.log"]
_TEXT_EXTS = (".md", ".txt", ".log", ".json", ".jsonl", ".csv", ".html", ".xml",
              ".yml", ".yaml", ".err")


def sanitize_text(text: str) -> str:
    """Regexp pipeline DUNG CHUNG cho log/markdown/json/zip-member (khong phai
    2 lenh replace thu cong): Windows, UNC, Unix-home, ~/."""
    text = _RE_ABS_WIN.sub("[PATH]", text)
    text = _RE_UNC.sub("[PATH]", text)
    text = _RE_ABS_UNIX.sub("[PATH]", text)
    text = _RE_HOMETILDE.sub("[PATH]", text)
    return text


def _decode_strict(raw: bytes, declared_encoding: Optional[str] = None) -> str:
    """Decode fail-closed, KHONG doan cua (F3.c):
      - UTF-16 khi co BOM (BOM la TINH HIEU NGUON tu khai bao, khong phai doan);
      - UTF-8 strict cho moi truong hop con lai;
      - encoding khac chi dung khi GOI TINH KHAI BAO RO RANG (`declared_encoding`,
        tu CLI `prepare --encoding`).
    Ban cu thu cp1252 cho MOI byte khong UTF-8: decode duoc ve mat codec KHONG
    chung minh nguon la cp1252 — byte roi thanh van ban gia im lang. Ky tu loi
    phai LA LOI RO RANG (SystemExit); khong errors='replace'/'ignore'."""
    if declared_encoding:                       # khai bao ro -> strict theo khai bao
        try:
            return raw.decode(declared_encoding)
        except (UnicodeDecodeError, LookupError) as e:
            raise SystemExit(
                f"LOI decode: KHAI BAO encoding={declared_encoding!r} nhung that bai "
                f"({e}); len={len(raw)} B. Can khai bao dung hoac luu lai bang UTF-8 "
                "(fail-closed, khong doan tiep).")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")             # BOM = nguon tu khai bao
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")          # UTF-8 BOM: bo BOM, noi dung UTF-8
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit(
            "LOI decode: log khong phai UTF-8/UTF-16 co BOM (fail-closed). "
            f"len={len(raw)} B. Neu chac chan nguon la encoding khac, PHIEN chay "
            "PHAI KHAI BAO ro: `prepare --encoding <ten>` — tool khong tu doan "
            "cp1252 vi decode-duoc != dung-encoding.")


def _fix_mojibake(text: str) -> str:
    """Phuc hoi double-encoding DA BIET NGUON GOC: chuoi UTF-8 bi doc nham cp1252
    roi luu lai. Chi thu khi co marker dac trung; giu nguyen chuoi goc neu khong
    phuc hoi sach, TUYET DOI khong errors='ignore'."""
    try:
        if ("\u00c3" in text) or ("Ã¢" in text) or ("á»" in text):
            candidate = text.encode("cp1252").decode("utf-8")
            if "\ufffd" not in candidate:
                return candidate
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass  # giu nguyen chuoi goc — khong doan mo
    return text


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize_log(raw: bytes, declared_encoding: Optional[str] = None) -> str:
    """Doc log (PS 5.1 co the ghi UTF-16LE/UTF-8 BOM) fail-closed -> phuc hoi mojibake
    neu la double-encode DA CO MARKER dac trung -> sanitize duong dan.

    F3.2: pipeline chay DEN DIEM BAT (fixpoint, khong phai 1 luot qua) roi kiem tra
    fail-closed tren san pham: `_RE_LEAK` con khop nghia la van con leak ma bo regex
    KHONG phu duoc (vi du username sau 'path ') -> LOI, khong xuat evidence.
    F3.c: encoding khac UTF-8/BOM-UTF-16 chi duoc decode khi KHAI BAO ro qua
    `declared_encoding` (CLI `prepare --encoding`); khong tu doan cp1252.
    """
    text = _decode_strict(raw, declared_encoding)
    text = _fix_mojibake(text)
    for _ in range(6):
        nxt = sanitize_text(text)
        if nxt == text:
            break
        text = nxt
    else:
        raise SystemExit(
            "LOI sanitize: pipeline khong hoi tu sau 6 vong (log sai dinh dang?). "
            "Khong xuat evidence.")
    residual = _RE_LEAK.search(text)
    if residual:
        raise SystemExit(f"LOI sanitize: log van con leak khong phu duoc -> "
                         f"{residual.group(0)!r}. Khong xuat evidence (fail-closed).")
    return text


def build_sanitized_logs(write: bool = True,
                         declared_encoding: Optional[str] = None) -> list:
    """Sinh docs/sanitized_logs/*.sanitized tu log tho HIEN CO; loi neu mau sau
    sanitize van con duong dan/username (fail-closed).

    F3.1: `hash` (chi doc) goi voi write=False -> KHONG tao/sua file nao; thieu ban
    .sanitized thi bao loi yeu cau chay `prepare` truoc (khong tu sinh ngam).
    """
    out_dir = DOCS / SANITIZED_DIR
    made = []
    for name in SANITIZED_LOG_SOURCES:
        src = DOCS / name
        if not src.exists():
            src = ROOT / name  # cho phep log nam o thu muc goc (redirect cu)
        dst = out_dir / (name + ".sanitized")
        if not src.exists():
            if write:
                print(f"  bo qua (khong co log nguon): {name}")
            continue
        if not write:
            if not dst.is_file():
                raise SystemExit(
                    f"LOI: thieu {dst.relative_to(ROOT).as_posix()} — chay "
                    "`python scripts/hash_evidence.py prepare` truoc khi hash.")
            made.append(dst)
            continue
        clean = sanitize_log(src.read_bytes())  # fail-closed trong (F3.2)
        out_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(dst, clean)
        made.append(dst)
    return made


def _sanitize_json_value(v):
    if isinstance(v, str):
        return sanitize_text(v)
    if isinstance(v, list):
        return [_sanitize_json_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _sanitize_json_value(x) for k, x in v.items()}
    return v


def sanitize_json_text(text: str) -> str:
    """Sanitize JSON theo CAU TRUC (de quy moi chuoi gia tri — bat ke do sau long),
    khong regex tren toan van ban nen khong the lam huong cau truc JSON."""
    obj = json.loads(text)
    return json.dumps(_sanitize_json_value(obj), ensure_ascii=False, indent=2) + "\n"


# Member trong ZIP evidence ma KHONG phai van ban (anh/PDF/font...): duoc phep giu
# nguyen byte, KHONG decode. Moi duoi khac khong decode duoc UTF-8 -> FAIL (F3.3).
_BINARY_OK_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf", ".ttf",
                   ".otf", ".woff", ".woff2", ".ico", ".zip")


def _backup_original(path: Path) -> Optional[Path]:
    """Luu BAN GOC truoc khi sua (F3.4). Chi ghi lan dau -> khong ghi de ban goc that.
    Tra ve duong dan ban goc (hoac None neu khong sao luu duoc)."""
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return None
    dst = ORIGINALS_DIR / rel
    if dst.exists():
        return dst
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(path.read_bytes())
    except OSError:
        return None
    return dst


def is_temp_path(p: Path) -> bool:
    """File tam cua chinh tool (tmpXXXX.tmp) — khong bao gio dua vao evidence."""
    return bool(_TMP_NAME.match(p.name))


def cleanup_leftover_temps() -> list:
    """Don file tam con sot trong docs/ (F3.5). Tra ve danh sach da xoa."""
    removed = []
    for p in sorted(DOCS.rglob("tmp*")):
        if p.is_file() and is_temp_path(p):
            try:
                p.unlink()
                removed.append(p.relative_to(ROOT).as_posix())
            except OSError:
                pass
    return removed


def sanitize_zip_members(path: Path) -> bool:
    """Sanitize member van ban trong ZIP; co thay doi -> TAO LAI ZIP (CRC/central
    directory tinh lai tu dau) thay vi ghi de member trong cho. True neu doi.

    F3.3/F3.4: member khong decode duoc (va khong thuoc allowlist nhi phan) lam FAIL ro
    rang thay vi bo qua im lang; ban GOC duoc sao luu truoc khi thay ZIP; sau khi tao lai
    thi VALIDATE lai namelist + CRC + doc lai duoc JSON.
    """
    import tempfile
    changed = False
    with zipfile.ZipFile(path, "r") as zf:
        items = [(i, zf.read(i.filename)) for i in zf.infolist()]
    new_items = []
    for info, data in items:
        if Path(info.filename).suffix.lower() in _BINARY_OK_EXTS:
            new_items.append((info, data))       # nhi phan: giu nguyen byte (ghi ro)
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise SystemExit(
                f"LOI ZIP: member {info.filename!r} trong {path.name} khong phai UTF-8 "
                f"({e}); khong the xac minh -> KHONG tu y bo qua (fail-closed).")
        cleaned = (sanitize_json_text(text) if info.filename.endswith(".json")
                   else sanitize_text(text))
        if cleaned != text:
            changed = True
        new_items.append((info, cleaned.encode("utf-8")))
    if not changed:
        return False
    original = _backup_original(path)
    fd, tmp_name = tempfile.mkstemp(suffix=".zip", dir=str(path.parent))
    os.close(fd)                                  # F3.5: khong de fd mo
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for info, data in new_items:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.external_attr = info.external_attr
                zf.writestr(zi, data)
        _validate_rebuilt_zip(tmp, [i.filename for i, _ in items],
                              {i.filename: data for i, data in items})
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    if original is not None:
        print(f"  ban goc ZIP -> {original.relative_to(ROOT).as_posix()}")
    return True


def _validate_rebuilt_zip(tmp: Path, names: list, before: dict) -> None:
    """ZIP tao lai phai: cung danh sach member, CRC/doc lai duoc, va member NHI PHAN
    khong doi byte (member van ban chi duoc doi khi sanitize that su)."""
    with zipfile.ZipFile(tmp, "r") as zf:
        got = zf.namelist()
        if got != names:
            raise SystemExit(f"LOI ZIP: danh sach member khac sau khi tao lai: {got} != {names}")
        bad = zf.testzip()
        if bad is not None:
            raise SystemExit(f"LOI ZIP: CRC hong o member {bad} (central directory moi)")
        for name in got:
            data = zf.read(name)
            if Path(name).suffix.lower() in _BINARY_OK_EXTS and data != before.get(name):
                raise SystemExit(f"LOI ZIP: member nhi phan {name} bi thay doi byte")


def _atomic_write(p: Path, text: str) -> None:
    """Ghi nguyen tu: file tam -> replace. F3.5: DONG file descriptor ngay (ban cu de mo
    lam `replace` that bai tren Windows) va XOA temp trong MOI duong thoat."""
    import tempfile
    import time
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=str(p.parent))
    tmp = Path(tmp_name)
    try:
        # os.fdopen nhan quyen so huu fd -> dong khi ra khoi `with` (khong con fd mo).
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        last = None
        for _ in range(5):
            try:
                os.replace(tmp, p)
                return
            except PermissionError as e:
                last = e
                time.sleep(0.4)
        # Fallback: tien trinh khac giu handle cho-phep-GHI nhung khong cho DELETE
        # (os.replace can delete) -> ghi truc tiep tai cho (van encoding utf-8).
        try:
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e2:
            raise SystemExit(
                f"LOI ghi tai cho {p.name}: replace={last}; in-place={e2} "
                "(file bi khoa, khong ep ghi)")
    finally:
        try:
            tmp.unlink(missing_ok=True)      # temp cua CHINH thao tac nay, luon don
        except OSError:
            pass


def sanitize_docs_in_place() -> list:
    """Quet docs/ theo danh sach ghi ro: log tho + md/json/zip; file co leak ->
    sanitize tai cho (atomic). Tra ve danh sach file da doi (de log co duoc).

    F3.4: MOI file sap bi sua duoc sao ban GOC vao data/evidence_originals/ (ngoai
    docs/) truoc khi ghi — chi lan dau, khong ghi de ban goc da luu. F3.5: don file
    tam con sot sau khi quet.
    """
    touched = []
    for rel in _RAW_LOGS:
        p = DOCS / rel
        if not p.is_file():
            continue
        raw = p.read_bytes()
        try:
            old = raw.decode("utf-8")
        except UnicodeDecodeError:
            old = None
        clean = sanitize_log(raw)
        if old is None or clean != old:
            _backup_original(p)
            _atomic_write(p, clean)
            touched.append(rel)
    for pattern in SANITIZE_TEXT_GLOBS:
        for p in DOCS.glob(pattern):
            if not p.is_file():
                continue
            if p.suffix.lower() == ".zip":
                if sanitize_zip_members(p):
                    touched.append(p.relative_to(ROOT).as_posix())
                continue
            text = p.read_text(encoding="utf-8", errors="strict")
            if not _leak_count(text):
                continue
            cleaned = (sanitize_json_text(text) if p.suffix.lower() == ".json"
                       else sanitize_text(text))
            if cleaned != text:
                _backup_original(p)
                _atomic_write(p, cleaned)
                touched.append(p.relative_to(ROOT).as_posix())
    removed = cleanup_leftover_temps()
    if removed:
        print(f"don file tam trong docs/: {removed}")
    return touched


def _leak_count(text: str) -> int:
    """SO LUONG leak tinh tren BAN GOC (F3.2): san pham sau sanitize la `[PATH]`,
    khong con drive letter nen leak-check khong the chay tren ban da thay."""
    return len(_RE_LEAK.findall(text))


def has_raw_path_leak(text: str) -> bool:
    """FAIL-CLOSED check tren BAN GOC (F3.2): ban cu kiem tra chuoi DA SANITIZE —
    luc do drive letter da tro thanh `[PATH]` nen khong con leak nao bị phát hiện
    (xac minh bang smoke test truoc khi sua). Check tren ban goc bat lai ca leak
    ma sanitizer se thay, va van bo qua URL/LaTeX/relative-path (regex co ranh gioi)."""
    return bool(_RE_LEAK.search(text))


def _json_value_leak(obj, _top: bool = True) -> bool:
    """Kiem tra leak tren GIA TRI JSON DA DECODE (LaTeX '\\frac' trong file la
    escape 'okie', khong phai UNC) — value khong sach khi sanitize_text doi no."""
    if isinstance(obj, str):
        return sanitize_text(obj) != obj
    if isinstance(obj, list):
        return any(_json_value_leak(x) for x in obj)
    if isinstance(obj, dict):
        return any(_json_value_leak(x) for x in obj.values())
    return False


def validate_docs_clean() -> None:
    """FAIL-CLOSED tren residual leak: quet TOAN BO file van ban trong docs/
    (ke ca zip member). JSON duoc kiem tra theo GIA TRI DECODE ( tranh duong
    tinh gia voi LaTeX escape '\\\\frac' trong van ban tho); con 1 leak -> KHONG
    xuat manifest."""
    bad = []

    def check_json_text(text: str) -> Optional[bool]:
        try:
            return _json_value_leak(json.loads(text))
        except json.JSONDecodeError:
            return None  # khong phai JSON hop le -> de quy tac van ban

    for p in sorted(DOCS.rglob("*")):
        if not p.is_file():
            continue
        if is_temp_path(p):
            continue                       # file tam cua tool: khong phai evidence
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                for name in zf.namelist():
                    if Path(name).suffix.lower() in _BINARY_OK_EXTS:
                        continue           # nhi phan (anh/pdf/font): khong decode
                    try:
                        text = zf.read(name).decode("utf-8")
                    except UnicodeDecodeError as e:
                        # F3.3: khong decode duoc ma khong nam allowlist -> FAIL ro
                        # rang thay vi bo qua im lang (ban cu 'continue').
                        bad.append(f"{p.relative_to(ROOT).as_posix()}::{name} "
                                   f"(khong phai UTF-8: {e})")
                        continue
                    res = check_json_text(text) if name.endswith(".json") else None
                    if res is True or (res is None and _RE_LEAK.search(text)):
                        bad.append(f"{p.relative_to(ROOT).as_posix()}::{name}")
            continue
        if p.suffix.lower() not in _TEXT_EXTS:
            continue
        text = p.read_text(encoding="utf-8", errors="strict")
        res = check_json_text(text) if p.suffix.lower() == ".json" else None
        if res is True or (res is None and _RE_LEAK.search(text)):
            bad.append(p.relative_to(ROOT).as_posix())
    if bad:
        raise SystemExit(
            "LOI: docs/ van con duong dan/leak sau sanitize (fail-closed, khong xuat "
            f"manifest): {sorted(set(bad))}")


def _collect():
    """Lap danh sach file evidence (CHI DOC — F3.1: khong tao/sua file nao).
    Khong bat file tam; file thieu thi bo (manifest la 'chung minh ton tai')."""
    found = []
    for rel in EVIDENCE_PATTERNS:
        p = DOCS / rel
        if p.is_file():
            found.append(p)
    for d in EVIDENCE_DIRS:
        dd = DOCS / d
        if dd.exists():
            for p in sorted(dd.rglob("*")):
                if p.is_file():
                    found.append(p)
    # F3.1: khong tu sinh sanitized logs o day (do chi doc); chi them neu da co.
    out_dir = DOCS / SANITIZED_DIR
    if out_dir.is_dir():
        for name in SANITIZED_LOG_SOURCES:
            dst = out_dir / (name + ".sanitized")
            if dst.is_file():
                found.append(dst)
    # loai chinh file dau ra de khong tu hash
    return sorted(set(found), key=lambda x: str(x.relative_to(ROOT)))


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Bang chung artifact nghiem thu (F3: "
                                             "tach 'prepare' (ghi) va 'hash' (chi doc))")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("prepare", help="sanitize docs/ tai cho + sinh sanitized "
                                           "logs + don file tam (CO ghi doi file)")
    p_pre.add_argument("--out", default=None,
                       help="khong dung: 'prepare' khong xuat manifest (chay 'hash')")

    p_hash = sub.add_parser("hash", help="KIEM TRA fail-closed + xuat manifest — chi doc")
    p_hash.add_argument("--out", default=str(DOCS / "EVIDENCE_SNAPSHOT.sha256"))
    p_hash.add_argument("--verify", action="store_true",
                        help="khong ghi: chi kiem tra manifest hien tai (in OK/MISMATCH)")

    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        if args.out is not None:
            ap.error("'prepare' khong xuat manifest — chay 'hash' de xuat.")
        touched = sanitize_docs_in_place()
        print(f"sanitize tai cho: {len(touched)} file doi")
        for rel in touched:
            print(f"  - {rel}")
        made = build_sanitized_logs(write=True)
        print(f"sanitized logs: {len(made)} file")
        validate_docs_clean()
        print("validator: docs/ CLEAN (khong con leak)")
        print("OK: da chuan bi. Bay gio chay: python scripts/hash_evidence.py hash")
        return 0

    # --- hash: CHI DOC. Khong tao/sua file nao trong docs/ truoc khi hash. ---
    made = build_sanitized_logs(write=False)
    print(f"sanitized logs (da co san, khong sinh moi): {len(made)} file")
    validate_docs_clean()
    print("validator: docs/ CLEAN (khong con leak)")
    out = Path(args.out)
    files = [p for p in _collect() if p.resolve() != out.resolve()]
    lines = ["# Bang chung artifact nghiem thu — PDF Cleaner Tool",
             f"# {len(files)} file · sinh boi scripts/hash_evidence.py hash",
             "# Tham chieu MOT CHIEU toi SOURCE_SNAPSHOT.sha256 (neu co trong danh sach).",
             "# Khong chua config.json runtime / duong dan tuyet doi / secret."]
    combined = hashlib.sha256()
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        digest = _sha(p)
        lines.append(f"{digest}  {rel}")
        combined.update(rel.encode("utf-8")); combined.update(digest.encode("utf-8"))
    lines.append("")
    lines.append(f"AGGREGATE sha256 = {combined.hexdigest()}")
    if args.verify:
        if not out.is_file():
            raise SystemExit(f"VERIFY FAIL: khong ton tai manifest {out}")
        current = out.read_text(encoding="utf-8")
        expect = "\n".join(lines) + "\n"
        if current != expect:
            raise SystemExit("VERIFY MISMATCH: manifest khong khop trang thai docs/ "
                             "hien tai (dung 'hash' de tao lai SAU khi kiem tra thay doi).")
        print(f"VERIFY OK: {len(files)} file, AGGREGATE = {combined.hexdigest()}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(out, "\n".join(lines) + "\n")
    print(f"da ghi {len(files)} file -> {out}")
    print("AGGREGATE:", combined.hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
