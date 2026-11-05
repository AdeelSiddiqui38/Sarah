"""Monthly partner snapshot for APEX Physio (read-only; the email is only ever a draft).

Built from the Cost Controller + Sarah's approved rows + statements, plus short
progress notes Adeel types in (Sarah cannot know those on her own).
"""
import datetime as dt
import json
from pathlib import Path

import apex_finance as af

NOTES = "apex-report-notes.json"
PARTNERS = ("Adeel", "Huzefa", "Zara")


def _p(folder, ddir):
    return af.data_dir(folder, ddir) / NOTES


def load_notes(folder, ddir=None):
    try:
        return json.loads(_p(folder, ddir).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_notes(folder, month, progress, decisions, ddir=None):
    _check_month(month)
    clean = lambda xs: [" ".join(str(x).split())[:300] for x in (xs or []) if str(x).strip()][:20]  # noqa: E731
    allnotes = load_notes(folder, ddir)
    allnotes[month] = {"progress": clean(progress), "decisions": clean(decisions)}
    p = _p(folder, ddir)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(allnotes, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _check_month(m):
    try:
        dt.date.fromisoformat(str(m) + "-01")
    except ValueError:
        raise ValueError("Month must look like 2026-10.")


def previous_month(today):
    first = today.replace(day=1)
    last = first - dt.timedelta(days=1)
    return last.strftime("%Y-%m")


def build(folder, ddir=None, month=None, today=None):
    today = today or dt.date.today()
    month = month or previous_month(today)
    _check_month(month)
    ov = af.overview(folder, ddir)
    s = ov["summary"]
    k = s.get("kpi", {})
    rows = af.all_rows(folder, ddir)
    mrows = [r for r in rows if r["month"] == month]
    m_in = round(sum(r["in"] for r in mrows if r["account"] in af.BANK_ACCOUNTS and r["status"] != "Due"), 2)
    m_out = round(sum(r["out"] for r in mrows if r["account"] in af.BANK_ACCOUNTS and r["status"] != "Due"), 2)
    cats = {}
    for r in mrows:
        if r["type"] in ("Expense", "Purchase") and r["out"]:
            cats[r["category"]] = round(cats.get(r["category"], 0) + r["out"], 2)
    due = [{"date": r["date"], "desc": r["desc"], "amount": r["out"], "account": r["account"]} for r in rows if r["status"] == "Due"]
    owed = {"Adeel": k.get("owed_adeel", 0.0), "Zara": k.get("owed_zara", 0.0), "Huzefa": 0.0}
    fronted_h = sum(r["out"] for r in rows if r["account"] == "Personal-Huzefa" and r["paid_by"] == "Huzefa")
    repaid_h = sum(r["out"] for r in rows if r["type"] == "Reimbursement" and r["paid_by"] == "to Huzefa")
    owed["Huzefa"] = round(fronted_h - repaid_h, 2)
    unpaid_total = round(sum(d["amount"] for d in due), 2)
    owe_total = round(unpaid_total + sum(v for v in owed.values() if v > 0), 2)
    bal = (ov.get("statements") or {}).get("balances", {})
    con = s.get("construction") or {}
    con_paid = round(sum(i["total"] for i in con.get("items", []) if i["status"] == "Paid"), 2)
    con_due = round(sum(i["total"] for i in con.get("items", []) if i["status"] == "Due"), 2)
    notes = load_notes(folder, ddir).get(month, {"progress": [], "decisions": []})
    needs = []
    for d in due:
        needs.append(f"Bill due: {d['desc']} ${d['amount']:,.2f} (OpCo to pay)")
    for who, v in owed.items():
        if v > 0.005:
            needs.append(f"Reimburse {who}: ${v:,.2f}")
    for m in (ov.get("statements") or {}).get("missing", {}).items() if isinstance((ov.get("statements") or {}).get("missing"), dict) else []:
        needs.append(f"{m[0]} statement missing: {', '.join(m[1])}")
    needs += [f"Check: {f['desc']}" for f in s.get("flags", [])[:3]]
    needs += notes.get("decisions", [])
    return {
        "month": month, "generated": today.isoformat(),
        "bank": {a: {"balance": v["balance"], "as_of": v["date"]} for a, v in bal.items()},
        "month_activity": {"money_in": m_in, "money_out": m_out, "net": round(m_in - m_out, 2), "by_category": sorted(({"category": c, "amount": v} for c, v in cats.items()), key=lambda x: -x["amount"])},
        "owe": {"unpaid_bills": due, "unpaid_total": unpaid_total, "owed_to_partners": owed, "total": owe_total},
        "project": {"capital_in": k.get("capital_in", 0), "spent": k.get("spent", 0), "property": k.get("property", 0), "expenses": k.get("expenses", 0),
                    "construction_contract": con.get("contract", 0), "construction_paid": con_paid, "construction_due": con_due,
                    "construction_remaining": round(con.get("contract", 0) * 1.05 - con_paid - con_due, 2) if con.get("contract") else 0},
        "per_partner_share_of_bills": round(unpaid_total / 3, 2),
        "progress": notes.get("progress", []), "needs_attention": needs,
    }


def money(v):
    return f"${v:,.2f}"


def text(r):
    L = [f"APEX Physio – partner snapshot for {r['month']}", f"Prepared {r['generated']} (draft for review)", ""]
    L.append("1. MONEY SNAPSHOT")
    for a, b in r["bank"].items():
        L.append(f"- {a} bank balance: {money(b['balance'])} (statement to {b['as_of']})")
    ma = r["month_activity"]
    L.append(f"- {r['month']} ledger bank activity: in {money(ma['money_in'])}, out {money(ma['money_out'])}, net {money(ma['net'])}")
    for c in ma["by_category"][:6]:
        L.append(f"    spent on {c['category']}: {money(c['amount'])}")
    L += ["", "2. WHAT WE OWE"]
    if r["owe"]["unpaid_bills"]:
        for d in r["owe"]["unpaid_bills"]:
            L.append(f"- Unpaid bill: {d['desc']} – {money(d['amount'])}")
    else:
        L.append("- No unpaid bills.")
    for who, v in r["owe"]["owed_to_partners"].items():
        if v > 0.005:
            L.append(f"- Owed back to {who}: {money(v)}")
    L.append(f"- Total to settle: {money(r['owe']['total'])}")
    if r["owe"]["unpaid_total"]:
        L.append(f"- Unpaid bills split three ways: {money(r['per_partner_share_of_bills'])} each")
    p = r["project"]
    L += ["", "3. PROJECT",
          f"- Capital in: {money(p['capital_in'])}; spent to date: {money(p['spent'])} (property {money(p['property'])}, expenses {money(p['expenses'])})"]
    if p["construction_contract"]:
        L.append(f"- Construction (PrimeRidge): contract {money(p['construction_contract'])} + GST; paid {money(p['construction_paid'])}, invoiced and due {money(p['construction_due'])}")
    L += ["", "4. PROGRESS THIS MONTH"]
    L += [f"- {x}" for x in r["progress"]] or ["- (no notes entered yet)"]
    L += ["", "5. NEEDS ATTENTION / DECISIONS"]
    L += [f"- {x}" for x in r["needs_attention"]] or ["- Nothing outstanding."]
    L += ["", "Figures come from the Cost Controller and bank statements; the Excel workbook stays the master."]
    return "\n".join(L)
