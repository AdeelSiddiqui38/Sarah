import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apex_finance as a


class T(unittest.TestCase):
    def test_add_payable_due_no_cash(self):
        with tempfile.TemporaryDirectory() as f, tempfile.TemporaryDirectory() as d:
            row = {"date": "2026-10-25", "desc": "Spartan Fitness SO 0046913", "category": "Gym Fit-Out", "amount": "8019.09", "account": "OpCo"}
            rid = a.add_payable(f, row, d)
            r = a.approved_rows(f, d)[0]
            self.assertEqual((r["status"], r["out"], r["category"], r["shared"]), ("Due", 8019.09, "Gym Fit-Out", "Y"))
            self.assertEqual(a.cash_effect(r), 0.0)
            with self.assertRaises(ValueError): a.add_payable(f, row, d)
            with self.assertRaises(ValueError): a.add_payable(f, dict(row, amount="0", desc="x2"), d)
            with self.assertRaises(ValueError): a.add_payable(f, dict(row, account="Trust", desc="x3"), d)

    def test_fronted_by_partner(self):
        with tempfile.TemporaryDirectory() as f, tempfile.TemporaryDirectory() as d:
            a.add_payable(f, {"date": "2026-10-29", "desc": "FASTSIGNS 674-10629", "category": "Signage", "amount": 4998, "fronted_by": "Huzefa"}, d)
            r = a.approved_rows(f, d)[0]
            self.assertEqual((r["account"], r["paid_by"], r["status"]), ("Personal-Huzefa", "Huzefa", "Paid"))
            self.assertEqual(a.cash_effect(r), 0.0)

if __name__ == "__main__": unittest.main()
