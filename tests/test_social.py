"""Offline tests for the Social media agent. Run: python3 -m unittest tests.test_social -v"""
import os, sys, tempfile, unittest
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import social_agent as s


class Social(unittest.TestCase):
    def test_every_pillar_every_month_builds_clean_posts(self):
        for month in range(1, 13):
            today = datetime(2026, month, 5)
            for pillar in s.CYCLE:
                for week in range(0, 12):
                    label, posts, flags = s.build_posts(pillar, today, s.pick_service(week))
                    self.assertEqual(set(posts), {"Facebook", "Instagram", "Nextdoor"})
                    self.assertEqual(flags, {}, (month, pillar, flags))
                    for ch, body in posts.items():
                        self.assertNotIn("{", body)
                        self.assertNotIn("Nolan Ridge", body)
                        self.assertIn("(403) 980-7003", body)
                    self.assertIn("#NolanHill", posts["Instagram"])
                    self.assertNotIn("#", posts["Facebook"])
                    self.assertNotIn("#", posts["Nextdoor"])

    def test_wording_guard_catches_bad_text(self):
        orig = s.SEASONAL[11]
        s.SEASONAL[11] = "We cure the flu, cheap meds, no prescription needed."
        try:
            _, _, flags = s.build_posts("seasonal", datetime(2026, 11, 2))
        finally:
            s.SEASONAL[11] = orig
        self.assertTrue(flags and all(any("cure" in x for x in v) for v in flags.values()))

    def test_rotation_and_offer_expiry(self):
        self.assertEqual([s.pick_pillar(w) for w in range(4)], s.CYCLE)
        self.assertTrue(s.offer_active(None)); self.assertTrue(s.offer_active("none"))
        self.assertFalse(s.offer_active("2020-01-01")); self.assertTrue(s.offer_active("2999-01-01"))

    def test_brief_text(self):
        label, posts, flags = s.build_posts("offer", datetime(2026, 11, 2))
        b = s.build_brief("offer", label, posts, flags, True, datetime(2026, 11, 2))
        for want in ("week of Nov 02, 2026", "Draft-only", "--- Facebook ---", "--- Nextdoor ---", "English flyer", "no Google version"):
            self.assertIn(want, b)
        self.assertIn("Review", s.build_brief("review_ask", *s.build_posts("review_ask", datetime(2026, 11, 2))[:1], *s.build_posts("review_ask", datetime(2026, 11, 2))[1:], False, datetime(2026, 11, 2)).replace("review", "Review"))

    def test_review_link_only_in_review_posts(self):
        _, p, _ = s.build_posts("review_ask", datetime(2026, 11, 2))
        self.assertIn("writereview", p["Facebook"])
        _, p, _ = s.build_posts("offer", datetime(2026, 11, 2))
        self.assertNotIn("writereview", p["Facebook"])


class CoreIntegration(unittest.TestCase):
    def test_run_social_one_draft(self):
        os.environ["SARAH_DATA_DIR"] = tempfile.mkdtemp()
        import importlib, sarah_core as c
        importlib.reload(c); c.init_db()
        p = c.find_project("Remedy Pills")
        r = c.run_social(p)
        self.assertTrue(r["draft"])
        d = c.q("SELECT * FROM drafts WHERE id=?", (r["draft"],), one=True)
        self.assertEqual((d["agent"], d["status"]), ("Social media", "pending"))
        self.assertIn("Draft-only", d["body"])
        self.assertIn("already waiting", c.run_social(p)["note"])
        self.assertTrue(c.q("SELECT 1 FROM audit WHERE action='social_drafts'", one=True))


if __name__ == "__main__":
    unittest.main()
