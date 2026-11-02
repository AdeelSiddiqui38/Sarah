"""WordPress access for remedypills.ca (REST API + application password from Sarah's vault).
Read/backup helpers only; edits go through wp_request() and are always audited by the caller."""
import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

SITE = "https://remedypills.ca"


def wp_request(user, pw, method, path, body=None, timeout=40):
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SITE + path, data=data, method=method, headers={
        "Authorization": "Basic " + tok, "Content-Type": "application/json", "User-Agent": "Sarah/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace")), {}
        except ValueError:
            return e.code, None, {}


def test(user, pw):
    st, me, _ = wp_request(user, pw, "GET", "/wp-json/wp/v2/users/me?context=edit")
    if st != 200:
        return {"ok": False, "status": st, "error": (me or {}).get("message", "Login failed")}
    return {"ok": True, "name": me.get("name"), "roles": me.get("roles"), "can_edit": bool((me.get("capabilities") or {}).get("edit_pages"))}


def backup(user, pw, dest):
    """Save every page, post, and category as JSON (raw content included) into dest."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    counts = {}
    for kind in ("pages", "posts", "categories"):
        items, page = [], 1
        while True:
            q = f"/wp-json/wp/v2/{kind}?per_page=100&page={page}&context=edit" + ("&status=any" if kind != "categories" else "")
            st, data, hdr = wp_request(user, pw, "GET", q)
            if st != 200 or not data:
                break
            items += data
            if len(data) < 100:
                break
            page += 1
        (dest / f"{kind}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
        counts[kind] = len(items)
    return counts
