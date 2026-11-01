"""Invoice <-> payment matching for the Remedy Ledger.
Rule: the bank line is the expense (counted once); the invoice is its supporting record.
Matches e-transfers sent to invoices by amount (within $1) and date, flags small differences,
lists invoices with no payment and payments with no invoice, and fixes the category of matched lines."""
import datetime as dt
import json
import re
import zipfile
from pathlib import Path

from pdftext import pdf_text

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
VENDOR_CATEGORY = {  # folder name -> ledger category for matched payments
    "Pharmacist - Nayel Anwer": "Wages - Nayel (Pharmacist)",
    "Kharb": "Delivery - Kharb (Rx delivery)",
}
# Name found in a bank line -> category (applies to every matching line, e.g. regular store supplies)
DESC_RULES = {"THREE-ONE": "Store supplies"}
DESC_HINT = {"NAYEL": "Pharmacist - Nayel Anwer", "KHARB": "Kharb"}
TOL = 1.00          # dollars: still a match, but flagged
WINDOW = (-3, 60)   # payment may be this many days before .. after the invoice date


def _money(s):
    return float(s.replace(",", ""))


def _docx_text(p):
    x = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8", "ignore")
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", x))


def _end_date_from_name(name, year):
    """'INVOICE RPP (Oct. 13 - Oct. 17)' -> last 'Mon. DD' in the brackets; 'Jan. 26 - 31' -> Jan 31."""
    m = re.search(r"\(([^)]*)\)", name)
    seg = m.group(1) if m else name
    toks = re.findall(r"([A-Za-z]{3,5})\.?\s*(\d{1,2})", seg)
    mon = None
    day = None
    for a, b in toks:
        if a[:3].lower() in MONTHS:
            mon, day = MONTHS[a[:3].lower()], int(b)
    if mon is None:
        return None
    tail = re.search(r"-\s*(\d{1,2})\s*\)?\s*$", seg)
    if tail and not re.search(r"-\s*[A-Za-z]", seg):
        day = int(tail.group(1))
    try:
        return dt.date(year, mon, day)
    except ValueError:
        return None


def read_invoice(p, vendor):
    """Return dict(vendor,file,total,date,no) or None when nothing usable was found."""
    p = Path(p)
    try:
        if p.suffix.lower() == ".docx":
            t = _docx_text(p)
            c = re.sub(r"\s+", "", t)
            tot = re.findall(r"Total\$?([\d,]+(?:\.\d+)?)", c)
            if not tot:
                return None
            y = re.findall(r",\s*(20\d\d)", t)
            d = _end_date_from_name(p.stem, int(y[-1]) if y else dt.date.fromtimestamp(p.stat().st_mtime).year)
            if d is None and not y:
                return None
            return {"vendor": vendor, "file": p.name, "total": round(_money(tot[-1]), 2), "date": d.isoformat() if d else None, "no": ""}
        if p.suffix.lower() == ".pdf":
            c = re.sub(r"\s+", "", pdf_text(p))
            tot = re.findall(r"(?:Total|AmountDue|BalanceDue)\$?([\d,]+\.\d\d)", c, re.I)
            d = re.findall(r"(?:Invoicedate|Date):?(\d{4}-\d\d-\d\d)", c, re.I)
            n = re.findall(r"Invoice(?:no\.?|#|number):?(\w+)", c, re.I)
            if not tot:
                return None
            return {"vendor": vendor, "file": p.name, "total": round(_money(tot[-1]), 2), "date": d[0] if d else None, "no": n[0] if n else ""}
    except (OSError, zipfile.BadZipFile, ValueError, KeyError):
        return None
    return None


def scan_invoices(root):
    """Walk Invoices/<vendor>[/<sub>]; ignore folders starting with '_'. Returns (invoices, unreadable)."""
    root = Path(root)
    found, skipped, seen = [], [], set()
    if not root.is_dir():
        return found, skipped
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        folders = [(d, d.name)] if d.name != "One-time" else [(s, "One-time/" + s.name) for s in sorted(d.iterdir()) if s.is_dir()]
        for folder, vendor in folders:
            for f in sorted(folder.iterdir()):
                if f.suffix.lower() not in (".docx", ".pdf"):
                    continue
                inv = read_invoice(f, vendor)
                if not inv or not inv["date"]:
                    skipped.append(f"{vendor}/{f.name}")
                    continue
                k = (vendor, inv["total"], inv["date"], inv["no"])
                if k in seen:
                    continue
                seen.add(k)
                found.append(inv)
    return found, skipped


