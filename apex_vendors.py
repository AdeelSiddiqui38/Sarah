"""APEX vendor invoices: one Inbox for everything that arrives, then per-vendor / per-month folders.

Layout inside the APEX project folder (S:\\APEX Physio):
    Vendor Invoices\\Inbox                      <- drop or upload anything here (PDF, phone photo)
    Vendor Invoices\\<Vendor>\\<YYYY-MM>\\<date>_<vendor>_<amount>.<ext>

Sarah reads PDFs in the Inbox, guesses vendor / date / amount, and PROPOSES where each file goes. Nothing moves until
Adeel approves on the APEX Finance page. Files are only moved (never overwritten or deleted). Photos cannot be read, so
they wait in the Inbox for Adeel to pick the vendor.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from pdftext import pdf_text

DIRNAME = "Vendor Invoices"
INBOX = "Inbox"
EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp"}
MAX_UPLOAD = 25_000_000
VENDOR_DIR_OVERRIDE = os.environ.get("SARAH_APEX_VENDOR_DIR")   # NAS: writable mount of ...\APEX Physio\Vendor Invoices


def root(folder):
    return Path(VENDOR_DIR_OVERRIDE) if VENDOR_DIR_OVERRIDE else Path(folder) / DIRNAME


def inbox(folder):
    return root(folder) / INBOX


def _clean(s, n=60):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(s)).strip(" .")
    return re.sub(r"\s+", " ", s)[:n].strip()


def _vendors_file(ddir):
    return Path(ddir) / "apex-vendors.json" if ddir else None


def _known(folder, ddir):
    names = {}
    f = _vendors_file(ddir)
    if f and f.exists():
        try:
            for n, aliases in json.loads(f.read_text(encoding="utf-8")).get("vendors", {}).items():
                names[n] = list(aliases)
        except (OSError, ValueError):
            pass
    r = root(folder)
    if r.is_dir():
        for d in r.iterdir():
            if d.is_dir() and d.name != INBOX and not d.name.startswith((".", "_")):
                names.setdefault(d.name, [])
    return names


def _remember(ddir, vendor):
    f = _vendors_file(ddir)
    if not f:
        return
    try:
        cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        cur = {}
    cur.setdefault("vendors", {}).setdefault(vendor, [])
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(f) + ".tmp")
    tmp.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def _money(s):
    try:
        return round(float(s.replace(",", "")), 2)
    except ValueError:
        return None


def _total(text):
    vals = [_money(m.group(2)) for m in re.finditer(r"(?i)(total|amount due|balance due|grand total)[^\d$\n]{0,25}\$?\s*([\d,]+\.\d\d)", text)]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def _date(text):
    m = re.search(r"(?i)(?:invoice date|date)[:\s]+(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(?i)(?:invoice date|date)[:\s]+([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})", text)
    if m and m.group(1).lower() in _MONTHS:
        return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(?i)(?:invoice date|date)[:\s]+(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:   # Canadian invoices are usually D/M/Y or M/D/Y; only trust it when unambiguous
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            return f"{y:04d}-{b:02d}-{a:02d}"
        if b > 12 and a <= 12:
            return f"{y:04d}-{a:02d}-{b:02d}"
    return ""


def _guess_vendor(name, text, known):
    hay = (name + "\n" + text).lower()
    best = ""
    for v, aliases in known.items():
        for key in [v] + aliases:
            if key and key.lower() in hay and len(key) > len(best):
                best = v
    return best


def _fid(rel, size):
    return hashlib.sha1(f"{rel}|{size}".encode()).hexdigest()[:12]


def scan_inbox(folder, ddir=None):
    """Everything waiting in the Inbox, with Sarah's guess for each file (nothing is moved)."""
    ib = inbox(folder)
    known = _known(folder, ddir)
    out = []
    if not ib.is_dir():
        return out
    for f in sorted(ib.iterdir()):
        if not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in EXTS:
            continue
        st = f.stat()
        text = ""
        if f.suffix.lower() == ".pdf":
            try:
                text = pdf_text(str(f))
            except Exception:  # noqa: BLE001
                text = ""
        out.append({"id": _fid(f.name, st.st_size), "file": f.name, "kind": "pdf" if f.suffix.lower() == ".pdf" else "photo",
                    "vendor": _guess_vendor(f.name, text, known), "date": _date(text) or dt.date.fromtimestamp(st.st_mtime).isoformat(),
                    "date_from_file": not _date(text), "total": _total(text), "readable": bool(text.strip()),
                    "received": dt.date.fromtimestamp(st.st_mtime).isoformat()})
    return out


def vendor_list(folder, ddir=None):
    r = root(folder)
    rows = []
    if r.is_dir():
        for d in sorted(r.iterdir()):
            if d.is_dir() and d.name != INBOX and not d.name.startswith((".", "_")):
                files = [x for x in d.rglob("*") if x.is_file() and x.suffix.lower() in EXTS]
                latest = max((x.parent.name for x in files), default="")
                rows.append({"vendor": d.name, "files": len(files), "latest": latest})
    return rows


def overview(folder, ddir=None):
    return {"inbox": scan_inbox(folder, ddir), "vendors": vendor_list(folder, ddir), "known": sorted(_known(folder, ddir)),
            "path": f"{DIRNAME}\\{INBOX}"}


def _unique(path):
    if not path.exists():
        return path
    i = 2
    while True:
        p = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not p.exists():
            return p
        i += 1


def file_invoices(folder, items, ddir=None):
    """items: [{id, vendor, date?}]. Moves each approved Inbox file into <Vendor>/<YYYY-MM>/. Returns how many moved."""
    by_id = {p["id"]: p for p in scan_inbox(folder, ddir)}
    ib, n = inbox(folder), 0
    for it in items:
        p = by_id.get(it.get("id"))
        vendor = _clean(it.get("vendor", ""))
        if not p or not vendor:
            continue
        date = it.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(it.get("date", ""))) else p["date"]
        src = ib / p["file"]
        tot = f"{p['total']:.2f}" if p["total"] is not None else "amount-unknown"
        dest_dir = root(folder) / vendor / date[:7]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique(dest_dir / (_clean(f"{date}_{vendor}_{tot}", 120).replace(" ", "-") + src.suffix.lower()))
        shutil.move(str(src), str(dest))
        _remember(ddir, vendor)
        n += 1
    return n


def save_upload(folder, name, b64):
    ext = Path(str(name)).suffix.lower()
    if ext not in EXTS:
        raise ValueError("Only PDF or photo files (jpg, png, heic, webp).")
    data = base64.b64decode(b64, validate=False)
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("File is empty or larger than 25 MB.")
    ib = inbox(folder)
    ib.mkdir(parents=True, exist_ok=True)
    stem = _clean(Path(str(name)).stem, 80) or "invoice"
    dest = _unique(ib / (stem + ext))
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest.name
