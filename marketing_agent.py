"""Marketing agent for a Sarah project (draft-only).

What it does (read-only, nothing is published or sent):
  * checks the live website against the owner's rules (naming, phone, address, banned claims, basic SEO tags),
  * flags wording that Google or health regulators dislike before anything is drafted,
  * keeps a monthly metrics log (Search Console / GA4 / Google Business Profile numbers pasted in by the owner),
  * suggests seasonal promo ideas,
  * turns all of that into ONE weekly brief that waits for the owner's approval.

It never logs in anywhere and never posts. Pure functions take their I/O as arguments so they can be tested offline.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta

SITE = "https://remedypills.ca"
PAGES = [
    ("/", "Home"),
    ("/prescribing-pharmacist/", "Prescribing pharmacist"),
    ("/prescription-refill/", "Prescription refill"),
    ("/transfer-prescription/", "Transfer prescription"),
    ("/request-delivery/", "Delivery"),
    ("/request-blister-packs/", "Blister packs"),
    ("/book-prescribing-consult/", "Book consult"),
    ("/current-offers/", "Current offers"),
]

# Owner rules. Edit here (or ask Claude to) - this is the single source for the agent.
RULES = {
    "business": "Remedy Pills Pharmacy",
    "phone_digits": "4039807003",          # compared after stripping everything that is not a digit
    "address_bits": ["246 Nolanridge", "T3R"],  # at least the street must appear on the contact/footer area of the home page
    "neighbourhood": "Nolan Hill",
    "must_not_contain": [
        ("nolan ridge", "Use 'Nolan Hill' (the street 'Nolanridge Crescent' stays as is)."),
        ("nolannridge", "Typo in the street name; it is 'Nolanridge'."),
        ("nationwide", "Old wording: Remedy Pills has one location."),
        ("alberta health care coverage", "Coverage claim was removed on purpose."),
        ("covered by alberta health", "Coverage claim was removed on purpose."),
        ("guaranteed results", "Unsupported health claim."),
        ("cure", "Avoid 'cure' claims (health regulator wording)."),
    ],
    "hours_text": ["9", "5"],               # weekday hours should still mention 9 and 5 wherever hours are shown
}

# Words that make Google Business Profile reject pharmacy posts (learned Nov 2026: flyer post rejected, posting switched off).
GOOGLE_RISKY = [
    (r"\d+\s*%", "a percentage discount"), (r"\bdiscount", "'discount'"), (r"\bsave\b", "'save'"), (r"\bfree\b", "'free'"),
    (r"price match", "'price match'"), (r"guarantee", "'guarantee'"), (r"\bbest\b|\bcheapest\b|#1", "superlatives"),
    (r"weight (loss|management)", "weight-loss wording"), (r"\bprescription\b.*\b(deal|offer|special)", "prescription deals"),
]
ANY_RISKY = [
    (r"\bcure[sd]?\b", "'cure' claim"), (r"100\s*%\s*(safe|effective)", "absolute safety/efficacy claim"),
    (r"no side effects", "'no side effects'"),
]

SEASONS = {
    1: ["Travel-health consults for spring break and reading week", "New-year medication review and blister-pack sign-ups"],
    2: ["Travel vaccines before spring travel", "Cold/flu aftercare: OTC essentials"],
    3: ["Allergy season: OTC antihistamines and a pharmacist chat", "Travel vaccines"],
    4: ["Allergy season", "Spring clean-out: safe medication disposal"],
    5: ["Sun safety: sunscreen and OTC", "Travel-health consults for summer"],
    6: ["Travel-health consults", "Summer first-aid kit checklist"],
    7: ["Travel-health consults", "Heat safety and medication storage"],
    8: ["Back-to-school: vaccines, vitamins, medication reviews", "Prepare for flu season"],
    9: ["Flu shot season starts: walk-in, no appointment", "Back-to-routine blister packs"],
    10: ["Flu shots (walk-in)", "Cold and flu OTC shelf", "Medication review before winter"],
    11: ["Flu shots (walk-in)", "Holiday travel vaccines", "Order repeat prescriptions before the holiday closures"],
    12: ["Holiday hours and refill reminders", "Last chance flu shot", "Year-end: use benefits (pharmacy care services)"],
}


# --------------------------------------------------------------------------- helpers
def digits(s):
    return re.sub(r"\D", "", s or "")


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Sarah-Marketing/1.0 (+read-only check)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:120]


def visible_text(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


def wording_flags(text, channel="any"):
    """Return a list of plain-English warnings for a draft's wording."""
    out = []
    pats = ANY_RISKY + (GOOGLE_RISKY if channel == "google" else [])
    for pat, label in pats:
        if re.search(pat, text or "", re.I):
            out.append(label)
    return sorted(set(out))


