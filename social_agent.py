"""Social media agent for a Sarah project (draft-only).

Every week it prepares ready-to-paste posts for Facebook, Instagram and Nextdoor and leaves them as ONE draft for the owner's
approval. It never logs in anywhere and never posts. Posts are built only from the verified FACTS below (no invented claims, no
testimonials), and every post is run through the wording guard first.
"""
import re
from datetime import datetime, timedelta

import marketing_agent as mk

FACTS = {
    "name": "Remedy Pills Pharmacy",
    "area": "Nolan Hill, NW Calgary",
    "address": "Unit 135, 246 Nolanridge Crescent NW, Calgary",
    "phone": "(403) 980-7003",
    "site": "remedypills.ca",
    "hours": "Mon-Fri 9-5, Sat 10-3, Sun closed",
    "delivery_areas": "NW Calgary neighbourhoods, Airdrie, Cochrane, Chestermere and Okotoks",
    "review_link": "https://search.google.com/local/writereview?placeid=ChIJHS1OYp9pcVMROTz9NNxuIrQ",
}

# One short, factual spotlight per service (all claims come from the owner's rules and the flyer).
SERVICES = [
    ("delivery", "Free prescription delivery",
     "Can't get out? We deliver prescriptions free to {delivery_areas}."),
    ("blister", "Free blister packs",
     "Blister packs make taking several medications easier, and they are free for all our patients. Ask us about getting started."),
    ("prescribing", "Prescribing pharmacist",
     "Our prescribing pharmacist can help with refills and certain minor conditions. Call us to ask whether it fits your situation."),
    ("transfer", "Easy prescription transfers",
     "Switching pharmacies is simple: tell us where your prescriptions are now and we take care of the transfer."),
    ("strep", "Strep testing on site",
     "Sore throat? We offer strep testing on site. Call ahead so we can tell you what to expect."),
    ("vaccines", "Vaccinations and injections",
     "Vaccinations and injections are available at the pharmacy. Ask us what you may be eligible for."),
    ("review", "Medication reviews",
     "A medication review is a chance to go through everything you take with a pharmacist. Ask us for one next time you pick up."),
    ("aadl", "AADL supplies",
     "We carry AADL supplies. Stop by or call and we will help you with what you need."),
]

SEASONAL = {
    1: "New year, a good time to ask your pharmacist for a medication review. Walk in or call us.",
    2: "Planning spring travel? Ask us early about travel vaccines and what you may need.",
    3: "Allergy season is starting. Our pharmacists can help you choose over-the-counter options, just ask.",
    4: "Spring clean-out: bring unused or expired medications to us for safe disposal.",
    5: "Sun season: ask us for help picking sunscreen and other summer essentials.",
    6: "Travelling this summer? Talk to us about travel health before you go.",
    7: "Hot days: remember to store medications as the label says, and keep them out of a hot car.",
    8: "Back to school: ask us about vaccines and keeping prescriptions on schedule.",
    9: "Flu shot season is here. Walk in, no appointment needed.",
    10: "Flu shots: walk in, no appointment needed. We are in Nolan Hill.",
    11: "Flu shots are available, walk in with no appointment. Heading away for the holidays? Order repeat prescriptions early.",
    12: "Holiday reminder: order repeat prescriptions early so you are covered. Flu shots still available.",
}

OFFER = ("Save 15% every day on all OTC products at {name}. Free prescription delivery, free blister packs, "
         "price match guarantee and on-site strep testing. Promotion applies to OTC products only.")

CYCLE = ["seasonal", "service", "offer", "review_ask"]
HASHTAGS = "#NolanHill #NWCalgary #Calgary #YYC #CalgaryPharmacy #RemedyPills"

# Extra words that Meta / pharmacy rules dislike in social posts.
SOCIAL_RISKY = [(r"cheap (meds|drugs|pills)", "'cheap meds' style wording"), (r"no prescription (needed|required)", "implies no prescription needed"),
                (r"\bbuy (opioids|oxycodone|fentanyl)\b", "controlled-substance wording")]


