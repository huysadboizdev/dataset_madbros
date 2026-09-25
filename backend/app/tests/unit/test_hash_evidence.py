"""F3 — hash_evidence: TACH 'prepare' (ghi) va 'hash' (chi doc) + regex KHONG pha
URL/LaTeX + fail-closed ZIP/username + file tam khong roi vao evidence.

Cach viet: FIXTURE tai lap trang thai loi (log co duong dan that, ZIP co member lech,
username trong log) -> chay ham -> khang dinh dung/FAIL ro rang; them 1 test tren
data that (B3 page 7 + ZIP B4) de khoa bang chung voi du lieu that.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

_spec = importlib.util.spec_from_file_location(
    "hash_evidence", ROOT / "scripts" / "hash_evidence.py")
he = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("hash_evidence", he)
_spec.loader.exec_module(he)


# ---------------------------------------------------------------- fixtures --

@pytest.fixture()
def fake_docs(tmp_path, monkeypatch):
    """docs/ gia lap: redirect ROOT cua module vao tmp de khong dong den docs/ that."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(he, "ROOT", tmp_path, raising=False)
    monkeypatch.setattr(he, "DOCS", docs, raising=False)
    monkeypatch.setattr(he, "ORIGINALS_DIR", tmp_path / "data" / "evidence_originals",
                        raising=False)
    return docs


# ------------------------------------------------- F3.2 regex: khong pha URL --

def test_sanitize_keeps_urls_and_relative_paths():
    """Loi that da xay ra: `https://...` -> `http[PATH]` (regex cu gap `s:/`)."""
    url = "xem https://paddlepaddle.org.cn/docs/install/v2.6/doc?p=1&q=2"
    out = he.sanitize_text(url)
    assert out == url, "URL phai giu nguyen nguyen van"
    rel = "docs/benchmark_dump/page_0007_blocks.json"
    assert he.sanitize_text(rel) == rel
    assert not he.has_raw_path_leak(url)


def test_sanitize_keeps_latex_and_still_masks_real_paths():
    latex = r"\\frac{a}{b} + \\sqrt{x}"
    assert he.sanitize_text(latex) == latex, "LaTeX \\frac khong duoc nham UNC"
    masked = he.sanitize_text(r"log tai C:\Users\Huy\AppData\Local\Temp\tmpabc.tmp xong")
    assert r"C:\Users" not in masked and "[PATH]" in masked
    masked_unc = he.sanitize_text(r"\\SRV01\share\data\book.pdf")
    assert "SRV01" not in masked_unc and "[PATH]" in masked_unc


@pytest.mark.parametrize("path_like", [
    r"C:\Users\Huy\report.pdf",          # Windows backslash
    "C:/Users/Huy/report.pdf",          # Windows forward slash
    r"\\SRV01\share\data\book.pdf",     # UNC
    "/home/huy/Documents/x.md",         # POSIX home
    "/Users/Huy/Desktop/x.md",          # macOS-style users
    "~/Desktop/secret.txt",             # home tilde
    "/var/log/app.log",                 # POSIX var
])
def test_sanitize_masks_all_absolute_path_flavors(path_like):
    """F3(b): Windows/UNC/POSIX path TUYET doi phai bi mask — khong phai chi Win."""
    out = he.sanitize_text(f"chay tai {path_like} xong")
    assert "[PATH]" in out
    assert not he.has_raw_path_leak(out)
    assert path_like not in out


def test_sanitize_keeps_http_lowercase_url_variant():
    """Counterexample cu trong audit: `http://example.com/x` -> `htt[PATH]`.
    Regex phai giu nguyen ca `http://` lan `https://`."""
    for url in ("http://example.com/x", "https://example.com/a",
                "see http://a.b/c?d=e&f=g#h for details"):
        assert he.sanitize_text(url) == url
        assert not he.has_raw_path_leak(url)


