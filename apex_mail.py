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
    save_err = None
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
                    ok = True
                    for fn, blob in atts:
                        try:
                            apex_vendors.save_upload_bytes(folder, f"{summ['from'] or 'mail'} {fn}", blob)
                            new_files += 1
                        except ValueError:
                            pass  # unusable attachment (empty/too big): skip it
                        except OSError:
                            ok = False  # folder not writable yet: retry on the next check
                            save_err = "Could not save attachments (the Vendor Invoices folder is not writable yet)."
                    if ok:
                        filed.add(summ["mid"])
                summ["new"] = summ["mid"] not in seen
                seen[summ["mid"]] = summ
        finally:
            try:
                M.logout()
            except Exception:
                pass
        st["error"] = save_err
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
        "outbox": outbox_view(ddir),
    }


# ---------------------------------------------------------------- outbox: send ONLY after Adeel approves each message
import re
import smtplib
import uuid
from email.message import EmailMessage

SMTP_HOST = os.environ.get("SARAH_APEX_MAIL_SMTP_HOST", HOST)
SMTP_PORT = int(os.environ.get("SARAH_APEX_MAIL_SMTP_PORT", "465"))
OUTBOX = "apex-outbox.json"
MAX_ATTACH = 20 * 1024 * 1024
ADDR = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _out_path(ddir):
    return Path(ddir) / OUTBOX


def load_outbox(ddir):
    try:
        return json.loads(_out_path(ddir).read_text("utf-8")).get("items", [])
    except (OSError, ValueError):
        return []


def _save_outbox(ddir, items):
    p = _out_path(ddir)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps({"items": items[-100:]}, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _addrs(v):
    out = []
    for a in (v if isinstance(v, list) else re.split(r"[,;\s]+", str(v or ""))):
        a = str(a).strip()
        if a:
            if not ADDR.match(a) or len(a) > 120:
                raise ValueError(f"Not a valid email address: {a[:60]}")
            out.append(a)
    return out[:10]


def create_outbox(ddir, to, cc, subject, body, attach=None, item_id=None, by="adeel"):
    """Save an email as a DRAFT. Nothing is sent until send_outbox() is called after Adeel approves."""
    to, cc = _addrs(to), _addrs(cc)
    subject = " ".join(str(subject or "").split())[:200]
    body = str(body or "").replace("\r", "")[:20000]
    if not to or not subject or not body.strip():
        raise ValueError("A recipient, subject and message are required.")
    att = []
    for a in (attach or [])[:5]:
        uid, name = str(a.get("uid", ""))[:20], str(a.get("name", ""))[:120]
        if not uid.isdigit() or not name:
            raise ValueError("Bad attachment.")
        att.append({"uid": uid, "name": name})
    items = load_outbox(ddir)
    if item_id:
        it = next((i for i in items if i["id"] == item_id and i["status"] == "draft"), None)
        if not it:
            raise ValueError("That draft can no longer be edited.")
        it.update({"to": to, "cc": cc, "subject": subject, "body": body, "attach": att})
    else:
        items.append({"id": uuid.uuid4().hex[:10], "status": "draft", "to": to, "cc": cc, "subject": subject, "body": body,
                      "attach": att, "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "by": by, "error": None})
        item_id = items[-1]["id"]
    _save_outbox(ddir, items)
    return item_id


def discard_outbox(ddir, item_id):
    items = load_outbox(ddir)
    it = next((i for i in items if i["id"] == item_id and i["status"] in ("draft", "failed")), None)
    if not it:
        raise ValueError("Nothing to discard.")
    it["status"] = "discarded"
    _save_outbox(ddir, items)


def _fetch_attachment(M, uid, name):
    typ, d = M.uid("FETCH", uid, "(BODY.PEEK[])")
    if typ != "OK" or not d or not isinstance(d[0], tuple):
        raise ValueError("Could not find that attachment in the mailbox.")
    msg = email.message_from_bytes(d[0][1], policy=email.policy.default)
    for part in msg.iter_attachments():
        if (part.get_filename() or "") == name:
            data = part.get_payload(decode=True) or b""
            if not data or len(data) > MAX_ATTACH:
                raise ValueError("Attachment is empty or larger than 20 MB.")
            return data, part.get_content_type()
    raise ValueError("Could not find that attachment in the mailbox.")


def send_outbox(ddir, item_id, imap_factory=None, smtp_factory=None):
    """SEND one approved draft. Called only from the explicit 'Approve & send' action."""
    items = load_outbox(ddir)
    it = next((i for i in items if i["id"] == item_id), None)
    if not it or it["status"] not in ("draft", "failed"):
        raise ValueError("That email was already sent or discarded.")
    if not configured() and not (imap_factory and smtp_factory):
        raise ValueError("Mailbox password is not set on the server.")
    it["status"] = "sending"      # blocks a double click
    _save_outbox(ddir, items)
    try:
        msg = EmailMessage()
        msg["From"] = f"APEX Physio and Wellness <{USER}>"
        msg["To"] = ", ".join(it["to"])
        if it["cc"]:
            msg["Cc"] = ", ".join(it["cc"])
        msg["Subject"] = it["subject"]
        msg["Date"] = email.utils.formatdate(localtime=False)
        msg["Message-ID"] = email.utils.make_msgid(domain=USER.split("@")[1])
        msg.set_content(it["body"])
        if it["attach"]:
            M = imap_factory() if imap_factory else imaplib.IMAP4_SSL(HOST, PORT, timeout=TIMEOUT)
            try:
                if not imap_factory:
                    M.login(USER, os.environ["SARAH_APEX_MAIL_PASS"])
                M.select("INBOX", readonly=True)
                for a in it["attach"]:
                    data, ctype = _fetch_attachment(M, a["uid"], a["name"])
                    mt, _, st = ctype.partition("/")
                    msg.add_attachment(data, maintype=mt or "application", subtype=st or "octet-stream", filename=a["name"])
            finally:
                try:
                    M.logout()
                except Exception:
                    pass
        S = smtp_factory() if smtp_factory else smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT)
        try:
            if not smtp_factory:
                S.login(USER, os.environ["SARAH_APEX_MAIL_PASS"])
            S.send_message(msg, from_addr=USER, to_addrs=it["to"] + it["cc"])
        finally:
            try:
                S.quit()
            except Exception:
                pass
        it["status"], it["error"] = "sent", None
        it["sent"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OSError, smtplib.SMTPException, imaplib.IMAP4.error) as e:
        it["status"] = "failed"
        it["error"] = str(e)[:160]      # message only, never credentials
    _save_outbox(ddir, items)
    if it["status"] == "failed":
        raise ValueError("Not sent: " + (it["error"] or "unknown error"))
    return it


def outbox_view(ddir):
    return [i for i in load_outbox(ddir) if i["status"] in ("draft", "failed", "sending")] + \
           [i for i in load_outbox(ddir) if i["status"] == "sent"][-5:]