def _fmt(t):
    return t.format(**FACTS)


def pick_pillar(week_no):
    return CYCLE[week_no % 4]


def pick_service(week_no):
    return SERVICES[(week_no // 4 + week_no) % len(SERVICES)]


def offer_active(offer_end, today=None):
    today = today or datetime.now()
    if not offer_end or offer_end == "none":
        return True
    try:
        return today.date() <= datetime.strptime(offer_end, "%Y-%m-%d").date()
    except ValueError:
        return True


def core_text(pillar, today, service=None):
    """The one plain sentence (or two) that every channel is built from."""
    if pillar == "seasonal":
        return SEASONAL[today.month], "Seasonal health reminder"
    if pillar == "offer":
        return _fmt(OFFER), "Offer (use the English flyer image)"
    if pillar == "review_ask":
        return ("If we have looked after you, a short Google review helps your neighbours find a pharmacy they can trust. "
                "Thank you!"), "Review request"
    key, label, text = service
    return _fmt(text), f"Service spotlight: {label}"


def build_posts(pillar, today, service=None):
    text, label = core_text(pillar, today, service)
    contact = f"{FACTS['address']} | {FACTS['phone']} | {FACTS['site']}"
    review = f"\nLeave a review: {FACTS['review_link']}" if pillar == "review_ask" else ""
    posts = {
        "Facebook": f"{text}\n\n{FACTS['name']}, {FACTS['area']}\n{contact}\nHours: {FACTS['hours']}{review}",
        "Instagram": f"{text}\n\n{FACTS['name']} in {FACTS['area']}.\nCall {FACTS['phone']} or visit {FACTS['site']} (link in bio).\n"
                     f"Hours: {FACTS['hours']}\n\n{HASHTAGS}",
        "Nextdoor": f"Hi neighbours! {text}\n\nWe are at {FACTS['address']}. Hours: {FACTS['hours']}. {FACTS['phone']}.\n"
                    f"- The team at {FACTS['name']}{review}",
    }
    flags = {}
    for ch, body in posts.items():
        f = mk.wording_flags(body, "any") + [lbl for pat, lbl in _social_hits(body)]
        if f:
            flags[ch] = sorted(set(f))
    return label, posts, flags


def _social_hits(text):
    return [(p, l) for p, l in SOCIAL_RISKY if re.search(p, text, re.I)]


IMAGE_HINT = {
    "offer": "Image: the English flyer (remedypills.ca/current-offers/ has the file).",
    "seasonal": "Image: a simple flu-shot or seasonal graphic from Canva, or a storefront photo.",
    "review_ask": "Image: a photo of the pharmacy counter or team (with permission from anyone shown).",
    "service": "Image: a clean photo of the pharmacy or the service (no patient faces or labels).",
}


def build_brief(pillar, label, posts, flags, google_blocked, today=None):
    today = today or datetime.now()
    week = today - timedelta(days=today.weekday())
    L = [f"Weekly social drafts, week of {week.strftime('%b %d, %Y')} ({FACTS['name']})",
         "Draft-only: nothing was posted. Copy each post, add the image, and post it yourself until Instagram and Nextdoor are connected.",
         "", f"Topic: {label}", IMAGE_HINT["service" if pillar not in IMAGE_HINT else pillar], "Best times: Facebook and Instagram weekday evenings; Nextdoor mid-morning.", ""]
    for ch, body in posts.items():
        L += [f"--- {ch} ---", body, ""]
    if flags:
        L.append("Wording to check before posting:")
        L += [f"- {ch}: {', '.join(f)}" for ch, f in flags.items()]
        L.append("")
    L.append("Rules used: facts only from your approved list, no testimonials, no medical advice, no patient information.")
    if google_blocked:
        L.append("Google Business Profile posting is switched off, so there is no Google version this week.")
    return "\n".join(L)