def test_leak_check_runs_on_raw_text():
    """F3.2 chot: san pham sau sanitize la `[PATH]` nen leak-check phai thay leak
    tren BAN GOC — ban cu check sau-thay thi khong bao gio bat duoc drive letter."""
    raw = "run tai C:\\Users\\Huy\\AppData\\Local\\Temp\\x.png xong"
    assert he.has_raw_path_leak(raw)
    assert not he.has_raw_path_leak(he.sanitize_text(raw))  # san pham sach


def test_leak_check_ignores_home_substring_inside_url():
    """F3(b): `https://site/home/x` khong phai duong dan — leak-check co ranh gioi
    tuong tu sanitize, khong fail-closed nham URL chua '/home/'."""
    assert not he.has_raw_path_leak("doc tai https://paddlepaddle.org.cn/home/x")
    assert he.has_raw_path_leak("file /home/huy/secrets.env bi lo")


# ------------------------------------------- F3(c) decode: KHONG doan cp1252 --

def test_decode_strict_rejects_undeclared_cp1252_guess():
    """F3(c): decode duoc khong chang minh encoding nguon la cp1252. Ban cu thu
    cp1252 cho MOI byte khong UTF-8 -> phai bo; chi nhan khi co khai bao ro rang."""
    raw = "café log".encode("cp1252")          # 'é' = 0xE9 -> khong hop le UTF-8
    with pytest.raises(SystemExit, match="khai bao"):
        he._decode_strict(raw)


def test_decode_strict_accepts_declared_encoding_and_explicit_bom():
    """UTF-8 strict, UTF-16 co BOM (tin hieu ro), hoac encoding DUOC KHAI BAO thi
    decode strict theo khai bao; sai khai bao -> FAIL, khong doan tiep."""
    assert he._decode_strict("xong".encode("utf-8")) == "xong"
    assert he._decode_strict("xong ✓".encode("utf-16")) == "xong ✓"  # BOM = khai bao
    assert he._decode_strict("café log".encode("cp1252"),
                             declared_encoding="cp1252") == "café log"
    with pytest.raises(SystemExit, match="khai bao"):
        he._decode_strict("café".encode("utf-16-le"), declared_encoding="utf-8")


def test_sanitize_log_requires_declaration_for_non_utf8():
    raw = ("café chay C:\\Users\\Huy\\a.pdf xong").encode("cp1252")
    with pytest.raises(SystemExit, match="khai bao"):
        he.sanitize_log(raw)
    out = he.sanitize_log(raw, declared_encoding="cp1252")
    assert "[PATH]" in out and "café" in out


def test_vietnamese_text_with_colon_backslash_not_masked():
    """Loi tim thay that tren data: lookbehind ASCII lam hong tieng Viet —
    'sau đây:\\na)' bi nhan nham `y:\\` vi 'â' (U+00E2) khong thuoc [A-Za-z0-9_]."""
    vn = "Tim bất phương trình bậc nhất hai ẩn sau đây:\\na) $ x - 5y + 2 \\\\leq 0 $"
    assert he.sanitize_text(vn) == vn, "van ban tieng Viet + LaTeX phai giu nguyen"
    assert not he.has_raw_path_leak(vn)


# --------------------------------------------- F3.2 sanitize_log fail-closed --

def test_sanitize_log_fixpoint_and_fail_closed():
    log = b"bat dau\nrun tai C:\\Users\\Huy\\AppData\\Local\\Temp\\t.tmp xong\nOK"
    out = he.sanitize_log(log)
    assert "C:\\Users" not in out and "[PATH]" in out
    # username 'trong tu do' ma sanitizer khong phu duoc -> PHAI LOI (khong xuat)
    with pytest.raises(SystemExit, match="fail-closed"):
        he.sanitize_log(b"path Huy trong log (khong phai duong dan)")


# ------------------------------------------------ F3.1 hash khong ghi file --

