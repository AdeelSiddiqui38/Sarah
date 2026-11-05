"""Read-only IMAP access to the APEX info mailbox.

Sarah only reads: it selects INBOX read-only and fetches with BODY.PEEK, so
nothing is marked read, moved or deleted. Invoice attachments (PDF/photos) are
copied into the Vendor Invoices Inbox; Adeel then files them from the APEX page.
The password comes from the environment only and is never stored or logged.
"""
import email
import email.policy
import email.utils
import imaplib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import apex_vendors

HOST = os.environ.get("SARAH_APEX_MAIL_HOST", "mail.apex-physio.ca")
PORT = int(os.environ.get("SARAH_APEX_MAIL_PORT", "993"))
USER = os.environ.get("SARAH_APEX_MAIL_USER", "info@apex-physio.ca")
KEEP = 60          # messages remembered for the page
FETCH_LAST = 40    # newest messages examined per check
TIMEOUT = 30
STATE = "apex-mail.json"


def configured():
    return bool(os.environ.get("SARAH_APEX_MAIL_PASS"))


def _state_path(ddir):
    return Path(ddir) / STATE


def load(ddir):
    try:
        return json.loads(_state_path(ddir).read_text("utf-8"))
    except (OSError, ValueError):
        return {"messages": [], "filed": [], "checked": None, "error": None}


def _save(ddir, st):
    p = _state_path(ddir)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(st, indent=1), "utf-8")
    tmp.replace(p)


def _snippet(msg):
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        text = part.get_content() if part else ""
    except Exception:
        text = ""
    return " ".join(str(text).split())[:240]


def parse_message(raw, uid):
    """Return (summary dict, [(filename, bytes)]) for one RFC822 message."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, addr = email.utils.parseaddr(str(msg.get("From", "")))
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        when = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        when = ""
    atts = []
    for part in msg.iter_attachments():
        fn = part.get_filename() or ""
        if Path(fn).suffix.lower() in apex_vendors.EXTS:
            data = part.get_payload(decode=True) or b""
            if data:
                atts.append((fn, data))
    summ = {
        "uid": str(uid),
        "mid": str(msg.get("Message-ID", "")).strip()[:200] or f"uid-{uid}",
        "from": (name or addr)[:80],
        "addr": addr[:120],
        "subject": str(msg.get("Subject", "(no subject)"))[:160],
        "date": when,
        "snippet": _snippet(msg),
        "attachments": [a[0][:100] for a in atts],
    }
    return summ, atts


def check(folder, ddir, imap_factory=None):
    """Read newest mail, file new invoice attachments, remember a summary."""
    st = load(ddir)
    if not configured() and imap_factory is None:
        st["error"] = "Mailbox password not set on the server."
        return st
    seen = {m["mid"]: m for m in st.get("messages", [])}
    filed = set(st.get("filed", []))
    new_files = 0
    try:
        if imap_factory:
            M = imap_factory()
        else:
            M = imaplib.IMAP4_SSL(HOST, PORT, timeout=TIMEOUT)
            M.login(USER, os.environ["SARAH_APEX_MAIL_PASS"])
        try:
            typ, _ = M.select("INBOX", readonly=True)
            if typ != "OK":
                raise imaplib.IMAP4.error("could not open INBOX")
            typ, data = M.uid("SEARCH", None, "ALL")
            uids = (data[0].split() if typ == "OK" and data and data[0] else [])[-FETCH_LAST:]
            for uid in uids:
                u = uid.decode() if isinstance(uid, bytes) else str(uid)
                typ, d = M.uid("FETCH", u, "(BODY.PEEK[])")
                if typ != "OK" or not d or not isinstance(d[0], tuple):
                    continue
                summ, atts = parse_message(d[0][1], u)
                if summ["mid"] in filed:
                    pass
                else:
                    for fn, blob in atts:
                        try:
                            apex_vendors.save_upload_bytes(folder, f"{summ['from'] or 'mail'} {fn}", blob)
                            new_files += 1
                        except (ValueError, OSError):
                            raise
                    filed.add(summ["mid"])
                summ["new"] = summ["mid"] not in seen
                seen[summ["mid"]] = summ
        finally:
            try:
                M.logout()
            except Exception:
                pass
        st["error"] = None
    except (imaplib.IMAP4.error, OSError) as e:
        # message only, never the credentials
        st["error"] = "Mailbox check failed: " + str(e)[:120]
    msgs = sorted(seen.values(), key=lambda m: m.get("date", ""), reverse=True)[:KEEP]
    st["messages"] = msgs
    st["filed"] = sorted(filed)[-500:]
    st["checked"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st["new_files"] = new_files
    try:
        _save(ddir, st)
    except OSError:
        st["error"] = (st.get("error") or "") + " (could not save mail state)"
    return st


def summary(ddir):
    st = load(ddir)
    return {
        "configured": configured(),
        "host": HOST,
        "user": USER,
        "checked": st.get("checked"),
        "error": st.get("error"),
        "messages": st.get("messages", [])[:30],
        "with_attachments": sum(1 for m in st.get("messages", []) if m.get("attachments")),
    }
