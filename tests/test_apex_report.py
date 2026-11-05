import sys, tempfile, unittest, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apex_finance as a, apex_report as r


class T(unittest.TestCase):
    def test_month_and_notes_and_text(self):
        self.assertEqual(r.previous_month(dt.date(2026, 1, 3)), "2025-12")
        with tempfile.TemporaryDirectory() as f, tempfile.TemporaryDirectory() as d:
            a.add_payable(f, {"date": "2026-10-25", "desc": "Spartan SO 1", "category": "Gym Fit-Out", "amount": 300}, d)
            a.add_payable(f, {"date": "2026-10-29", "desc": "Sign", "category": "Signage", "amount": 4998, "fronted_by": "Huzefa"}, d)
            r.save_notes(f, "2026-10", ["Sign installed", " "], ["Approve gym order"], d)
            rep = r.build(f, d, "2026-10", dt.date(2026, 11, 1))
            self.assertEqual(rep["owe"]["unpaid_total"], 300.0)
            self.assertEqual(rep["owe"]["owed_to_partners"]["Huzefa"], 4998.0)
            self.assertEqual(rep["progress"], ["Sign installed"])
            t = r.text(rep)
            self.assertIn("Owed back to Huzefa: $4,998.00", t); self.assertIn("100.00 each", t)
            self.assertIn("Approve gym order", t)
            with self.assertRaises(ValueError): r.build(f, d, "bad")

if __name__ == "__main__": unittest.main()