def test_hash_mode_is_read_only(fake_docs):
    """'hash' KHONG duoc tao/sua file: log tho co leak nhung khong co .sanitized ->
    LOI yeu cau 'prepare', va khong bat ky file nao duoc tao."""
    (fake_docs / "formula_run0915.log").write_text(
        "run C:\\Users\\Huy\\x.png", encoding="utf-8")
    before = sorted(str(p.relative_to(fake_docs)) for p in fake_docs.rglob("*"))
    with pytest.raises(SystemExit, match="prepare"):
        he.build_sanitized_logs(write=False)
    after = sorted(str(p.relative_to(fake_docs)) for p in fake_docs.rglob("*"))
    assert before == after, "che do 'hash' (write=False) phai chi doc"


def test_hash_cli_is_byte_for_byte_read_only(fake_docs, tmp_path):
    """F3(a)/(f) chot: sau khi prepare, lenh `hash` (va `hash --verify`) KHONG duoc
    doi BAT KY BYTE nao cua input — so sánh toan bo tree docs/ truoc va sau."""
    (fake_docs / "formula_run0915.log").write_text(
        "run C:\\Users\\Huy\\x.png", encoding="utf-8")
    assert he.main(["prepare"]) == 0

    def snap():
        return {str(p.relative_to(fake_docs)): p.read_bytes()
                for p in sorted(fake_docs.rglob("*")) if p.is_file()}

    before = snap()
    assert before, "can co file trong docs/ gia lap de so sanh co y nghia"
    manifest = tmp_path / "out" / "EVIDENCE_SNAPSHOT.sha256"
    assert he.main(["hash", "--out", str(manifest)]) == 0
    assert snap() == before, "'hash' lam thay doi byte input (fail F3.a)"
    assert manifest.is_file()
    assert he.main(["hash", "--out", str(manifest), "--verify"]) == 0
    assert snap() == before, "'hash --verify' lam thay doi byte input (fail F3.a)"


def test_prepare_then_collect_includes_sanitized_logs(fake_docs):
    """'prepare' sinh ban .sanitized; _collect (dung boi 'hash') phai NHA CHUNG vao
    manifest — khong con 'hash' tu sinh ngam nhu ban cu."""
    (fake_docs / "formula_run0915.log").write_text(
        "run C:\\Users\\Huy\\x.png", encoding="utf-8")
    made = he.build_sanitized_logs(write=True)
    assert made and all(p.is_file() for p in made)
    made2 = he.build_sanitized_logs(write=False)   # chi doc lan 2: khong sinh moi
    assert [p.name for p in made] == [p.name for p in made2]
    collected = {p.name for p in he._collect()}
    assert "formula_run0915.log.sanitized" in collected


def test_temp_files_never_enter_manifest(fake_docs):
    """F3.5: file tam cua tool (tmp*.tmp) phai bo qua: khong vao manifest, bi don."""
    (fake_docs / "tmp0vumg5bf.tmp").write_text("C:\\Users\\Huy\\leak.png", encoding="utf-8")
    assert he.is_temp_path(fake_docs / "tmp0vumg5bf.tmp")
    removed = he.cleanup_leftover_temps()
    assert removed == ["docs/tmp0vumg5bf.tmp"]
    assert not (fake_docs / "tmp0vumg5bf.tmp").exists()


# ------------------------------------------ F3.3/F3.4 ZIP fail-closed + goc --

def _mk_zip(path: Path, members: dict) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_zip_binary_member_kept_text_member_sanitized(fake_docs):
    z = fake_docs / "e2e_real_export.zip"
    png = bytes(range(256))                      # member nhi phan bat ky
    _mk_zip(z, {"content.json": json.dumps({"cmd": r"C:\Users\Huy\a.png"}).encode(),
                "img/page.png": png})
    assert he.sanitize_zip_members(z) is True
    with zipfile.ZipFile(z) as zf:
        assert zf.testzip() is None, "CRC/central directory phai hop le sau tao lai"
        assert json.loads(zf.read("content.json"))["cmd"] == "[PATH]"
        assert zf.read("img/page.png") == png, "member nhi phan phai giu nguyen byte"
    original = he.ORIGINALS_DIR / "docs" / z.name   # ban goc de NGOAI docs/
    assert original.is_file()
    with zipfile.ZipFile(original) as zf:
        assert json.loads(zf.read("content.json"))["cmd"] == r"C:\Users\Huy\a.png"