def desc_key(date, desc, amount):
    a = int(amount) if float(amount).is_integer() else amount
    return f"{date}|{desc}|{a}".lower()


def is_sent_transfer(r):
    s = r.get("desc", "").upper().replace(" ", "")
    return r.get("amount", 0) < 0 and (r.get("acct") or "Chequing") == "Chequing" and "INTERAC" in s and "SENT" in s


def match(invoices, rows, today=None):
    today = today or dt.date.today()
    pays = [r for r in rows if is_sent_transfer(r)]
    pairs = []
    for i, inv in enumerate(invoices):
        idate = dt.date.fromisoformat(inv["date"])
        for j, r in enumerate(pays):
            delta = round(abs(-r["amount"] - inv["total"]), 2)
            if delta > TOL:
                continue
            days = (dt.date.fromisoformat(r["date"]) - idate).days
            if not WINDOW[0] <= days <= WINDOW[1]:
                continue
            hint = next((v for k, v in DESC_HINT.items() if k in r["desc"].upper()), None)
            if hint and hint != inv["vendor"]:
                continue
            pairs.append((delta, abs(days), i, j))
    pairs.sort()
    used_i, used_j, matches = set(), set(), []
    for delta, _, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        r, inv = pays[j], invoices[i]
        matches.append({"date": r["date"], "paid": -r["amount"], "desc": r["desc"], "key": desc_key(r["date"], r["desc"], r["amount"]),
                        "category": r.get("category"), "vendor": inv["vendor"], "file": inv["file"], "invoice": inv["total"],
                        "invoice_date": inv["date"], "diff": round(-r["amount"] - inv["total"], 2)})
    # Owner rule: every Nayel payment is against a valid invoice even when the invoice email is gone,
    # so old unmatched Nayel invoices / unmatched Nayel payments are not problems (recent invoices still are).
    def old_nayel(inv):
        return inv["vendor"] == "Pharmacist - Nayel Anwer" and (today - dt.date.fromisoformat(inv["date"])).days > 30
    unpaid = [inv for i, inv in enumerate(invoices) if i not in used_i and (today - dt.date.fromisoformat(inv["date"])).days > 14 and not old_nayel(inv)]
    # payments that look like vendor payments but have no invoice
    names = tuple(DESC_HINT)
    def other_name(desc):
        tail = re.split(r"SENT", desc.upper().replace(" ", ""), maxsplit=1)[-1]
        tail = re.sub(r"\d.*$", "", tail)
        return bool(re.search(r"[A-Z]{3}", tail)) and "NAYEL" not in tail

    def accepted(r):  # unnamed or Nayel e-transfer filed as Nayel wages
        return r.get("category", "").startswith("Wages - Nayel") and not other_name(r["desc"])
    nomatch = [{"date": r["date"], "paid": -r["amount"], "desc": r["desc"], "category": r.get("category")}
               for j, r in enumerate(pays) if j not in used_j and not accepted(r) and (r.get("category", "").startswith(("Wages - Nayel", "Delivery - Kharb")) or any(n in r["desc"].upper() for n in names))]
    return {"matches": sorted(matches, key=lambda m: m["date"]), "unpaid": sorted(unpaid, key=lambda m: m["date"]),
            "no_invoice": sorted(nomatch, key=lambda m: m["date"])}


def category_fixes(result, overrides):
    """Overrides for matched lines whose category differs; never touches a line the owner already changed by hand."""
    fixes = {}
    for m in result["matches"]:
        want = VENDOR_CATEGORY.get(m["vendor"])
        if want and m["category"] != want and m["key"] not in overrides:
            fixes[m["key"]] = want
    return fixes


def rule_fixes(rows, overrides):
    """Category rules by name in the bank line; never touches a line the owner already changed by hand."""
    out = {}
    for r in rows:
        s = r.get("desc", "").upper().replace(" ", "")
        for name, cat in DESC_RULES.items():
            if name in s and r.get("category") != cat:
                k = desc_key(r["date"], r["desc"], r["amount"])
                if k not in overrides:
                    out[k] = cat
    return out


def seed_rows(html_path):
    h = Path(html_path).read_text(encoding="utf-8", errors="replace")
    i = h.find("window.SEED_DATA = ")
    if i < 0:
        return []
    obj, _ = json.JSONDecoder().raw_decode(h[i + len("window.SEED_DATA = "):])
    return obj.get("txns", [])
