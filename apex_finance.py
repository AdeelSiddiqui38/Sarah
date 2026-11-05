"""APEX Physio finance for Sarah: reads the Cost Controller workbook (Excel stays the master), reads BMO statements and
invoices, and proposes ledger rows for Adeel to approve. Dependency-free (stdlib only). Nothing here sends, pays or
edits the workbook: approved rows go to a small JSON file next to the statements, and merge_to_excel.py folds them into
the workbook on the PC when Adeel asks.

Layout (project folder = S:\\APEX Physio):
  Finance/APEX_PHYSIO_Cost_Controller.xlsx       master workbook (read-only for Sarah)
  Finance/BMO Bank Doc/Bank Statement/*.pdf      "Holco ..." = HoldCo, "OpCo ..." = OpCo
  Finance/Sarah Data/apex-ledger-inbox.json      proposed rows (waiting for approval)
  Finance/Sarah Data/apex-ledger-adds.json       approved / rejected rows
"""
import datetime as dt
import hashlib
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import apex_vendors

try:  # in the container pdftext.py sits next to this file
    from pdftext import pdf_text
except Exception:  # noqa: BLE001
    def pdf_text(_p):  # type: ignore
        return ""

WORKBOOK = "APEX_PHYSIO_Cost_Controller.xlsx"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
IN_TYPES = {"Capital-In", "Income", "Loan-In"}
OUT_TYPES = {"Expense", "Purchase", "Reimbursement", "Loan-Repay"}
BANK_ACCOUNTS = ("HoldCo", "OpCo", "Trust")      # accounts that count as cash (as in the workbook)
TOL = 1.00


