import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import supervisor as sv
import sarah_core as sc


class Rules(unittest.TestCase):
    def test_company_of(self):
        self.assertEqual(sv.company_of("APEX Physio and Wellness Clinic"), "APEX Physio")
        self.assertEqual(sv.company_of("Remedy Pills Pharmacy"), "Remedy Pills")
        self.assertIsNone(sv.company_of("Holiday plans"))

    def test_clean_draft_passes(self):
        r = sv.check_draft("APEX Physio", "Condo fee reminder", "Fee is $378.41 from the OpCo account on Dec 1. Call 825-509-7141.")
        self.assertTrue(r["ok"], r)

    def test_cross_company_is_held_both_ways(self):
        r = sv.check_draft("APEX Physio", "Invoice", "Please bill Remedy Pills for this.")
        self.assertEqual([i["code"] for i in r["issues"]], ["cross_company"])
        r = sv.check_draft("Remedy Pills", "Hello", "Reply from info@apex-physio.ca")
        self.assertFalse(r["ok"])

    def test_shared_building_words_do_not_trip(self):
        # Both clinics are at 246 Nolanridge Crescent NW in Nolan Hill
        self.assertTrue(sv.check_draft("Remedy Pills", "Flu shots", "Walk in at 246 Nolanridge Crescent NW, Nolan Hill.")["ok"])
        self.assertTrue(sv.check_draft("APEX Physio", "Open", "We are in Nolan Hill on Nolanridge Crescent.")["ok"])

    def test_secrets_are_held(self):
        for body in ("Password: hunter2", "SIN 123-456-789", "Account # 1234567", "Card 4111 1111 1111 1111"):
            r = sv.check_draft("APEX Physio", "T", body)
            self.assertIn("secret", [i["code"] for i in r["issues"]], body)
        self.assertTrue(sv.check_draft("APEX Physio", "T", "Phone 825-509-7141, invoice 674-10629, total $8,019.09")["ok"])

    def test_empty_and_unknown_company(self):
        self.assertFalse(sv.check_draft("APEX Physio", "", "x")["ok"])
        self.assertIn("no_company", [i["code"] for i in sv.check_draft(None, "a", "b")["issues"]])

    def test_dates_are_not_cards(self):
        for a in range(1, 13):
            for d in range(1, 29):
                txt = f"Statement period 2026-{a:02d}-{d:02d} 2026-10-31, invoice 674-10629"
                self.assertTrue(sv.check_draft("Remedy Pills", "Statement", txt)["ok"], txt)

    def test_needs_adeel_flag(self):
        self.assertTrue(sv.check_draft("APEX Physio", "Pay Spartan", "Pay the invoice")["needs_adeel"])
        self.assertFalse(sv.check_draft("APEX Physio", "Note", "Ledger looks fine")["needs_adeel"])

    def test_stale(self):
        rows = [{"id": 1, "created": "2026-11-01T10:00:00+00:00"}, {"id": 2, "created": "2026-11-08T10:00:00+00:00"}]
        self.assertEqual([d["id"] for d in sv.stale(rows, date(2026, 11, 9))], [1])


