import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import trading_report as tr
import sarah_core as sc


def w(d, name, obj):
    (d / name).write_text(json.dumps(obj), encoding="utf-8")


HUB = {
    "equity": {"cash": 8609.38, "starting_cash": 10000.0, "total_value": 9586.48, "unrealized": -413.52,
               "positions": [{"ticker": "NVDA", "qty": 6, "upnl": -413.52}],
               "trades": [{"ts": "2026-11-16T10:05:00", "ticker": "AAPL", "action": "buy", "qty": 2, "price": 230.0, "reasoning": "momentum"}]},
    "leverage": {"equity": 10010.0, "starting_cash": 10000.0, "open": [],
                 "closed": [{"symbol": "SOL/USDT", "side": "short", "pnl": 10.0, "close_reason": "take_profit", "closed_at": "2026-11-16T15:00:00+00:00"}]},
    "gappers": {"rows": [{"ticker": "SBC", "score": 5, "chg": 45.2, "price": 6.1, "news": {"title": "SBC soars"}},
                         {"ticker": "LOW", "score": 2, "chg": 12.0, "price": 3.0, "news": None}]},
    "signals": {"tickers": [{"ticker": "TSLA", "received_at": "2026-11-16T14:00:00+00:00"}],
                "leverage": [{"symbol": "BTCUSDT", "side": "long", "received_at": "2026-11-16T14:05:00+00:00"}]},
}


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name)
        self.b = self.f / "trading-paperbot"
        self.b.mkdir()
        w(self.b, "momentum_portfolio.json", {"cash": 9990.0, "starting_cash": 10000.0, "open_positions": [],
          "closed_trades": [{"symbol": "XLAB", "pnl": -5.0, "r_multiple": -1.0, "close_reason": "stop", "closed_at": "2026-11-16T15:10:00+00:00"},
                            {"symbol": "QQQX", "pnl": 3.0, "closed_at": "2026-11-13T15:10:00+00:00"}],
          "day": {"date": "2026-11-16", "realized": -5.0, "halted": ""}})
        w(self.b, "tactical_portfolio.json", {"starting_cash": 10000.0, "positions": {"SPY": 4.0, "SHY": 70.0}, "pending": None,
          "equity_curve": [{"date": "2026-11-16", "equity": 10020.0}], "rebalances": []})
        w(self.b, "fx_signals.json", [{"ts": "2026-11-16T13:00:00+00:00", "side": "long", "symbol": "XAUUSD", "channel": "FX Culture"}])

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_report_is_since_start(self):
        snap = tr.snapshot(str(self.f), HUB, date(2026, 11, 16))
        s, body = tr.build(snap, None)
        by = {r["bot"]: r for r in s["rows"]}
        self.assertEqual(by["momentum"]["day_pl"], -10.0)
        self.assertEqual(by["tactical"]["day_pl"], 20.0)
        self.assertEqual(by["equity"]["day_pl"], -413.52)
        self.assertEqual(by["leverage"]["trades"], 1)
        self.assertEqual(by["momentum"]["trades"], 1)          # only today's closed trade
        self.assertTrue(s["first"])
        self.assertIn("XLAB", body); self.assertNotIn("QQQX", body)
        self.assertIn("SBC 5/5", body); self.assertNotIn("LOW 2/5", body)
        self.assertIn("XAUUSD", body); self.assertIn("TSLA", body); self.assertIn("LONG BTCUSDT", body)

    def test_second_day_uses_previous_values(self):
        d1 = tr.snapshot(str(self.f), HUB, date(2026, 11, 16))
        hub2 = json.loads(json.dumps(HUB)); hub2["equity"]["total_value"] = 9686.48
        w(self.b, "tactical_portfolio.json", {"starting_cash": 10000.0, "positions": {}, "equity_curve": [{"date": "2026-11-17", "equity": 10000.0}]})
        s, _ = tr.build(tr.snapshot(str(self.f), hub2, date(2026, 11, 17)), d1)
        by = {r["bot"]: r for r in s["rows"]}
        self.assertEqual((by["equity"]["day_pl"], by["tactical"]["day_pl"], by["momentum"]["day_pl"]), (100.0, -20.0, 0.0))
        self.assertFalse(s["first"])

    def test_hub_down_uses_files(self):
        w(self.b, "portfolio.json", {"cash": 9000.0, "starting_cash": 10000.0, "positions": {"NVDA": {"qty": 5, "avg_price": 200.0}}, "trades": []})
        snap = tr.snapshot(str(self.f), {}, date(2026, 11, 16))
        self.assertEqual(snap["bots"]["equity"]["value"], 10000.0)
        self.assertIn("did not answer", tr.build(snap)[1])


class Job(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sc.DATA_DIR = Path(self.tmp.name)
        sc.DB_PATH = sc.DATA_DIR / "sarah.db"
        sc.init_db()
        (Path(self.tmp.name) / "tcc" / "trading-paperbot").mkdir(parents=True)
        sc.q("INSERT INTO projects (slot,name,relevance,folder,agents,created) VALUES (?,?,?,?,?,?)",
             (3, "Trading Command Center", "x", str(Path(self.tmp.name) / "tcc"), json.dumps({"Journal & Risk": 1}), sc.now()))

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs_once_after_230_on_weekdays_and_emails_only_adeel(self):
        sent = []
        with mock.patch.object(sc, "_hub_state", lambda: HUB), \
             mock.patch.object(sc, "send_trading_report", lambda p, subj, body: sent.append(subj) or True):
            self.assertIsNone(sc.trading_report_job(when=datetime(2026, 11, 16, 14, 0)))   # before 2:30
            self.assertIsNone(sc.trading_report_job(when=datetime(2026, 11, 15, 15, 0)))   # Sunday
            rid = sc.trading_report_job(when=datetime(2026, 11, 16, 14, 35))
            self.assertEqual(sc.trading_report_job(when=datetime(2026, 11, 16, 15, 35)), rid)  # once a day
        self.assertEqual(len(sent), 1)
        self.assertEqual(sc.q("SELECT count(*) AS n FROM alerts WHERE kind='report'", one=True)["n"], 1)
        self.assertTrue(sc.q("SELECT emailed FROM reports", one=True)["emailed"])

    def test_email_goes_to_the_saved_address_only(self):
        sc.setting("trading_report_email", "me@gmail.com")
        p = sc.trading_project()
        sc.vault_set("gmail_app_password", "abcdabcdabcdabcd", p["slot"])
        calls = {}

        class FakeSMTP:
            def __init__(self, *a, **k): calls["host"] = a[0]
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def login(self, u, pw): calls["login"] = u
            def send_message(self, msg, to_addrs=None): calls["to"] = to_addrs; calls["hdr"] = msg["To"]
        with mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            self.assertTrue(sc.send_trading_report(p, "s", "b"))
        self.assertEqual((calls["host"], calls["login"], calls["to"], calls["hdr"]), ("smtp.gmail.com", "me@gmail.com", ["me@gmail.com"], "me@gmail.com"))


if __name__ == "__main__":
    unittest.main()