# ---------------------------------------------------------------- xlsx reader (no openpyxl in the container)
def _col(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return m.group(1), int(m.group(2))


def read_xlsx(path):
    """{sheet name: {(row, 'A'): value}} using the stored values (formula cells without a stored value are None)."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for s in wb.find(NS + "sheets"):
        target = rels[s.get(RNS + "id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        cells = {}
        for c in ET.fromstring(z.read(target)).iter(NS + "c"):
            col, row = _col(c.get("r"))
            t = c.get("t")
            v = c.find(NS + "v")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(NS + "t"))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                val = shared[int(v.text)]
            elif t in ("str", "e"):
                val = v.text
            elif t == "b":
                val = bool(int(v.text))
            else:
                val = float(v.text)
            cells[(row, col)] = val
        out[s.get("name")] = cells
    return out


def _date(v):
    if isinstance(v, (int, float)):
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
        return v[:10]
    return None


def _num(v):
    return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _txt(v):
    return "" if v is None else (str(int(v)) if isinstance(v, float) and v == int(v) else str(v))


# ---------------------------------------------------------------- paths
def finance_dir(folder):
    return Path(folder) / "Finance"


def data_dir(folder, override=None):
    return Path(override) if override else finance_dir(folder) / "Sarah Data"


def settings(folder, ddir=None):
    """apex-settings.json in Sarah Data. HoldCo is dormant by default: the shop is bought and its account is not used any more."""
    cfg = _load(data_dir(folder, ddir) / "apex-settings.json", {})
    dormant = cfg.get("dormant", ["HoldCo"])
    return {"dormant": [d for d in dormant if isinstance(d, str)]}


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- ledger
def load_ledger(folder):
    """Rows from the workbook Ledger sheet (row 4 on). Returns [] if the workbook is missing."""
    wb = finance_dir(folder) / WORKBOOK
    if not wb.is_file():
        return []
    sh = read_xlsx(wb).get("Ledger", {})
    rows = []
    for r in range(4, max([k[0] for k in sh] + [3]) + 1):
        d = _date(sh.get((r, "A"))) or ""
        if not d and not (sh.get((r, "G")) or sh.get((r, "H"))):
            continue          # an empty line; rows with amounts but no date still count (as in the workbook totals)
        rows.append({"src": "xlsx", "row": r, "date": d, "month": d[:7], "account": _txt(sh.get((r, "C"))),
                     "type": _txt(sh.get((r, "D"))), "category": _txt(sh.get((r, "E"))), "desc": _txt(sh.get((r, "F"))),
                     "in": _num(sh.get((r, "G"))), "out": _num(sh.get((r, "H"))), "shared": _txt(sh.get((r, "I"))),
                     "paid_by": _txt(sh.get((r, "K"))), "status": _txt(sh.get((r, "L"))), "notes": _txt(sh.get((r, "M")))})
    return rows


def approved_rows(folder, ddir=None):
    adds = _load(data_dir(folder, ddir) / "apex-ledger-adds.json", {"rows": [], "rejected": []})
    out = []
    for r in adds.get("rows", []):
        x = dict(r)
        x["src"] = "sarah"
        x["month"] = x["date"][:7]
        out.append(x)
    return out


def all_rows(folder, ddir=None):
    return load_ledger(folder) + approved_rows(folder, ddir)


def cash_effect(r):
    if r["account"] in BANK_ACCOUNTS and r["status"] != "Due":
        return round(r["in"] - r["out"], 2)
    return 0.0


# ---------------------------------------------------------------- workbook sheets
def read_sheets(folder):
    wb = finance_dir(folder) / WORKBOOK
    return read_xlsx(wb) if wb.is_file() else {}


def construction(sheets):
    sh = sheets.get("Construction Budget", {})
    items, contract = [], 0.0
    for r in range(4, 40):
        ref, st = sh.get((r, "A")), sh.get((r, "F"))
        if not ref or not st:
            continue
        item = {"ref": _txt(ref), "desc": _txt(sh.get((r, "B"))), "subtotal": _num(sh.get((r, "C"))),
                "gst": _num(sh.get((r, "D"))), "total": _num(sh.get((r, "E"))), "status": _txt(st)}
        if item["status"] == "Contract":
            contract = item["total"]
        else:
            items.append(item)
    paid = sum(i["total"] for i in items if i["status"] == "Paid")
    due = sum(i["total"] for i in items if i["status"] == "Due")
    return {"contract": contract, "items": items, "paid": round(paid, 2), "due": round(due, 2),
            "remaining": round(contract - paid - due, 2)}


def contributions(sheets):
    sh = sheets.get("Capital & Contributions", {})
    purchase = [{"who": _txt(sh.get((r, "A"))), "source": _txt(sh.get((r, "B"))), "amount": _num(sh.get((r, "C"))),
                 "date": _date(sh.get((r, "D"))) or "", "notes": _txt(sh.get((r, "E")))} for r in range(6, 11) if sh.get((r, "C"))]
    topups = [{"who": _txt(sh.get((r, "A"))), "target": _num(sh.get((r, "B"))), "received": _num(sh.get((r, "C"))),
               "status": _txt(sh.get((r, "D"))), "notes": _txt(sh.get((r, "E")))} for r in range(16, 19)]
    fronted = round(sum(_num(sh.get((r, "C"))) for r in range(24, 30)), 2)
    zara = round(sum(_num(sh.get((r, "C"))) for r in (38, 39)), 2)
    return {"purchase": purchase, "topups": topups, "fronted_adeel": fronted, "paid_zara": zara,
            "warning": _txt(sh.get((12, "A")))}


def loc_info(sheets, rows):
    sh = sheets.get("BMO LOC", {})
    facs = []
    for r in (6, 7, 8):
        name, lim = _txt(sh.get((r, "B"))), _num(sh.get((r, "C")))
        key = {6: "term", 7: "mastercard", 8: "overdraft"}[r]
        drawn = sum(x["in"] for x in rows if x["type"] == "Loan-In" and key in (x["category"] + " " + x["desc"]).lower())
        facs.append({"name": name, "limit": lim, "drawn": round(drawn, 2), "available": round(lim - drawn, 2)})
    reminders = []
    for r in range(59, 70):
        if sh.get((r, "D")) == "Open" and sh.get((r, "B")):
            reminders.append({"action": _txt(sh.get((r, "B"))), "due": _txt(sh.get((r, "C"))), "notes": _txt(sh.get((r, "F")))})
    return {"facilities": facs, "reminders": reminders}


# ---------------------------------------------------------------- summary (mirrors the workbook Dashboard)
def summarize(folder, ddir=None):
    rows = all_rows(folder, ddir)
    sheets = read_sheets(folder)
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], [0.0, 0.0])
        by_type[r["type"]][0] += r["in"]
        by_type[r["type"]][1] += r["out"]
    tin = lambda t: round(by_type.get(t, [0, 0])[0], 2)     # noqa: E731
    tout = lambda t: round(by_type.get(t, [0, 0])[1], 2)    # noqa: E731
    funds_in = tin("Capital-In") + tin("Income") + tin("Loan-In")
    spent = tout("Purchase") + tout("Expense")
    settle = tout("Reimbursement") + tout("Loan-Repay")
    months = {}
    for r in rows:
        m = months.setdefault(r["month"], {"in": 0.0, "out": 0.0})
        m["in"] += r["in"]
        m["out"] += r["out"]
    cats = {}
    for r in rows:
        if r["type"] in ("Expense", "Purchase") and r["out"]:
            cats[r["category"]] = round(cats.get(r["category"], 0) + r["out"], 2)
    accounts = {}
    for r in rows:
        accounts[r["account"]] = round(accounts.get(r["account"], 0) + cash_effect(r), 2)
    contrib = contributions(sheets) if sheets else {}
    repaid_adeel = sum(r["out"] for r in rows if r["type"] == "Reimbursement" and r["paid_by"] == "to Adeel")
    repaid_zara = sum(r["out"] for r in rows if r["type"] == "Reimbursement" and r["paid_by"] == "to Zara")
    owed_adeel = round(contrib.get("fronted_adeel", 0) - repaid_adeel, 2) if contrib else 0.0
    owed_zara = round(contrib.get("paid_zara", 0) - repaid_zara, 2) if contrib else 0.0
    unpaid = round(sum(r["out"] for r in rows if r["status"] == "Due"), 2)
    cash = round(sum(cash_effect(r) for r in rows), 2)
    undated = [r for r in rows if not r["date"]]
    flags = [{"date": r["date"] or "no date", "desc": r["desc"], "why": "Needs a check: " + (r["paid_by"] if "⚠" in r["paid_by"] else r["notes"])[:140]}
             for r in rows if "⚠" in r["paid_by"] or "⚠" in r["notes"]]
    bank_undated = [r for r in undated if r["account"] in BANK_ACCOUNTS]
    for r in bank_undated:
        flags.append({"date": "no date", "desc": r["desc"], "why": f"Bank-account row without a date (${r['out'] or r['in']:,.2f}); add the date so it reconciles"})
    con = construction(sheets) if sheets else {}
    return {
        "found": bool(sheets), "rows": len(rows), "added_by_sarah": sum(1 for r in rows if r["src"] == "sarah"),
        "kpi": {"capital_in": tin("Capital-In"), "income": tin("Income"), "loan_in": tin("Loan-In"), "funds_in": round(funds_in, 2),
                "property": tout("Purchase"), "expenses": tout("Expense"), "spent": round(spent, 2), "settlements": round(settle, 2),
                "net_position": round(funds_in - spent - settle, 2), "cash_on_hand": cash, "unpaid_invoices": unpaid,
                "owed_adeel": owed_adeel, "owed_zara": owed_zara, "to_settle": round(unpaid + owed_adeel + owed_zara, 2)},
        "months": [{"month": m or "No date", "in": round(v["in"], 2), "out": round(v["out"], 2), "net": round(v["in"] - v["out"], 2)} for m, v in sorted(months.items(), key=lambda kv: (kv[0] == "", kv[0]))],
        "categories": sorted(({"category": k, "amount": v} for k, v in cats.items()), key=lambda x: -x["amount"]),
        "accounts": accounts, "construction": con, "contributions": contrib, "loc": loc_info(sheets, rows) if sheets else {},
        "flags": flags, "last_entry": max((r["date"] for r in rows if r["date"]), default=""),
    }


# ---------------------------------------------------------------- bank statements
def _statement_files(folder):
    base = finance_dir(folder) / "BMO Bank Doc" / "Bank Statement"
    return sorted(base.glob("*.pdf")) if base.is_dir() else []


def _account_of(name):
    n = name.lower()
    if n.startswith("holco") or n.startswith("holdco"):
        return "HoldCo"
    if n.startswith("opco"):
        return "OpCo"
    return ""


def _money(s):
    return float(s.replace(",", ""))


def parse_statement(path):
    """Read a BMO business statement PDF. Returns {'account','closing','closing_date','opening','txns':[...] } or None.
    Debit vs credit comes from the running balance (reliable); position of the amount is the fallback."""
    text = pdf_text(str(path))
    if not text or "Transaction details" not in text:
        return None
    m = re.search(r"period ending\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if not m:
        return None
    end = dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    opening = start = None
    txns, prev, pending = [], None, []
    in_tx = False
    for line in text.splitlines():
        if "Transaction details" in line:
            in_tx = True
            continue
        if not in_tx or not line.strip():
            continue
        mm = re.match(r"\s*([A-Z][a-z]{2})\s+(\d{1,2})\s+(.*?)\s*$", line)
        if mm and mm.group(1).lower() in MONTHS:
            mon, day, rest = MONTHS[mm.group(1).lower()], int(mm.group(2)), mm.group(3)
            if rest.startswith("Opening balance"):
                nums = re.findall(r"[\d,]+\.\d\d", rest)
                prev = opening = _money(nums[-1]) if nums else None
                start = dt.date(end.year if mon <= end.month else end.year - 1, mon, day)
                continue
            if rest.startswith("Closing totals"):
                break
            nums = re.findall(r"[\d,]+\.\d\d", rest)
            if not nums:
                continue
            desc = re.sub(r"\s+[\d,]+\.\d\d.*$", "", rest).strip()
            year = end.year if mon <= end.month else end.year - 1
            amt = _money(nums[0])
            bal = _money(nums[1]) if len(nums) > 1 else None
            col = line.rfind(nums[0]) + len(nums[0])
            txns.append({"date": dt.date(year, mon, day).isoformat(), "desc": desc, "amount": amt, "balance": bal, "col": col})
            continue
        if txns and line.startswith(" ") and not re.search(r"[\d,]+\.\d\d", line) and not line.strip().startswith(("Number of", "Page")):
            txns[-1]["desc"] = (txns[-1]["desc"] + " " + line.strip()).strip()
    # direction
    prev = opening
    known = []
    for t in txns:
        if t["balance"] is not None and prev is not None:
            t["credit"] = t["balance"] > prev
            known.append((t["col"], t["credit"]))
        elif prev is not None and t["balance"] is None:
            t["credit"] = None
        prev = t["balance"] if t["balance"] is not None else prev
    if known:
        cr = [c for c, k in known if k]
        db = [c for c, k in known if not k]
        thr = (min(cr) + max(db)) / 2 if cr and db else None
    else:
        thr = None
    for t in txns:
        if t.get("credit") is None:
            t["credit"] = bool(thr and t["col"] > thr)
        t.pop("col", None)
    closing = txns and next((t["balance"] for t in reversed(txns) if t["balance"] is not None), None)
    sm = re.search(r"#\s*[\d\- ]+\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)", text)
    totals = {"opening": _money(sm.group(1)), "debits": _money(sm.group(2)), "credits": _money(sm.group(3)), "closing": _money(sm.group(4))} if sm else {}
    if totals:
        closing = totals["closing"]
        opening = totals["opening"]
    got_d = round(sum(t["amount"] for t in txns if not t["credit"]), 2)
    got_c = round(sum(t["amount"] for t in txns if t["credit"]), 2)
    ok = bool(totals) and abs(got_d - totals["debits"]) < 0.01 and abs(got_c - totals["credits"]) < 0.01
    return {"account": _account_of(Path(path).name), "period_end": end.isoformat(), "opening": opening, "closing": closing,
            "txns": txns, "checked": ok, "file": Path(path).name,
            "start": (start or dt.date(end.year, end.month, 1)).isoformat()}


def suggest(account, desc, credit):
    """Rule-based starting point for a proposed row. Adeel confirms every one."""
    d = desc.upper()
    if "HIQ SQUARE" in d:
        return "Expense", "Condo Fee", "Y", "Paid", ""
    if "INVOICE" in d or "DEFT SETTLEMENT" in d:
        return "Expense", "Construction", "Y", "Paid", "Confirm which PrimeRidge invoice"
    if "TRANSFER FROM" in d or "MOVING TO APEX" in d or re.search(r"TRANSFER,\s*\d{4}-\d{4}-\d{3}", d) or d.startswith("TRANSFER"):
        return "Transfer", "Internal transfer", "N", "Received" if credit else "Paid", "Own-account transfer – confirm"
    if "E-TRANSFER RECEIVED" in d or "DEPOSIT" in d or "WIRE" in d:
        return "Capital-In", "Top-up", "N", "Received", "⚠ Confirm which partner sent this"
    if "FEE" in d or "SERVICE CHARGE" in d or "CHARGE" in d:
        return "Expense", "Bank Fee", "N", "Paid", ""
    if "INTEREST" in d:
        return "Expense", "Interest", "N", "Paid", ""
    return ("Capital-In" if credit else "Expense"), ("Top-up" if credit else "Other"), "N", ("Received" if credit else "Paid"), "⚠ New kind of line – pick the category"


def _row_id(account, t):
    return hashlib.sha1(f"{account}|{t['date']}|{t['desc']}|{t['amount']}|{t['credit']}".encode()).hexdigest()[:12]


def match_statement_to_ledger(stmt, rows):
    """Statement lines that are not in the ledger yet (same account, same amount in the right column, within 5 days)."""
    used, missing = set(), []
    led = [r for r in rows if r["account"] == stmt["account"]]
    for t in stmt["txns"]:
        d = dt.date.fromisoformat(t["date"])
        hit = None
        for i, r in enumerate(led):
            if i in used:
                continue
            amt = r["in"] if t["credit"] else r["out"]
            if abs(amt - t["amount"]) < 0.01 and abs((dt.date.fromisoformat(r["date"]) - d).days) <= 5:
                hit = i
                break
        if hit is None:
            missing.append(t)
        else:
            used.add(hit)
    return missing


def scan_statements(folder, ddir=None):
    """Read every statement, compare with the ledger, return coverage + proposals (not saved)."""
    rows = all_rows(folder, ddir)
    adds = _load(data_dir(folder, ddir) / "apex-ledger-adds.json", {"rows": [], "rejected": []})
    rejected = set(adds.get("rejected", []))
    approved_ids = {r.get("id") for r in adds.get("rows", [])}
    coverage, proposals, balances = {}, [], {}
    stmts = []
    for f in _statement_files(folder):
        s = parse_statement(f)
        if s and s["account"]:
            stmts.append(s)
    stmts.sort(key=lambda x: (x["account"], x["period_end"]))
    prev_end = {}
    for s in stmts:
        acct = s["account"]
        coverage.setdefault(acct, []).append({"file": s["file"], "start": s["start"], "period_end": s["period_end"],
                                              "closing": s["closing"], "checked": s["checked"]})
        bal = balances.get(acct)
        if not bal or s["period_end"] > bal["date"]:
            balances[acct] = {"date": s["period_end"], "balance": s["closing"]}
        lo = prev_end.get(acct, "0000-00-00")
        prev_end[acct] = s["period_end"]
        # the ledger may record a statement's lines differently (netted, from the other account's side); when the
        # ledger's cash change for the period equals the statement's, the period is fine and nothing is proposed
        led_net = round(sum(cash_effect(r) for r in rows if r["account"] == acct and lo < r["date"] <= s["period_end"]), 2)
        stmt_net = round((s["closing"] or 0) - (s["opening"] or 0), 2)
        if s["checked"] and abs(led_net - stmt_net) < 0.01:
            continue
        for t in match_statement_to_ledger(s, rows):
            pid = _row_id(acct, t)
            if pid in rejected or pid in approved_ids:
                continue
            typ, cat, shared, status, note = suggest(acct, t["desc"], t["credit"])
            proposals.append({"id": pid, "date": t["date"], "account": acct, "type": typ, "category": cat,
                              "desc": t["desc"].title() if t["desc"].isupper() else t["desc"],
                              "in": t["amount"] if t["credit"] else 0.0, "out": 0.0 if t["credit"] else t["amount"],
                              "shared": shared, "paid_by": "", "status": status,
                              "notes": ("From " + s["file"] + (". " + note if note else "")) + ("" if s["checked"] else " (statement totals did not tie – check)")})
    for lst in coverage.values():
        lst.sort(key=lambda x: x["period_end"])
    proposals.sort(key=lambda p: (p["date"], p["account"]))
    dormant = settings(folder, ddir)["dormant"]
    return {"coverage": coverage, "balances": balances, "proposals": [p for p in proposals if p["account"] not in dormant],
            "dormant": dormant, "dormant_new": sum(1 for p in proposals if p["account"] in dormant),
            "scanned": dt.datetime.now().isoformat(timespec="seconds")}


def reconcile(folder, ddir=None, scan=None):
    """Ledger cash per account up to the latest statement vs the statement closing balance."""
    scan = scan or scan_statements(folder, ddir)
    rows = all_rows(folder, ddir)
    out = []
    for acct, b in scan["balances"].items():
        if acct in scan.get("dormant", []):
            continue
        led = round(sum(cash_effect(r) for r in rows if r["account"] == acct and r["date"] and r["date"] <= b["date"]), 2)
        out.append({"account": acct, "through": b["date"], "statement": b["balance"], "ledger": led,
                    "difference": round(b["balance"] - led, 2) if b["balance"] is not None else None})
    return out


def archive(scan, rows):
    """Dormant accounts (HoldCo): final balance and history only. No alerts, no reminders."""
    out = []
    for acct in scan.get("dormant", []):
        cov = scan["coverage"].get(acct, [])
        b = scan["balances"].get(acct)
        led = round(sum(cash_effect(r) for r in rows if r["account"] == acct and (not b or (r["date"] and r["date"] <= b["date"]))), 2)
        out.append({"account": acct, "statements": len(cov), "first": cov[0]["start"] if cov else "", "last": cov[-1]["period_end"] if cov else "",
                    "final_balance": b["balance"] if b else None, "ledger": led,
                    "difference": round(b["balance"] - led, 2) if b and b["balance"] is not None else None,
                    "new_activity": scan.get("dormant_new", 0)})
    return out


def missing_statements(scan, today=None):
    """Months not covered by any statement between the first statement and last month (a month is due ~10 days after it closes)."""
    today = today or dt.date.today()
    first_of = today.replace(day=1)
    last = first_of - dt.timedelta(days=1) if today.day >= 10 else (first_of - dt.timedelta(days=1)).replace(day=1) - dt.timedelta(days=1)
    out = {}
    for acct, files in scan["coverage"].items():
        if acct in scan.get("dormant", []):
            continue
        have = set()
        for f in files:
            y, m = map(int, f["start"][:7].split("-"))
            ey, em = map(int, f["period_end"][:7].split("-"))
            while (y, m) <= (ey, em):
                have.add(f"{y:04d}-{m:02d}")
                m += 1
                if m == 13:
                    y, m = y + 1, 1
        if not have:
            continue
        y, m = map(int, min(have).split("-"))
        miss = []
        while (y, m) <= (last.year, last.month):
            if f"{y:04d}-{m:02d}" not in have:
                miss.append(f"{y:04d}-{m:02d}")
            m += 1
            if m == 13:
                y, m = y + 1, 1
        if miss:
            out[acct] = miss
    return out


def save_proposals(folder, scan, ddir=None):
    path = data_dir(folder, ddir) / "apex-ledger-inbox.json"
    _save(path, {"proposals": scan["proposals"], "scanned": scan["scanned"]})


def load_proposals(folder, ddir=None):
    return _load(data_dir(folder, ddir) / "apex-ledger-inbox.json", {"proposals": [], "scanned": ""})


FIELDS = ("date", "account", "type", "category", "desc", "in", "out", "shared", "paid_by", "status", "notes")


def add_payable(folder, row, ddir=None):
    """Record a bill (Due, or already paid personally by a partner) straight into the approved ledger additions. No money moves."""
    try:
        date = dt.date.fromisoformat(str(row.get("date", "")))
        amt = round(float(row.get("amount", 0)), 2)
    except (ValueError, TypeError):
        raise ValueError("Enter a valid date and amount.")
    acct = str(row.get("account", "OpCo"))
    fronted = str(row.get("fronted_by", "")).strip()
    if fronted:
        if fronted not in ("Huzefa", "Zara", "Adeel"):
            raise ValueError("Pick Huzefa, Zara or Adeel.")
        acct = "Personal-" + fronted
    elif acct not in ("OpCo", "HoldCo"):
        raise ValueError("Pick OpCo or HoldCo.")
    desc = " ".join(str(row.get("desc", "")).split())[:120]
    cat = " ".join(str(row.get("category", "")).split())[:40]
    if amt <= 0 or not desc or not cat:
        raise ValueError("Description, category and an amount above zero are required.")
    path = data_dir(folder, ddir) / "apex-ledger-adds.json"
    adds = _load(path, {"rows": [], "rejected": []})
    rid = "ap-" + hashlib.sha1(f"{date}|{desc}|{amt}".encode()).hexdigest()[:10]
    if any(r.get("id") == rid for r in adds["rows"]):
        raise ValueError("That bill is already recorded.")
    adds["rows"].append({"date": date.isoformat(), "account": acct, "type": "Expense", "category": cat, "desc": desc,
                         "in": 0.0, "out": amt, "shared": "Y" if row.get("shared", True) else "N", "paid_by": fronted,
                         "status": "Paid" if fronted else "Due", "notes": str(row.get("notes", ""))[:300], "id": rid,
                         "approved": dt.date.today().isoformat()})
    _save(path, adds)
    return rid


def decide(folder, ids, approve, ddir=None, edits=None):
    """Approve (moves to apex-ledger-adds.json) or reject proposals. `edits` {id: {field: value}} lets Adeel fix a row first."""
    inbox = load_proposals(folder, ddir)
    path = data_dir(folder, ddir) / "apex-ledger-adds.json"
    adds = _load(path, {"rows": [], "rejected": []})
    ids = set(ids)
    keep, n = [], 0
    for p in inbox["proposals"]:
        if p["id"] not in ids:
            keep.append(p)
            continue
        n += 1
        if approve:
            row = {k: p.get(k, "") for k in FIELDS}
            row.update({k: v for k, v in (edits or {}).get(p["id"], {}).items() if k in FIELDS})
            row["id"] = p["id"]
            row["approved"] = dt.date.today().isoformat()
            adds["rows"].append(row)
        else:
            adds["rejected"].append(p["id"])
    inbox["proposals"] = keep
    _save(path, adds)
    _save(data_dir(folder, ddir) / "apex-ledger-inbox.json", inbox)
    return n


# ---------------------------------------------------------------- invoices <-> payments
INVOICE_DIRS = ("Construction", "Operations", "Legal & Corporate", "Finance")


def _invoice_total(text):
    """Best guess at an invoice total (largest amount near 'total'/'amount due'/'balance')."""
    vals = []
    for m in re.finditer(r"(?i)(total|amount due|balance due|grand total|payment made)[^\d$\n]{0,25}\$?\s*([\d,]+\.\d\d)", text):
        vals.append(_money(m.group(2)))
    return max(vals) if vals else None


def scan_invoices(folder):
    out = []
    vroot = apex_vendors.root(folder)
    for d in INVOICE_DIRS + (apex_vendors.DIRNAME,):
        base = vroot if d == apex_vendors.DIRNAME else Path(folder) / d
        if not base.is_dir():
            continue
        for f in base.rglob("*.pdf"):
            vendor_file = d == apex_vendors.DIRNAME
            if (not vendor_file and not re.search(r"(?i)\binv|invoice|ord\d|receipt", f.name)) or "_to_delete" in f.parts:
                continue
            try:
                text = pdf_text(str(f))
            except Exception:  # noqa: BLE001
                text = ""
            tot = _invoice_total(text)
            dm = re.search(r"(?i)(?:invoice date|date)[:\s]+([A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", text)
            out.append({"file": f.name, "path": str(f.relative_to(base if d == apex_vendors.DIRNAME else folder)), "total": tot, "date_text": dm.group(1) if dm else ""})
    return out


def _fronted_items(sheets):
    """Amounts Adeel/Zara paid personally (tracked on 'Capital & Contributions', not as bank lines)."""
    sh = sheets.get("Capital & Contributions", {})
    items = []
    for r, who in list(zip(range(24, 30), ["Adeel"] * 6)) + list(zip(range(38, 40), ["Zara"] * 2)):
        if sh.get((r, "C")):
            items.append({"who": who, "item": _txt(sh.get((r, "A"))), "amount": _num(sh.get((r, "C")))})
    return items


def match_invoices(folder, ddir=None):
    """Matches by reference first (INV-03 in the file name and in the ledger text, so part payments add up), then by amount."""
    rows = [r for r in all_rows(folder, ddir) if r["out"] and r["type"] in ("Expense", "Purchase")]
    fronted = _fronted_items(read_sheets(folder))
    invs = scan_invoices(folder)
    used, matches, no_pay = set(), [], []
    for inv in invs:
        tot = inv["total"]
        if tot is None:
            no_pay.append({**inv, "why": "Could not read a total"})
            continue
        ref = re.search(r"(?i)\bINV[-\s]?0*(\d+)", inv["file"])
        by_ref = []
        if ref:
            pat = re.compile(r"(?i)\bINV[-\s]?0*" + ref.group(1) + r"\b")
            by_ref = [i for i, r in enumerate(rows) if i not in used and pat.search(r["desc"])]
        if by_ref:
            paid = round(sum(rows[i]["out"] for i in by_ref if rows[i]["status"] != "Due"), 2)
            used.update(by_ref)
            status = ("Paid" if abs(paid - tot) <= TOL else "Due – not paid yet" if paid == 0
                      else f"Part paid: ${tot - paid:,.2f} still owing")
            matches.append({"invoice": inv["file"], "total": tot, "paid": paid, "date": rows[by_ref[-1]]["date"],
                            "ledger": "; ".join(rows[i]["desc"] for i in by_ref), "status": status})
            continue
        hit = next((i for i, r in enumerate(rows) if i not in used and abs(r["out"] - tot) <= TOL), None)
        if hit is not None:
            used.add(hit)
            r = rows[hit]
            due = r["status"] == "Due"
            matches.append({"invoice": inv["file"], "total": tot, "paid": 0.0 if due else r["out"], "date": r["date"], "ledger": r["desc"],
                            "status": "Due – not paid yet" if due else "Paid"})
            continue
        pers = next((f for f in fronted if abs(f["amount"] - tot) <= TOL), None)
        if pers:
            matches.append({"invoice": inv["file"], "total": tot, "paid": tot, "date": inv["date_text"], "ledger": f"Paid personally by {pers['who']} (reimbursement tracker)",
                            "status": "Paid personally"})
        else:
            no_pay.append({**inv, "why": "No payment of this amount in the ledger"})
    big = [{"date": r["date"], "desc": r["desc"], "amount": r["out"]} for i, r in enumerate(rows)
           if i not in used and r["out"] >= 500 and r["type"] == "Expense"]
    return {"matches": matches, "invoices_without_payment": no_pay, "payments_without_invoice": big}


# ---------------------------------------------------------------- reminders (each becomes at most one draft)
def reminders(folder, ddir=None, today=None, scan=None, matches=None):
    today = today or dt.date.today()
    rows = all_rows(folder, ddir)
    sheets = read_sheets(folder)
    out = []
    ym = today.strftime("%Y-%m")
    if today.day >= 6 and any(r["category"] == "Condo Fee" for r in rows) and \
            not any(r["category"] == "Condo Fee" and r["month"] == ym for r in rows) and \
            not any(r["category"] == "Condo Fee" and r["month"] > ym for r in rows):
        out.append({"key": f"apex_condo_{ym}", "title": f"APEX: condo fee for {today.strftime('%B %Y')} is not in the ledger",
                    "body": "The HIQ Square condo fee (about $378.41, pre-authorized around the 1st) has no ledger row this month. "
                            "It should appear in the next statement; if the account is dormant, check the payment still goes out."})
    con = construction(sheets) if sheets else {}
    for it in con.get("items", []):
        if it["status"] == "Due":
            wk = today.isocalendar()
            out.append({"key": f"apex_inv_{it['ref']}_{wk[0]}W{wk[1]:02d}", "title": f"APEX: PrimeRidge {it['ref']} is due (${it['total']:,.2f})",
                        "body": f"{it['desc']}. Status is Due in the Cost Controller. Pay from OpCo, then record it in the Ledger as Expense / Construction. "
                                "Sarah does not pay anything."})
    for m in (matches if matches is not None else match_invoices(folder, ddir))["matches"]:
        if m["status"].startswith("Part paid"):
            out.append({"key": "apex_part_" + re.sub(r"\W+", "", m["invoice"]) + f"_{int(m['paid'])}", "title": f"APEX: {m['invoice']} is only part paid",
                        "body": f"{m['status']} (invoice ${m['total']:,.2f}, paid ${m['paid']:,.2f}). The Construction Budget tab may show it as Paid; "
                                "check with the contractor and update the Ledger or the budget."})
    scan = scan or scan_statements(folder, ddir)
    miss = missing_statements(scan, today)
    for acct, months in miss.items():
        out.append({"key": f"apex_stmt_{acct}_{months[-1]}", "title": f"APEX: {acct} statement missing for {', '.join(months)}",
                    "body": "Download the BMO statement(s) into Finance\\BMO Bank Doc\\Bank Statement (file name starts with "
                            f"\"{'Holco' if acct == 'HoldCo' else 'OpCo'} -\"). Sarah will then draft the new ledger rows."})
    if scan["proposals"]:
        out.append({"key": f"apex_prop_{len(scan['proposals'])}_{ym}", "title": f"APEX: {len(scan['proposals'])} statement lines are not in the ledger yet",
                    "body": "Open the APEX Finance page and approve or reject the proposed rows."})
    return out


# ---------------------------------------------------------------- one call for the page
def overview(folder, ddir=None):
    summ = summarize(folder, ddir)
    scan = scan_statements(folder, ddir) if summ["found"] else {"coverage": {}, "balances": {}, "proposals": [], "scanned": ""}
    inbox = load_proposals(folder, ddir)
    dormant = scan.get("dormant", [])
    live = lambda d: {k: v for k, v in d.items() if k not in dormant}    # noqa: E731
    props = [p for p in (inbox["proposals"] or scan["proposals"]) if p.get("account") not in dormant]
    return {"summary": summ, "dormant": dormant,
            "statements": {"coverage": live(scan["coverage"]), "balances": live(scan["balances"]),
                           "missing": missing_statements(scan), "reconcile": reconcile(folder, ddir, scan)},
            "archive": archive(scan, all_rows(folder, ddir)),
            "proposals": props, "scanned": inbox.get("scanned") or scan["scanned"]}


def full(folder, ddir=None, today=None):
    """Everything the APEX Finance page shows, in one call (read-only, nothing is saved)."""
    out = overview(folder, ddir)
    out["invoices"] = match_invoices(folder, ddir)
    out["reminders"] = reminders(folder, ddir, today, matches=out["invoices"])
    out["vendors"] = apex_vendors.overview(folder, ddir)
    n = len(out["vendors"]["inbox"])
    if n:
        out["reminders"].append({"key": f"apex_inbox_{n}_{(today or dt.date.today()).isocalendar()[1]}", "title": f"APEX: {n} vendor invoice(s) waiting in the Inbox",
                                 "body": "Open the APEX Finance page > Vendor invoices, check the vendor, and approve to file them."})
    con = out["summary"].get("construction") or {}
    for it in con.get("items", []):
        m = re.search(r"Milestone\s+(\d+)", it["desc"])
        it["check"] = None
        if m:
            pat = re.compile(r"(?i)\bINV[-\s]?0*" + m.group(1) + r"\b")
            hit = next((x for x in out["invoices"]["matches"] if pat.search(x["invoice"])), None)
            if hit:
                it["check"] = hit["status"]
                it["check_ok"] = (hit["status"] == "Paid" and it["status"] == "Paid") or (hit["status"].startswith("Due") and it["status"] == "Due")
    return out