def test_zip_undecodable_member_fails_closed(fake_docs):
    """F3.3: member khong decode duoc + khong nam allowlist nhi phan -> LOI ro rang,
    khong im lang bo qua (ban cu 'continue')."""
    z = fake_docs / "e2e_real_export.zip"
    _mk_zip(z, {"data.bin": b"\x00\xff\xfe\x80\x81"})
    with pytest.raises(SystemExit, match="fail-closed"):
        he.sanitize_zip_members(z)


def test_validate_docs_clean_zip_fail_closed(fake_docs):
    z = fake_docs / "x.zip"
    _mk_zip(z, {"data.bin": b"\x00\xff\xfe\x80\x81"})
    with pytest.raises(SystemExit, match="khong phai UTF-8"):
        he.validate_docs_clean()


def test_zip_rebuild_preserves_member_names_and_order(fake_docs):
    """F3(d)/(f): ZIP tao lai phai giu DUNG ten + thu tu member, CRC tinh lai hop le."""
    names = ["z.txt", "a.json", "img/x.png"]
    z = fake_docs / "e2e_real_export.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("z.txt", "see C:\\Users\\Huy\\a".encode("utf-8"))
        zf.writestr("a.json", json.dumps({"p": "C:\\Users\\Huy\\b"}).encode("utf-8"))
        zf.writestr("img/x.png", b"\x89PNG\x00\xff\x01")
    assert he.sanitize_zip_members(z) is True
    with zipfile.ZipFile(z) as zf:
        assert zf.namelist() == names, "member/ thu tu thay doi sau rebuild"
        assert zf.testzip() is None


# ---------------- validator scope: docs/ van ban LOAI tru directory van-hanh --

def test_validator_skips_non_evidence_ops_dir_but_blocks_plain_file(fake_docs):
    """F3 bao dong can thiet: `docs/plans/**` (roadmap/SOP van-hanh, KHONG thuoc
    EVIDENCE_PATTERNS) co the chua duong dan may local — validator khong chan;
    nhung file van ban KHAC duoi docs/ van phai clean (fail-closed)."""
    plans = fake_docs / "plans"
    plans.mkdir()
    (plans / "roadmap.md").write_text("venv tai D:\\OCR_Local\\.venv313",
                                      encoding="utf-8")
    assert "plans" in he.NON_EVIDENCE_SUBDIRS
    he.validate_docs_clean()                      # khong duoc noi
    (fake_docs / "notes.md").write_text("doc tai D:\\OCR_Local\\y", encoding="utf-8")
    with pytest.raises(SystemExit, match="notes.md"):
        he.validate_docs_clean()


def test_evidence_file_in_excluded_dir_is_still_validated(fake_docs, monkeypatch):
    """Union guard: file nam TRONG dir duoc mien khai but bi them vao
    EVIDENCE_PATTERNS thi validator VAN bat buoc sach — mien khai khong phai ao che."""
    plans = fake_docs / "plans"
    plans.mkdir()
    (plans / "tracked.md").write_text("nhay C:\\Users\\Huy\\z", encoding="utf-8")
    monkeypatch.setattr(he, "EVIDENCE_PATTERNS",
                        list(he.EVIDENCE_PATTERNS) + ["plans/tracked.md"])
    with pytest.raises(SystemExit, match="tracked.md"):
        he.validate_docs_clean()


def test_validator_non_utf8_text_file_fails_with_named_error(fake_docs):
    """F3(c): file van ban khong decode duoc UTF-8 -> FAIL CO TEN FILE, khong crash
    traceback tho (ban cu UnicodeDecodeError noi len khong chi ro dang kiem gi)."""
    (fake_docs / "broken.md").write_bytes(b"\x81\xfe kai \xc3\x28 khong hop le")
    with pytest.raises(SystemExit, match="broken.md"):
        he.validate_docs_clean()


# --------------------------------------- JSON long: chi mask gia tri duong dan --

