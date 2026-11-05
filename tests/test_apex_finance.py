import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import apex_finance as A

try:
    import openpyxl
except ImportError:  # the workbook fixture needs it; the container itself does not
    openpyxl = None

OPCO_SEP = """Transaction details
                                         Amounts debited                       Amounts credited
Date            Description                                                                   from your account ($)                    to your account ($)            Balance ($)
Aug 01          Opening balance                                                                                                                                          28,593.75
Sep 09          Transfer, TRANSFER FROM, 2817532 ALBERTA INC.                                                                                        10,000.00          38,593.75
Sep 09          Transfer, INVOICE 000030                                                                         21,000.00                                               17,593.75
Sep 29          Pre-Authorized Payment, DEFT SETTLEMENT FLE                                                      15,000.00                                              2,593.75
                0001
Sep 29          Closing totals                                                                                  36,000.00                            10,000.00
"""
OPCO_SEP = "For the period ending September 29, 2026\nBusiness Current Account\n# 3218 1961-455   28,593.75   36,000.00   10,000.00   2,593.75\n" + OPCO_SEP


def make_workbook(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ledger"
    ws.append(["LEDGER"])
    ws.append(["note"])
    ws.append(["Date", "Month", "Account", "Type", "Category", "Description", "In", "Out", "Shared", "Each", "Paid by", "Status", "Notes", "Cash"])
    for r in rows:
        ws.append([dt.datetime.fromisoformat(r[0]), None, r[1], r[2], r[3], r[4], r[5] or None, r[6] or None, "N", None, "", r[7], ""])
    wb.save(path)


@unittest.skipIf(openpyxl is None, "openpyxl not installed")
class ApexFinance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Finance" / "BMO Bank Doc" / "Bank Statement").mkdir(parents=True)
        (self.root / "Finance" / "BMO Bank Doc" / "Bank Statement" / "OpCo -Sep 2026.pdf").write_bytes(b"%PDF")
        self.data = self.root / "sd"
        patcher = mock.patch.object(A, "pdf_text", lambda p: OPCO_SEP)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def ledger(self, rows):
        make_workbook(self.root / "Finance" / A.WORKBOOK, rows)

    def test_statement_parse_directions_and_totals(self):
        s = A.parse_statement(self.root / "Finance" / "BMO Bank Doc" / "Bank Statement" / "OpCo -Sep 2026.pdf")
        self.assertEqual(s["account"], "OpCo")
        self.assertEqual([t["credit"] for t in s["txns"]], [True, False, False])
        self.assertEqual(s["txns"][2]["desc"], "Pre-Authorized Payment, DEFT SETTLEMENT FLE 0001")
        self.assertEqual(s["start"], "2026-08-01")

    def test_summary_cash_and_flags(self):
        self.ledger([("2026-09-09", "OpCo", "Capital-In", "Top-up", "wire", 10000, 0, "Received"),
                     ("2026-09-09", "OpCo", "Expense", "Construction", "INV-02", 0, 21000, "Paid"),
                     ("2026-10-16", "OpCo", "Expense", "Construction", "INV-04", 0, 31500, "Due")])
        s = A.summarize(str(self.root), str(self.data))
        self.assertEqual(s["kpi"]["cash_on_hand"], -11000.0)   # the Due invoice is not cash yet
        self.assertEqual(s["kpi"]["unpaid_invoices"], 31500.0)

    def test_rows_without_a_date_still_count(self):
        # the real workbook has rows with an amount but no date (e.g. a part payment); totals must include them
        make_workbook(self.root / "Finance" / A.WORKBOOK, [("2026-09-09", "OpCo", "Capital-In", "Top-up", "wire", 10000, 0, "Received")])
        wb = openpyxl.load_workbook(self.root / "Finance" / A.WORKBOOK)
        wb["Ledger"].append([None, None, "OpCo", "Expense", "Construction", "balance (no date)", None, 500, "N", None, "", "Paid", ""])
        wb.save(self.root / "Finance" / A.WORKBOOK)
        s = A.summarize(str(self.root), str(self.data))
        self.assertEqual(s["kpi"]["expenses"], 500.0)
        self.assertEqual(s["kpi"]["cash_on_hand"], 9500.0)
        self.assertTrue(any("without a date" in f["why"] for f in s["flags"]))

    def test_proposals_when_ledger_misses_a_period(self):
        self.ledger([("2026-09-09", "OpCo", "Capital-In", "Top-up", "wire", 10000, 0, "Received")])
        scan = A.scan_statements(str(self.root), str(self.data))
        self.assertEqual(len(scan["proposals"]), 2)          # invoice 21,000 and the 15,000 settlement
        self.assertTrue(all(p["account"] == "OpCo" for p in scan["proposals"]))
        self.assertEqual({p["out"] for p in scan["proposals"]}, {21000.0, 15000.0})

    def test_ledger_that_ties_proposes_nothing_even_if_lines_are_recorded_differently(self):
        # the ledger records the whole period as one netted row: same cash change as the statement, so no proposals
        self.ledger([("2026-09-29", "OpCo", "Expense", "Construction", "all payments netted", 0, 26000, "Paid")])
        scan = A.scan_statements(str(self.root), str(self.data))
        self.assertEqual(scan["proposals"], [])

    def test_approve_reject_and_dedupe(self):
        self.ledger([("2026-09-09", "OpCo", "Capital-In", "Top-up", "wire", 10000, 0, "Received")])
        scan = A.scan_statements(str(self.root), str(self.data))
        A.save_proposals(str(self.root), scan, str(self.data))
        ids = [p["id"] for p in scan["proposals"]]
        n = A.decide(str(self.root), ids[:1], True, str(self.data), {ids[0]: {"category": "Construction"}})
        self.assertEqual(n, 1)
        n = A.decide(str(self.root), ids[1:], False, str(self.data))
        self.assertEqual(n, 1)
        again = A.scan_statements(str(self.root), str(self.data))
        self.assertEqual(again["proposals"], [])            # approved and rejected rows do not come back
        s = A.summarize(str(self.root), str(self.data))
        self.assertEqual(s["added_by_sarah"], 1)

    def test_reminders_dedupe_keys_are_stable(self):
        self.ledger([("2026-09-09", "OpCo", "Capital-In", "Top-up", "wire", 10000, 0, "Received")])
        a = A.reminders(str(self.root), str(self.data), dt.date(2026, 11, 5))
        b = A.reminders(str(self.root), str(self.data), dt.date(2026, 11, 5))
        self.assertEqual([r["key"] for r in a], [r["key"] for r in b])

    def test_merge_script_writes_rows_and_marks_them(self):
        import merge_to_excel
        self.ledger([("2026-09-09", "OpCo", "Capital-In", "Top-up", "wire", 10000, 0, "Received")])
        scan = A.scan_statements(str(self.root), str(self.data))
        A.save_proposals(str(self.root), scan, str(self.data))
        A.decide(str(self.root), [scan["proposals"][0]["id"]], True, str(self.data))
        fin = self.root / "Finance"
        (fin / "Sarah Data").mkdir(exist_ok=True)
        for f in self.data.glob("*.json"):
            (fin / "Sarah Data" / f.name).write_text(f.read_text())
        self.assertEqual(merge_to_excel.merge(fin), 1)
        self.assertEqual(merge_to_excel.merge(fin), 0)       # second run adds nothing
        self.assertEqual(len(list((fin / "_backup").glob("*.xlsx"))), 1)
        rows = A.load_ledger(str(self.root))
        self.assertEqual(len(rows), 2)


class XlsxReader(unittest.TestCase):
    @unittest.skipIf(openpyxl is None, "openpyxl not installed")
    def test_reads_inline_and_formula_cells(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.xlsx"
            wb = openpyxl.Workbook()
            wb.active["A1"] = "hello"
            wb.active["B1"] = 12.5
            wb.active["C1"] = "=B1*2"
            wb.save(p)
            sh = A.read_xlsx(p)["Sheet"]
            self.assertEqual(sh[(1, "A")], "hello")
            self.assertEqual(sh[(1, "B")], 12.5)
            self.assertNotIn((1, "C"), sh)                  # formula without a stored value is skipped


if __name__ == "__main__":
    unittest.main()
