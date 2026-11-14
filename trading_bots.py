"""Trading Command Center (Slot 03): read-only view of the paper-trading bots.

The bots themselves run in their own NAS app (trading-hub, see deploy/truenas-trading-hub.yaml) and write their
portfolio and log files into the company folder. Sarah only READS those files (her /projects mount is read-only):
she never starts, stops or changes a bot, and nothing here can place an order. Paper money only.
"""
import json
import math
import os
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001  (no tz database: fall back to a fixed offset)
    ET = timezone(timedelta(hours=-5))

BOTS = {
    "momentum": {"label": "Small-cap momentum (Gap & Go)", "portfolio": "momentum_portfolio.json", "log": "momentum_bot.log"},
    "tactical": {"label": "Tactical 5-asset trend sleeve", "portfolio": "tactical_portfolio.json", "log": "tactical_bot.log"},
}
MOMENTUM_WINDOW = (dtime(7, 0), dtime(11, 30))   # ET, weekdays: the bot scans about every 5 minutes
SILENT_MINUTES = 30


def bot_dir(folder):
    return Path(folder or "") / "trading-paperbot"


def _num(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _read(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _tail(path, n=5):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return [l[:240] for l in lines if l.strip()][-n:]
    except OSError:
        return []


def _mtime(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    except OSError:
        return None


def momentum_summary(pf):
    pf = pf or {}
    closed = pf.get("closed_trades") or []
    pnl = [_num(t.get("pnl")) for t in closed]
    pnl = [x for x in pnl if x is not None]
    day = pf.get("day") or {}
    return {"cash": _num(pf.get("cash")), "starting_cash": _num(pf.get("starting_cash")),
            "open_positions": len(pf.get("open_positions") or []), "closed_trades": len(closed),
            "realized": round(sum(pnl), 2), "wins": sum(1 for x in pnl if x > 0),
            "day": {"date": day.get("date"), "realized": _num(day.get("realized")), "halted": day.get("halted") or "",
                    "traded": list(day.get("traded") or [])},
            "last_trades": [{k: t.get(k) for k in ("symbol", "qty", "entry", "exit", "opened_at", "closed_at", "pnl", "r_multiple", "close_reason") if k in t}
                            for t in closed[-5:]]}


def tactical_summary(pf):
    pf = pf or {}
    curve = pf.get("equity_curve") or []
    last = curve[-1] if curve else {}
    equity = _num(last.get("equity"))
    start = _num(pf.get("starting_cash")) or 10000.0
    bad = any(_num(q) is None for q in (pf.get("positions") or {}).values()) or (bool(curve) and equity is None)
    return {"equity": equity, "starting_cash": start, "as_of": last.get("date"),
            "return_pct": round((equity / start - 1) * 100, 2) if equity else None,
            "positions": {s: q for s, q in (pf.get("positions") or {}).items()},
            "pending": pf.get("pending"), "last_processed": pf.get("last_processed"),
            "rebalances": len(pf.get("rebalances") or []), "data_problem": bad}


def status(folder, now=None):
    """Both bots' accounts and last log lines, read from the company folder."""
    d = bot_dir(folder)
    now = now or datetime.now(timezone.utc)
    out = {"folder": str(d), "found": d.is_dir(), "paper_only": True, "bots": {}}
    for name, b in BOTS.items():
        pf = _read(d / b["portfolio"])
        seen = _mtime(d / b["log"])
        out["bots"][name] = {
            "label": b["label"], "has_account": pf is not None,
            "account": (momentum_summary if name == "momentum" else tactical_summary)(pf),
            "last_log_at": seen.isoformat(timespec="seconds") if seen else None,
            "minutes_since_log": int((now - seen).total_seconds() // 60) if seen else None,
            "recent_log": _tail(d / b["log"]),
        }
    return out


def problems(st, now=None):
    """What the Trading Supervisor should alert on. Returns [(ref, text)]; empty when all is well."""
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(ET)
    out = []
    if not st.get("found"):
        return [("bots:folder", "The trading-paperbot folder is missing from the company folder.")]
    m = st["bots"]["momentum"]
    in_window = et.weekday() < 5 and MOMENTUM_WINDOW[0] <= et.time() <= MOMENTUM_WINDOW[1]
    if in_window and (m["minutes_since_log"] is None or m["minutes_since_log"] > SILENT_MINUTES):
        out.append((f"bots:momentum-silent:{et.date()}",
                    f"Momentum paper bot has been silent for {m['minutes_since_log']} min inside its trading window. "
                    "Check the trading-hub app on the NAS."))
    t = st["bots"]["tactical"]["account"]
    if t.get("data_problem"):
        out.append(("bots:tactical-data", "Tactical paper sleeve has invalid (NaN) values in its account. It needs a reset."))
    elif t.get("last_processed") and et.weekday() < 5:
        try:
            age = (et.date() - datetime.fromisoformat(t["last_processed"]).date()).days
        except ValueError:
            age = 0
        if age > 4:
            out.append((f"bots:tactical-stale:{t['last_processed']}",
                        f"Tactical paper sleeve has not processed a trading day since {t['last_processed']}."))
    return out
