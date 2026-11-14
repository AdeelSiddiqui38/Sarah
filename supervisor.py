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
            "Email": "info@apex-physio.ca: reads every 6 h (read-only), files attachments, drafts replies to the outbox",
            "Website": "apex-physio.ca and SEO: changes go PR, then Adeel merges, then upload; Search Console",
            "Marketing": "Local content, Business Profile, reviews",
            "Social media": "Posts (needs the list of APEX social accounts)",
            "Coordinator": "Reminders, scheduling, follow-ups",
            "Administration": "Company records, renewals, condo and vendor admin",
        },
    },
    "Trading Command Center": {
        "match": r"trading",
        "identifiers": ["trading command center", "trading-command-center", "paperbot", "paper bot"],
        # Own agent set: this company does not use the generic business agents (Adeel, Nov 14 2026)
        "own_agents": True,
        "agents": {
            "Gappers Scanner": "Pre-market gap scan, Ross Cameron 5 pillars (price, float, relative volume, % gain, news); top gappers to the watchlist",
            "Watchlist & Catalysts": "Daily watchlist, news catalysts and upcoming events for the names in play",
            "Market Research": "Market wrap, quick takes, earnings setups and recaps for watchlist names",
            "Paper Bots": "paperbot, leverage, momentum and tactical bots; paper money only, never real orders",
            "Telegram Signals": "Telegram channel listener: parses text, voice notes and screenshots into paper trade ideas",
            "Journal & Risk": "Trade journal, weekly execution sheet rules (A+ setups, max loss, stop after 2 losses), candlestick review",
            "Strategy Lab": "Backtests (ORB small caps, pairs, trend/mean-reversion), replay tools, Vibe-Trading and the signal agent",
        },
        # Claude skills each agent uses when Claude works on this company (names as listed in Claude)
        "skills": {
            "Gappers Scanner": ["bigdata-com:bigdata-screen", "bigdata-com:bigdata-catalysts", "bigdata-com:bigdata-stock-move"],
            "Watchlist & Catalysts": ["bigdata-com:bigdata-watchlist", "bigdata-com:bigdata-catalysts", "bigdata-com:bigdata-company-brief"],
            "Market Research": ["bigdata-com:bigdata-markets-today", "bigdata-com:bigdata-quick-take", "bigdata-com:bigdata-earnings-preview",
                                "bigdata-com:bigdata-earnings-recap", "bigdata-com:bigdata-sector", "bigdata-com:bigdata-theme"],
            "Paper Bots": ["bigdata-com:bigdata-stock-move"],
            "Telegram Signals": ["bigdata-com:bigdata-stock-move", "bigdata-com:bigdata-quick-take"],
            "Journal & Risk": ["bigdata-com:bigdata-risk"],
            "Strategy Lab": ["bigdata-com:bigdata-screen", "bigdata-com:bigdata-valuation"],
        },
    },
    "Remedy Pills": {
        "match": r"remedy",
        "identifiers": ["remedy pills", "remedypills", "remedypillspharmacy"],
        "agents": {
            "Finance": "Ledger, statements, CRA records, vendor invoices (weekly and monthly)",
            "Email": "remedypillspharmacy@gmail.com invoice intake",
            "Website": "remedypills.ca (WordPress) checks",
            "Marketing": "Weekly marketing brief",
            "Social media": "Weekly Facebook, Instagram and Nextdoor drafts",
            "Coordinator": "Reminders, scheduling, follow-ups",
            "Administration": "Company records and renewals",
        },
    },
}

SENSITIVE = re.compile(r"\b(send|sent to|pay|payment|e-?transfer|wire|publish|post (it|this|to)|delete|cancel|sign)\b", re.I)
PASSWORD = re.compile(r"\b(password|passcode|app password|pin)\s*[:=]\s*\S+", re.I)
SIN = re.compile(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b")
ACCOUNT = re.compile(r"\b(account|acct|a/c)\s*(no\.?|number|#)?\s*[:#]?\s*\d{5,}\b", re.I)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def agents_for(company, default):
    """The agent switches a company gets: its own set, or Sarah's default business agents."""
    c = COMPANIES.get(company or "")
    return list(c["agents"]) if c and c.get("own_agents") else list(default)


def skills_for(company, agent):
    return list(COMPANIES.get(company or "", {}).get("skills", {}).get(agent, []))


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
    if kind == "bot":
        return f"{company}: {d.get('text', '')}"
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