# --------------------------------------------------------------------------- website check
def check_page(path, label, status, html, rules=RULES):
    """Return {'page','ok','issues'} for one page. Issues are short strings."""
    issues = []
    if status != 200:
        return {"page": label, "path": path, "ok": False, "issues": [f"Page did not load (HTTP {status or 'no answer'})."]}
    low = html.lower()
    text = visible_text(html)
    tl = text.lower()
    for bad, why in rules["must_not_contain"]:
        if re.search(r"\b" + re.escape(bad) + r"\b", tl):
            issues.append(f"Contains '{bad}': {why}")
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not (m and m.group(1).strip()):
        issues.append("Missing page title.")
    if not re.search(r'(?i)<meta[^>]+name=["\']description["\'][^>]+content=["\'][^"\']{30,}', html) and \
       not re.search(r'(?i)<meta[^>]+content=["\'][^"\']{30,}["\'][^>]+name=["\']description', html):
        issues.append("Missing or very short meta description.")
    if re.search(r'(?i)<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex', html):
        issues.append("Page is set to noindex (Google will not list it).")
    n_img = len(re.findall(r"(?i)<img\b", html))
    n_noalt = len(re.findall(r'(?i)<img\b(?![^>]*\balt=["\'][^"\']+["\'])[^>]*>', html))
    if n_img and n_noalt > max(3, n_img // 3):
        issues.append(f"{n_noalt} of {n_img} images have no alt text.")
    if rules["phone_digits"] not in digits(text) and path in ("/", "/request-delivery/", "/book-prescribing-consult/", "/current-offers/"):
        issues.append("Main phone number (403) 980-7003 not found on the page.")
    if path == "/" and rules["neighbourhood"].lower() not in tl and rules["neighbourhood"].lower() not in low:
        issues.append("Home page never says 'Nolan Hill'.")
    return {"page": label, "path": path, "ok": not issues, "issues": issues}


def check_site(fetcher=fetch, site=SITE, pages=PAGES):
    return [check_page(path, label, *fetcher(site + path)) for path, label in pages]


def offer_banner_state(home_html, offer_end):
    """Is the site-wide offer bar on? Is it past its end date?"""
    on = "rp-offer-bar" in (home_html or "")
    if not on:
        return None
    if offer_end:
        try:
            if datetime.now().date() > datetime.strptime(offer_end, "%Y-%m-%d").date():
                return f"Offer bar is still showing but the offer ended {offer_end}. Remove rp-offer-banner.php or extend the offer."
        except ValueError:
            return f"Offer end date '{offer_end}' is not YYYY-MM-DD."
    return None


# --------------------------------------------------------------------------- metrics
METRIC_FIELDS = ["clicks", "impressions", "avg_position", "ga_users", "reviews", "rating", "gbp_views", "gbp_calls", "gbp_directions"]


def add_metrics(existing, entry, today=None):
    """Append a snapshot (numbers only) and keep the last 24."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    row = {"date": entry.get("date") or today}
    for k in METRIC_FIELDS:
        v = entry.get(k)
        if v in (None, ""):
            continue
        try:
            row[k] = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k} must be a number")
    if len(row) == 1:
        raise ValueError("No numbers given.")
    rows = [r for r in existing if r.get("date") != row["date"]] + [row]
    return sorted(rows, key=lambda r: r["date"])[-24:]


def metrics_section(rows, today=None):
    today = today or datetime.now()
    if not rows:
        return ["No numbers saved yet. Send me this month's Search Console (clicks, impressions, avg position), GA4 users, "
                "review count and rating, and Google profile views/calls/directions."]
    last = rows[-1]
    age = (today.date() - datetime.strptime(last["date"], "%Y-%m-%d").date()).days
    lines = []
    prev = rows[-2] if len(rows) > 1 else {}
    for k in METRIC_FIELDS:
        if k in last:
            v = last[k]
            d = f" ({v - prev[k]:+g} vs {prev['date']})" if k in prev else ""
            lines.append(f"- {k.replace('_', ' ')}: {v:g}{d}")
    if age > 35:
        lines.append(f"- These numbers are {age} days old. Please send fresh ones (first Monday of the month).")
    return [f"Latest numbers saved {last['date']}:"] + lines


# --------------------------------------------------------------------------- promo ideas
def promo_ideas(month):
    return SEASONS.get(month, [])


# --------------------------------------------------------------------------- the weekly brief
def build_brief(site_results, metrics_rows, open_items, gbp_blocked, banner_note, pending_drafts, today=None):
    today = today or datetime.now()
    week = today - timedelta(days=today.weekday())
    L = [f"Weekly marketing brief, week of {week.strftime('%b %d, %Y')} (Remedy Pills Pharmacy)",
         "Draft-only: nothing was posted, edited or sent.", ""]
    bad = [r for r in site_results if not r["ok"]]
    L.append("1. Website check")
    if not bad:
        L.append(f"- All {len(site_results)} pages passed (naming, phone, banned claims, titles, indexing).")
    for r in bad:
        for i in r["issues"]:
            L.append(f"- {r['page']} ({r['path']}): {i}")
    if banner_note:
        L.append(f"- {banner_note}")
    L += ["", "2. Numbers"] + metrics_section(metrics_rows, today)
    L += ["", "3. Google Business Profile"]
    if gbp_blocked:
        L.append("- Posting is switched off by Google (policy email, Routing ID DPNB). Do NOT draft Google posts until the appeal succeeds. "
                 "Reviews, photos, hours and Q&A still work.")
    else:
        L.append("- Posting allowed. Keep posts plain: no percentages, 'free', 'guarantee' or discount wording.")
    L += ["", f"4. Ideas for {today.strftime('%B')} (for your approval, none drafted yet)"]
    L += [f"- {i}" for i in promo_ideas(today.month)]
    L += ["", "5. Open marketing items"]
    L += [f"- {i}" for i in (open_items or ["None recorded."])]
    L += ["", f"6. Waiting for your approval: {pending_drafts} draft(s) in total."]
    return "\n".join(L)


DEFAULT_OPEN_ITEMS = [
    "Appeal Google's posting block (Business Profile Help > Contact us, Routing ID DPNB).",
    "Post the offers flyer on Instagram and in WhatsApp/WeChat groups; print the bilingual copy with a review QR.",
    "Review engine: counter QR card, delivery-bag insert, thank-you message that asks every patient for a review.",
    "Star GA4 key events once they appear: whatsapp_click, cta_click, review_click, generate_lead.",
]
