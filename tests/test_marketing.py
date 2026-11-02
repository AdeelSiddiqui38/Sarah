"""Offline tests for the Marketing agent. Run: python3 -m unittest tests.test_marketing -v"""
import os, sys, tempfile, unittest
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marketing_agent as m

GOOD = ('<html><head><title>Nolan Hill Pharmacy NW Calgary</title><meta name="description" content="Your Nolan Hill pharmacy: refills, '
        'transfers, delivery and a prescribing pharmacist at Remedy Pills."></head><body><div class="rp-offer-bar">x</div>'
        '<p>Call (403) 980-7003. 246 Nolanridge Crescent NW, Nolan Hill.</p><img src="a.jpg" alt="Store"></body></html>')


class Brief(unittest.TestCase):
    def test_good_page_passes(self):
        self.assertTrue(m.check_page("/", "Home", 200, GOOD)["ok"])

    def test_bad_wording_and_seo_flagged(self):
        html = "<html><head></head><body>Nolan Ridge pharmacy nationwide. We cure everything. <img src=a.jpg></body></html>"
        r = m.check_page("/", "Home", 200, html)
        txt = " | ".join(r["issues"]).lower()
        for want in ("nolan ridge", "nationwide", "cure", "missing page title", "meta description", "phone"):
            self.assertIn(want, txt)

    def test_no_false_positive_on_secure(self):
        html = GOOD.replace("Call", "Secure online refills, obscure procure. Call")
        self.assertTrue(m.check_page("/", "Home", 200, html)["ok"])

    def test_noindex_and_404(self):
        self.assertIn("noindex", " ".join(m.check_page("/x/", "X", 200, GOOD.replace("<head>", '<head><meta name="robots" content="noindex,follow">'))["issues"]))
        self.assertFalse(m.check_page("/x/", "X", 404, "")["ok"])
        self.assertIn("no answer", m.check_page("/x/", "X", 0, "")["issues"][0])

    def test_wording_flags_google(self):
        f = m.wording_flags("Save 15% every day, free delivery, price match guarantee", "google")
        for want in ("a percentage discount", "'free'", "'price match'", "'guarantee'"):
            self.assertIn(want, f)
        self.assertEqual(m.wording_flags("Walk-in flu shots, no appointment needed", "google"), [])

    def test_banner_expiry(self):
        self.assertIsNone(m.offer_banner_state("<p>none</p>", "2020-01-01"))
        self.assertIn("ended", m.offer_banner_state(GOOD, "2020-01-01"))
        self.assertIsNone(m.offer_banner_state(GOOD, "2999-01-01"))
        self.assertIn("YYYY", m.offer_banner_state(GOOD, "soon"))

    def test_metrics(self):
        rows = m.add_metrics([], {"clicks": "75", "impressions": 9030, "date": "2026-10-31"})
        rows = m.add_metrics(rows, {"clicks": 90, "date": "2026-11-30"})
        self.assertEqual(len(rows), 2)
        sec = "\n".join(m.metrics_section(rows, datetime(2026, 12, 1)))
        self.assertIn("clicks: 90 (+15 vs 2026-10-31)", sec)
        old = "\n".join(m.metrics_section(rows, datetime(2027, 2, 1)))
        self.assertIn("days old", old)
        with self.assertRaises(ValueError):
            m.add_metrics([], {"clicks": "lots"})
        with self.assertRaises(ValueError):
            m.add_metrics([], {})

    def test_brief_blocked_google_and_issues(self):
        res = [m.check_page("/", "Home", 200, GOOD), m.check_page("/a/", "A", 404, "")]
        b = m.build_brief(res, [], ["Item one"], True, "banner note", 3, datetime(2026, 11, 2))
        for want in ("week of Nov 02, 2026", "Draft-only", "A (/a/)", "banner note", "Routing ID DPNB", "November", "Item one", "3 draft(s)"):
            self.assertIn(want, b)
        ok = m.build_brief([m.check_page("/", "Home", 200, GOOD)], [], [], False, None, 0, datetime(2026, 11, 2))
        self.assertIn("All 1 pages passed", ok)
        self.assertIn("Posting allowed", ok)

    def test_check_site_uses_fetcher(self):
        calls = []
        def f(url):
            calls.append(url); return 200, GOOD
        res = m.check_site(f, "https://x.test", [("/", "Home"), ("/a/", "A")])
        self.assertEqual(calls, ["https://x.test/", "https://x.test/a/"])
        self.assertEqual(len(res), 2)


class CoreIntegration(unittest.TestCase):
    def test_run_marketing_creates_one_draft_per_week(self):
        tmp = tempfile.mkdtemp()
        os.environ["SARAH_DATA_DIR"] = tmp
        import importlib, sarah_core as c
        importlib.reload(c)
        c.init_db()
        p = c.find_project("Remedy Pills")
        self.assertIsNotNone(p)
        c.marketing_agent.fetch = lambda url, timeout=25: (200, GOOD)
        r1 = c.run_marketing(p)
        self.assertTrue(r1.get("draft"))
        d = c.q("SELECT * FROM drafts WHERE id=?", (r1["draft"],), one=True)
        self.assertEqual(d["agent"], "Marketing"); self.assertEqual(d["status"], "pending")
        self.assertIn("Draft-only", d["body"])
        self.assertIn("already waiting", c.run_marketing(p)["note"])
        self.assertTrue(c.q("SELECT 1 FROM audit WHERE action='marketing_brief'", one=True))


if __name__ == "__main__":
    unittest.main()