def test_sanitize_json_text_nested_multilevel_values_only():
    """F3(f): JSON nhieu tang dict/list long nhau — moi chuoi GIA TRI duong dan bi
    mask, cau truc + URL + relative path + LaTeX escape + ten nguyen van GIU NGUYEN."""
    obj = {"a": [{"b": {"c": r"open C:\Users\Huy\f.pdf and docs/x.md "
                        r"and https://e.com/y"}}],
           "tex": r"\frac{a}{b} \\sqrt{x}",
           "name": "Huy"}
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    out = he.sanitize_json_text(text)
    got = json.loads(out)
    assert got["a"][0]["b"]["c"] == ("open [PATH] and docs/x.md and https://e.com/y")
    assert got["tex"] == r"\frac{a}{b} \\sqrt{x}", "LaTeX escape trong JSON khong bi nao"
    assert got["name"] == "Huy", "json sanitize chi mask duong dan, khong mask ten tran"
    assert out.endswith("\n")


def test_json_value_leak_detects_nested_paths_not_latex_or_url():
    assert he._json_value_leak({"d": {"l": ["tai C:\\Users\\Huy\\q"]}})
    assert not he._json_value_leak({"tex": "\\frac{a}{b} \\\\sqrt{x}"})
    assert not he._json_value_leak({"url": "https://example.com/home/x",
                                    "rel": "docs/a.md"})


# --------------------------------------- _atomic_write: fd dong + tam don sach --

def test_atomic_write_closes_fd_and_leaves_no_temp(fake_docs):
    target = fake_docs / "out.json"
    he._atomic_write(target, '{"a": 1}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'
    leftovers = [p.name for p in fake_docs.iterdir() if p.name != "out.json"]
    assert leftovers == [], f"khong duoc de lai file tam: {leftovers}"


# --------------------------------------- test tren data evidence THAT (docs/) --

def test_real_evidence_b3_has_skipped_visual_and_b4_does_not():
    """F4/F3 khoa bang chung: B3 trang 7 co block skipped_visual (text=null, bbox);
    ZIP B4 KHONG co block skipped_visual nao. Neu data doi, test phai doi theo —
    khong duoc mo ta evidence khac voi thuc te."""
    b3 = json.loads((ROOT / "docs" / "benchmark_dump" / "page_0007_blocks.json")
                    .read_text(encoding="utf-8"))
    blocks = b3 if isinstance(b3, list) else b3.get("blocks", [])
    sv = [b for b in blocks if str(b.get("type", "")).endswith("skipped_visual")]
    assert sv, "B3 page 7 phai con block skipped_visual (bang chung P14)"
    assert all(b.get("text") in (None, "") for b in sv)
    with zipfile.ZipFile(ROOT / "docs" / "e2e_real_export.zip") as zf:
        content = json.loads(zf.read("content.json").decode("utf-8"))
    for page in content.get("pages", []):
        assert not [b for b in page.get("blocks", [])
                    if str(b.get("type", "")).endswith("skipped_visual")], \
            "ZIP B4 khong duoc dung lam bang chung skipped_visual (khong co block nay)"


def test_real_docs_have_no_unmasked_drive_paths():
    """Toan bo van ban docs/ THAT (md/json/log): khong con duong dan drive/UNC chua
    duoc mask — check tren ban goc (has_raw_path_leak), file nhi phan bo qua.
    Pham vi = giong het validator: dir van-hanh NON_EVIDENCE (docs/plans/) duoc mien
    TRU khi no nam trong EVIDENCE_PATTERNS (union guard duoc kiem o test gia lap)."""
    docs_dir = ROOT / "docs"
    evidence = {str(p.resolve()) for p in he._collect()}
    bad = []
    for p in sorted(docs_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in he._TEXT_EXTS:
            continue
        parts = p.relative_to(docs_dir).parts
        if (len(parts) > 1 and parts[0] in he.NON_EVIDENCE_SUBDIRS
                and str(p.resolve()) not in evidence):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            bad.append(f"{p.name} (khong phai UTF-8)")
            continue
        if he.has_raw_path_leak(text):
            bad.append(p.name)
    assert not bad, f"docs/ con leak: {bad}"