import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import trading_bots as tb


def write(d, name, obj):
    (d / name).write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")


class Bots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.d = self.folder / "trading-paperbot"
        self.d.mkdir()
        write(self.d, "momentum_portfolio.json", {"cash": 9990.5, "starting_cash": 10000.0, "open_positions": [],
              "closed_trades": [{"symbol": "XLAB", "qty": 10, "pnl": -4.5, "r_multiple": -0.9, "close_reason": "stop"},
                                {"symbol": "TCRT", "qty": 5, "pnl": 6.0, "r_multiple": 1.2}],
              "day": {"date": "2026-11-13", "realized": 1.5, "halted": "", "traded": ["XLAB", "TCRT"]}})
        write(self.d, "momentum_bot.log", "[x] start\n[y] outside trading window - idle\n")
        write(self.d, "tactical_bot.log", "[x] EQUITY\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_reads_both_accounts(self):
        write(self.d, "tactical_portfolio.json", {"cash": 0, "starting_cash": 10000.0, "positions": {"SPY": 20.1},
              "pending": None, "last_processed": "2026-11-13", "equity_curve": [{"date": "2026-11-13", "equity": 10150.0}], "rebalances": [1]})
        st = tb.status(str(self.folder))
        m = st["bots"]["momentum"]["account"]
        self.assertEqual((m["closed_trades"], m["realized"], m["wins"]), (2, 1.5, 1))
        self.assertEqual(st["bots"]["momentum"]["recent_log"][-1], "[y] outside trading window - idle")
        t = st["bots"]["tactical"]["account"]
        self.assertEqual((t["equity"], t["return_pct"], t["data_problem"]), (10150.0, 1.5, False))

    def test_nan_account_is_flagged(self):
        write(self.d, "tactical_portfolio.json", '{"cash": 0.0, "starting_cash": 10000.0, "positions": {"SPY": NaN}, '
              '"pending": null, "last_processed": "2026-10-21", "equity_curve": [{"date": "2026-10-21", "equity": NaN}], "rebalances": []}')
        st = tb.status(str(self.folder))
        self.assertTrue(st["bots"]["tactical"]["account"]["data_problem"])
        refs = [r for r, _ in tb.problems(st, datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc))]
        self.assertEqual(refs, ["bots:tactical-data"])

    def test_silent_momentum_only_alerts_inside_window(self):
        old = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc).timestamp()  # 08:00 ET Monday
        os.utime(self.d / "momentum_bot.log", (old, old))
        write(self.d, "tactical_portfolio.json", {"starting_cash": 10000.0, "positions": {}, "equity_curve": [], "last_processed": "2026-11-13"})
        inside = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)   # 10:00 ET, log 2 h old
        outside = datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)  # 15:00 ET
        self.assertTrue(any(r.startswith("bots:momentum-silent") for r, _ in tb.problems(tb.status(str(self.folder), inside), inside)))
        self.assertEqual(tb.problems(tb.status(str(self.folder), outside), outside), [])

    def test_missing_folder(self):
        st = tb.status("/nope")
        self.assertFalse(st["found"])
        self.assertEqual(tb.problems(st)[0][0], "bots:folder")


if __name__ == "__main__":
    unittest.main()