class Wiring(unittest.TestCase):
    """Supervisor inside Sarah Core, on a throwaway database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (sc.DATA_DIR, sc.DB_PATH)
        sc.DATA_DIR = Path(self.tmp.name)
        sc.DB_PATH = sc.DATA_DIR / "sarah.db"
        sc.init_db()
        sc.q("INSERT INTO projects (slot,name,relevance,folder,agents,created) VALUES (?,?,?,?,?,?)",
             (1, "APEX Physio", "Clinic", self.tmp.name, json.dumps({"Finance": 1}), sc.now()))
        self.apex = sc.find_project("APEX Physio")
        self.remedy = sc.find_project("Remedy Pills")

    def tearDown(self):
        sc.DATA_DIR, sc.DB_PATH = self.saved
        self.tmp.cleanup()

    def test_good_draft_pending_bad_draft_held_with_alert(self):
        ok = sc.make_draft(self.apex, "Finance", "Reminder", "Pay Spartan by Friday.", actor="sarah")
        bad = sc.make_draft(self.apex, "Finance", "Reminder", "Ask Remedy Pills to cover it.", actor="sarah")
        st = {d["id"]: d["status"] for d in sc.q("SELECT id, status FROM drafts")}
        self.assertEqual((st[ok], st[bad]), ("pending", "held"))
        alerts = sc.q("SELECT * FROM alerts")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["company"], "APEX Physio")
        self.assertEqual(sc.q("SELECT company FROM audit WHERE action='draft_created'")[0]["company"], "APEX Physio")
        view = {c["company"]: c for c in sc.supervisor_view()}
        self.assertEqual([h["id"] for h in view["APEX Physio"]["held"]], [bad])
        self.assertEqual(view["Remedy Pills"]["held"], [])

    def test_supervise_logs_work_and_alerts_on_error_once(self):
        sc.supervise("APEX Physio", "Finance", "noop", lambda: None)
        self.assertEqual(sc.q("SELECT count(*) AS n FROM tasks", one=True)["n"], 0)
        sc.supervise("APEX Physio", "Finance", "work", lambda: sc.audit("sarah", "x", {"project": "APEX Physio"}))
        self.assertEqual(sc.q("SELECT status FROM tasks", one=True)["status"], "done")

        def boom():
            raise RuntimeError("disk full")
        for _ in range(3):
            self.assertFalse(sc.supervise("Remedy Pills", "Invoices", "fetch", boom))
        self.assertEqual(sc.q("SELECT count(*) AS n FROM alerts WHERE kind='job_error'", one=True)["n"], 1)
        self.assertEqual(sc.q("SELECT count(*) AS n FROM tasks WHERE status='error'", one=True)["n"], 3)

    def test_ask_adeel_tool_and_stale(self):
        out = sc.run_tool("ask_adeel", {"project": "APEX Physio", "question": "Split FASTSIGNS 3 ways?"})
        self.assertTrue(out["ok"])
        self.assertEqual(sc.q("SELECT kind FROM alerts", one=True)["kind"], "question")
        st = sc.run_tool("project_status", {"project": "APEX Physio"})
        self.assertEqual(st["questions_to_adeel"][0]["status"], "open")
        did = sc.make_draft(self.remedy, "Finance", "Old", "Statement reminder", actor="sarah")
        sc.q("UPDATE drafts SET created='2026-01-01T00:00:00+00:00' WHERE id=?", (did,))
        sc.stale_check(); sc.stale_check()
        self.assertEqual(sc.q("SELECT count(*) AS n FROM alerts WHERE kind='stale'", one=True)["n"], 1)

    def test_remedy_reminders_skip_apex(self):
        sc.monthly_statements_task.__globals__["datetime"]  # module loaded
        import unittest.mock as um
        from datetime import datetime as real
        class FakeDT(real):
            @classmethod
            def now(cls, tz=None): return real(2026, 11, 20, 9, 0)
        with um.patch.object(sc, "datetime", FakeDT), um.patch.object(sc, "checklist", lambda p: {"items": [{"item": "Bank", "missing": ["Oct"]}, {"item": "Card", "missing": ["Oct"]}]}):
            sc.monthly_statements_task()
        made = sc.q("SELECT p.name AS project, d.status FROM drafts d JOIN projects p ON p.id=d.project_id")
        self.assertTrue(made)
        self.assertTrue(all("Remedy" in m["project"] for m in made), made)

    def test_held_draft_not_duplicated(self):
        sc.q("UPDATE projects SET agents=? WHERE id=?", (json.dumps({"Marketing": 1}), self.remedy["id"]))
        sc.make_draft(self.remedy, "Marketing", "Brief", "Mention apex-physio.ca", actor="sarah")
        self.assertTrue(sc.q("SELECT 1 FROM drafts WHERE project_id=? AND title=? AND status IN ('pending','held')", (self.remedy["id"], "Brief"), one=True))

    def test_email_agent_is_a_switch_and_shows_for_both_companies(self):
        self.assertIn("Email", sc.AGENTS)
        view = {c["company"]: c for c in sc.supervisor_view()}
        for co in ("APEX Physio", "Remedy Pills"):
            names = [a["name"] for a in view[co]["agents"]]
            self.assertEqual(names, sc.AGENTS)
            self.assertTrue(next(a for a in view[co]["agents"] if a["name"] == "Email")["role"])
        self.assertFalse(next(a for a in view["APEX Physio"]["agents"] if a["name"] == "Email")["on"])

    def test_old_database_gets_new_columns(self):
        sc.CON.close()
        con = sqlite3.connect(sc.DB_PATH)
        cols = {r[1] for r in con.execute("PRAGMA table_info(audit)")}
        con.close()
        self.assertIn("company", cols)
        sc.init_db()  # second run must not fail


if __name__ == "__main__":
    unittest.main()
