"""Trading Command Center (Slot 03): end-of-day paper trading report.

Built once per US trading day (weekdays, 2:30 PM Calgary = 30 min after the US close) from:
  - the hub's live state (equity AI bot and crypto leverage bot, with live prices), and
  - the bot files in the company folder (momentum, tactical, Telegram/FX journal, gappers).
Day P&L = today's account value minus the value in the previous report (first report: minus the start).
Paper money only. Pure functions so the numbers are easy to test.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    ET = timezone.utc

BOT_LABELS = {"momentum": "Momentum (Gap & Go)", "tactical": "Tactical 5-asset sleeve",
              "equity": "Equity AI (Vibe-Trading)", "leverage": "Crypto leverage (Telegram)"}


def _read(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def _num(x, d=0.0):
    try:
        x = float(x)
        return x if x == x and abs(x) != float("inf") else d
    except (TypeError, ValueError):
        return d


def _day(ts):
    """ISO timestamp -> date in New York time (the trading day it belongs to)."""
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(str(ts)[:10])
        except ValueError:
            return None
    if d.tzinfo is None:
        return d.date()
    return d.astimezone(ET).date()


def snapshot(folder, hub, day):
    """Account value per bot plus today's trades. hub = the hub's /api/state (or {} if unreachable)."""
    bot = Path(folder or "") / "trading-paperbot"
    out = {"date": day.isoformat(), "bots": {}, "hub_ok": bool(hub)}

    m = _read(bot / "momentum_portfolio.json", {}) or {}
    m_open = m.get("open_positions") or []
    m_val = _num(m.get("cash"), 10000.0) + sum(_num(p.get("qty")) * _num(p.get("entry")) for p in m_open)
    m_trades = [t for t in (m.get("closed_trades") or []) if _day(t.get("closed_at")) == day]
    out["bots"]["momentum"] = {"value": round(m_val, 2), "start": _num(m.get("starting_cash"), 10000.0),
                               "open": len(m_open), "halted": (m.get("day") or {}).get("halted") or "",
                               "trades": [{"symbol": t.get("symbol"), "pnl": round(_num(t.get("pnl")), 2),
                                           "r": t.get("r_multiple"), "why": t.get("close_reason")} for t in m_trades]}

    t = _read(bot / "tactical_portfolio.json", {}) or {}
    curve = t.get("equity_curve") or []
    t_val = _num(curve[-1].get("equity"), _num(t.get("starting_cash"), 10000.0)) if curve else _num(t.get("cash"), 10000.0)
    out["bots"]["tactical"] = {"value": round(t_val, 2), "start": _num(t.get("starting_cash"), 10000.0),
                               "holds": sorted((t.get("positions") or {}).keys()), "as_of": curve[-1].get("date") if curve else None,
                               "pending": bool(t.get("pending")),
                               "trades": [{"symbol": "rebalance", "pnl": None, "why": ", ".join(f"{k} {v*100:.0f}%" for k, v in (r.get("weights") or {}).items())}
                                          for r in (t.get("rebalances") or []) if str(r.get("date")) == day.isoformat()]}

    eq = (hub or {}).get("equity")
    if eq is None:
        pf = _read(bot / "portfolio.json", {}) or {}
        eq = {"cash": pf.get("cash", 10000.0), "starting_cash": pf.get("starting_cash", 10000.0),
              "total_value": _num(pf.get("cash"), 10000.0) + sum(_num(p.get("qty")) * _num(p.get("avg_price")) for p in (pf.get("positions") or {}).values()),
              "positions": [{"ticker": k, "qty": v.get("qty"), "upnl": None} for k, v in (pf.get("positions") or {}).items()],
              "trades": list(reversed(pf.get("trades") or []))}
    out["bots"]["equity"] = {"value": round(_num(eq.get("total_value")), 2), "start": _num(eq.get("starting_cash"), 10000.0),
                             "holds": [f"{p.get('ticker')} x{p.get('qty')}" for p in (eq.get("positions") or [])],
                             "unrealized": round(_num(eq.get("unrealized")), 2),
                             "trades": [{"symbol": x.get("ticker"), "side": x.get("action"), "qty": x.get("qty"),
                                         "price": x.get("price"), "pnl": x.get("pnl"), "why": (x.get("reasoning") or "")[:140]}
                                        for x in (eq.get("trades") or []) if _day(x.get("ts")) == day]}

    lv = (hub or {}).get("leverage")
    if lv is None:
        pf = _read(bot / "leverage_portfolio.json", {}) or {}
        lv = {"equity": _num(pf.get("cash"), 10000.0) + sum(_num(p.get("margin")) for p in (pf.get("open_positions") or [])),
              "starting_cash": pf.get("starting_cash", 10000.0), "open": pf.get("open_positions") or [],
              "closed": list(reversed(pf.get("closed_trades") or []))}
    out["bots"]["leverage"] = {"value": round(_num(lv.get("equity")), 2), "start": _num(lv.get("starting_cash"), 10000.0),
                               "holds": [f"{str(p.get('symbol', '')).split('/')[0]} {p.get('side')} {p.get('leverage')}x" for p in (lv.get("open") or [])],
                               "trades": [{"symbol": str(c.get("symbol", "")).split("/")[0], "side": c.get("side"),
                                           "pnl": round(_num(c.get("pnl")), 2), "why": c.get("close_reason")}
                                          for c in (lv.get("closed") or []) if _day(c.get("closed_at") or c.get("exit_time")) == day]}

    gap = (hub or {}).get("gappers") or _read(Path(folder or "") / "trading-hub" / "logs" / "gappers.json", {}) or {}
    rows = sorted(gap.get("rows") or [], key=lambda r: (r.get("score") or 0, r.get("chg") or 0), reverse=True)
    out["ideas"] = [{"ticker": r.get("ticker"), "score": r.get("score"), "chg": round(_num(r.get("chg")), 1),
                     "price": r.get("price"), "news": (r.get("news") or {}).get("title") if isinstance(r.get("news"), dict) else None}
                    for r in rows if (r.get("score") or 0) >= 4][:5]
    sig = (hub or {}).get("signals") or {}
    out["signals"] = {
        "tickers": [s.get("ticker") for s in (sig.get("tickers") or _read(bot / "candidates.json", []) or []) if _day(s.get("received_at")) == day],
        "crypto": [f"{s.get('side', '').upper()} {s.get('symbol')}" for s in (sig.get("leverage") or _read(bot / "leverage_candidates.json", []) or [])
                   if _day(s.get("received_at") or s.get("ts")) == day],
        "fx": [f"{(s.get('side') or '').upper()} {s.get('symbol')} ({s.get('channel')})" for s in (_read(bot / "fx_signals.json", []) or [])
               if _day(s.get("ts")) == day]}
    return out


def build(snap, prev=None):
    """Report dict + plain-text body. prev = the previous report's snapshot (None on the first report)."""
    rows, total_day, total_val, total_start = [], 0.0, 0.0, 0.0
    for key in ("momentum", "tactical", "equity", "leverage"):
        b = snap["bots"][key]
        base = ((prev or {}).get("bots", {}).get(key) or {}).get("value")
        base = _num(base, b["start"]) if base is not None else b["start"]
        day_pl = round(b["value"] - base, 2)
        rows.append({"bot": key, "label": BOT_LABELS[key], "value": b["value"], "day_pl": day_pl,
                     "since_start": round(b["value"] - b["start"], 2), "trades": len(b["trades"])})
        total_day += day_pl
        total_val += b["value"]
        total_start += b["start"]
    summary = {"date": snap["date"], "day_pl": round(total_day, 2), "value": round(total_val, 2),
               "since_start": round(total_val - total_start, 2), "first": prev is None, "rows": rows}
    return summary, text(snap, summary)


