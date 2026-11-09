"""Supervisor: one per company. Delegates work to the company's agents, checks every draft before Adeel sees it,
and raises alerts. Pure functions only (no database, no network) so the rules are easy to test.

PILLAR rules (Adeel, Nov 9 2026), for every company in Sarah, now and future:
  P1 each company is independent (own vault, folder, mailbox, agents); nothing crosses companies
  P2 one Supervisor per company; every agent task goes through her
  P3 agents are draft-only; Adeel approves anything that sends, pays, publishes or deletes
  P4 every action is logged (time, company, agent, action, input, result, approver)
  P5 Supervisor communicates by alerts only (no daily or weekly summaries for now)
  P6 when the Supervisor needs direction she asks Adeel and waits
  P7 a new company gets the same template, and its Supervisor comes with it
"""
import re

STALE_DAYS = 3

# Words that identify a company. A draft for one company must not carry another company's identifiers (P1).
COMPANIES = {
    "APEX Physio": {
        "match": r"apex",
        # Not the street or "Nolan Hill": Remedy Pills is in the same building (Unit 135), so location words are shared.
        "identifiers": ["apex physio", "apex-physio", "apexphysio", "info@apex-physio.ca", "2817532 alberta",
                        "unit 150"],
        "agents": {
            "Finance": "Bank statements, ledger proposals, payables, partner snapshot",
            "Email": "info@apex-physio.ca: read every 6 h, draft replies to the outbox",
            "Website/SEO": "apex-physio.ca changes (PR, then Adeel merges, then upload), Search Console",
            "Marketing": "Local content, Business Profile, reviews",
            "Social media": "Posts (not built yet; needs the list of APEX social accounts)",
        },
    },
    "Remedy Pills": {
        "match": r"remedy",
        "identifiers": ["remedy pills", "remedypills", "remedypillspharmacy"],
        "agents": {
            "Finance": "Ledger, statements, CRA records",
            "Invoices": "Vendor invoices from remedypillspharmacy@gmail.com, weekly and monthly",
            "Website": "remedypills.ca (WordPress) checks",
            "Marketing": "Weekly marketing brief",
            "Social media": "Weekly Facebook, Instagram and Nextdoor drafts",
            "Coordinator": "Reminders, scheduling, follow-ups",
        },
    },
}

SENSITIVE = re.compile(r"\b(send|sent to|pay|payment|e-?transfer|wire|publish|post (it|this|to)|delete|cancel|sign)\b", re.I)
PASSWORD = re.compile(r"\b(password|passcode|app password|pin)\s*[:=]\s*\S+", re.I)
SIN = re.compile(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b")
ACCOUNT = re.compile(r"\b(account|acct|a/c)\s*(no\.?|number|#)?\s*[:#]?\s*\d{5,}\b", re.I)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def company_of(project_name):
    """The company a project belongs to, or None for an unknown project."""
    n = (project_name or "").lower()
    for name, c in COMPANIES.items():
        if re.search(c["match"], n):
            return name
    return None


def _luhn(digits):
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s % 10 == 0


DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _has_card(text):
    text = DATE.sub(" ", text)  # ISO dates side by side ("2026-10-01 2026-10-31") are not card numbers
    for m in CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


def check_draft(company, title, body):
    """Supervisor review of one draft. Returns {"ok", "issues", "needs_adeel"}.
    Blocking issues put the draft on hold until Adeel releases it; nothing is deleted."""
    title, body = (title or "").strip(), (body or "").strip()
    text = f"{title}\n{body}"
    low = text.lower()
    issues = []
    if not title or not body:
        issues.append({"code": "empty", "msg": "Draft has no title or no body."})
    if company:
        for other, c in COMPANIES.items():
            if other == company:
                continue
            hit = next((w for w in c["identifiers"] if w in low), None)
            if hit:
                issues.append({"code": "cross_company",
                               "msg": f"{company} draft mentions {other} ('{hit}'). Companies must stay separate."})
    else:
        issues.append({"code": "no_company", "msg": "Draft is not linked to a known company."})
    if PASSWORD.search(text):
        issues.append({"code": "secret", "msg": "Draft seems to contain a password or PIN."})
    if SIN.search(text):
        issues.append({"code": "secret", "msg": "Draft seems to contain a SIN (###-###-###)."})
    if ACCOUNT.search(text):
        issues.append({"code": "secret", "msg": "Draft seems to contain a bank account number."})
    if _has_card(text):
        issues.append({"code": "secret", "msg": "Draft seems to contain a card number."})
    return {"ok": not issues, "issues": issues, "needs_adeel": bool(SENSITIVE.search(text))}


def alert_text(kind, company, detail):
    """One-line alert wording (P5: alerts only)."""
    d = detail or {}
    if kind == "draft_held":
        return f"{company}: draft #{d.get('draft')} '{d.get('title', '')}' held by Supervisor: " + "; ".join(i["msg"] for i in d.get("issues", []))
    if kind == "job_error":
        return f"{company}: {d.get('agent')} task '{d.get('task')}' failed: {d.get('error', '')}"
    if kind == "stale":
        return f"{company}: draft #{d.get('draft')} '{d.get('title', '')}' has waited {d.get('days')} days for your decision."
    if kind == "question":
        return f"{company}: Supervisor has a question for you: {d.get('question', '')}"
    return f"{company}: {kind}"


def stale(drafts, today, days=STALE_DAYS):
    """Pending drafts older than `days`. Each draft needs 'id' and 'created' (ISO date or datetime)."""
    out = []
    for d in drafts:
        try:
            age = (today - _date(d["created"])).days
        except (KeyError, ValueError, TypeError):
            continue
        if age >= days:
            out.append(dict(d, days=age))
    return out


def _date(s):
    from datetime import date
    return date.fromisoformat(str(s)[:10])