def _m(x):
    return ("-" if x < 0 else "+") + f"${abs(x):,.2f}"


def text(snap, s):
    d = datetime.fromisoformat(snap["date"]).strftime("%a %b %d, %Y")
    out = [f"Trading Command Center - daily paper report, {d}", "PAPER MONEY ONLY. Not financial advice.", "",
           f"TODAY: {_m(s['day_pl'])}   |   All bots: ${s['value']:,.2f}   |   Since start: {_m(s['since_start'])}"
           + ("   (first report: 'today' = since start)" if s["first"] else ""), "", "P&L BY BOT"]
    for r in s["rows"]:
        out.append(f"- {r['label']}: today {_m(r['day_pl'])}, value ${r['value']:,.2f}, since start {_m(r['since_start'])}, trades today {r['trades']}")
    out += ["", "TRADES TODAY"]
    any_t = False
    for key, b in snap["bots"].items():
        for t in b["trades"]:
            any_t = True
            pl = "" if t.get("pnl") is None else f" P&L {_m(_num(t.get('pnl')))}"
            side = f" {t['side']}" if t.get("side") else ""
            qty = f" {t['qty']} @ {t['price']}" if t.get("qty") else ""
            why = f" - {t['why']}" if t.get("why") else ""
            out.append(f"- [{BOT_LABELS[key]}]{side} {t.get('symbol')}{qty}{pl}{why}")
    if not any_t:
        out.append("- No trades today.")
    out += ["", "HOLDING AT THE CLOSE"]
    b = snap["bots"]
    out.append(f"- Equity AI: {', '.join(b['equity']['holds']) or 'cash only'} (unrealized {_m(b['equity'].get('unrealized', 0))})")
    out.append(f"- Crypto leverage: {', '.join(b['leverage']['holds']) or 'no open positions'}")
    out.append(f"- Tactical: {', '.join(b['tactical']['holds']) or 'cash'}" + (" (rebalance pending)" if b["tactical"]["pending"] else ""))
    out.append(f"- Momentum: {b['momentum']['open']} open" + (f" (halted: {b['momentum']['halted']})" if b["momentum"]["halted"] else ""))
    sg = snap["signals"]
    out += ["", "SIGNALS TODAY",
            f"- Telegram stock tickers: {', '.join(sg['tickers']) or 'none'}",
            f"- Telegram crypto calls: {', '.join(sg['crypto']) or 'none'}",
            f"- Forex/gold (journal only): {', '.join(sg['fx']) or 'none'}",
            "", "WATCH NEXT SESSION (gappers with 4-5 of Ross Cameron's 5 pillars)"]
    for i in snap["ideas"]:
        out.append(f"- {i['ticker']} {i['score']}/5, +{i['chg']}% at ${i['price']}" + (f" - {i['news']}" if i.get("news") else ""))
    if not snap["ideas"]:
        out.append("- None met 4/5 today. Check the 7:00 ET pre-market scan.")
    out += ["", "Rules from your weekly sheet: A+ setups only, fixed risk, stop after 2 losses, no chasing.",
            "Open the Command Center: https://sarah.tail700e7e.ts.net/trading/"]
    if not snap["hub_ok"]:
        out.append("Note: the hub did not answer; equity and crypto values come from the saved files (no live prices).")
    return "\n".join(out)
