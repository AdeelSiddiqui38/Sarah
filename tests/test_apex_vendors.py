import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import apex_vendors as V
import apex_finance as A

INV_TEXT = "ACME Physio Supplies Ltd\nInvoice date: 2026-10-14\nSubtotal 100.00\nTotal $105.00\n"


class Vendors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "sd"
        (self.root / "Vendor Invoices" / "Acme Physio Supplies").mkdir(parents=True)
        p = mock.patch.object(V, "pdf_text", lambda path: INV_TEXT if str(path).endswith(".pdf") else "")
        p.start()
        self.addCleanup(p.stop)

    def test_upload_lands_in_inbox_and_rejects_bad_files(self):
        n = V.save_upload(self.root, "../evil/inv 1.pdf", base64.b64encode(b"%PDF-1.4 x").decode())
        self.assertEqual(n, "inv 1.pdf")
        self.assertTrue((self.root / "Vendor Invoices" / "Inbox" / n).exists())
        with self.assertRaises(ValueError):
            V.save_upload(self.root, "run.exe", base64.b64encode(b"x").decode())
        self.assertEqual(V.save_upload(self.root, "inv 1.pdf", base64.b64encode(b"%PDF y").decode()), "inv 1-2.pdf")

    def test_scan_guesses_vendor_date_total_and_photos_wait(self):
        V.save_upload(self.root, "scan001.pdf", base64.b64encode(b"%PDF").decode())
        V.save_upload(self.root, "IMG_1.jpg", base64.b64encode(b"\xff\xd8x").decode())
        got = {x["file"]: x for x in V.scan_inbox(self.root, self.data)}
        self.assertEqual(got["scan001.pdf"]["vendor"], "Acme Physio Supplies")
        self.assertEqual(got["scan001.pdf"]["date"], "2026-10-14")
        self.assertEqual(got["scan001.pdf"]["total"], 105.0)
        self.assertEqual(got["IMG_1.jpg"]["vendor"], "")
        self.assertEqual(got["IMG_1.jpg"]["kind"], "photo")

    def test_filing_moves_without_overwriting_and_remembers_vendor(self):
        V.save_upload(self.root, "a.pdf", base64.b64encode(b"%PDF").decode())
        V.save_upload(self.root, "b.pdf", base64.b64encode(b"%PDF2").decode())
        items = [{"id": x["id"], "vendor": "Acme Physio Supplies"} for x in V.scan_inbox(self.root, self.data)]
        self.assertEqual(V.file_invoices(self.root, items, self.data), 2)
        d = self.root / "Vendor Invoices" / "Acme Physio Supplies" / "2026-10"
        names = sorted(p.name for p in d.iterdir())
        self.assertEqual(names, ["2026-10-14_Acme-Physio-Supplies_105.00-2.pdf", "2026-10-14_Acme-Physio-Supplies_105.00.pdf"])
        self.assertEqual(V.scan_inbox(self.root, self.data), [])
        self.assertIn("Acme Physio Supplies", (self.data / "apex-vendors.json").read_text())

    def test_filing_needs_a_vendor_and_a_real_inbox_id(self):
        V.save_upload(self.root, "a.pdf", base64.b64encode(b"%PDF").decode())
        i = V.scan_inbox(self.root, self.data)[0]["id"]
        self.assertEqual(V.file_invoices(self.root, [{"id": i, "vendor": "  "}, {"id": "nope", "vendor": "X"}, {"id": i, "vendor": "../../x"}], self.data), 1)
        self.assertTrue((self.root / "Vendor Invoices" / "x").is_dir())     # path characters are stripped, never escapes
        self.assertFalse((self.root.parent / "x").exists())

    def test_holdco_is_dormant_by_default_and_can_be_switched_back(self):
        self.assertEqual(A.settings(self.root, self.data)["dormant"], ["HoldCo"])
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "apex-settings.json").write_text('{"dormant": []}')
        self.assertEqual(A.settings(self.root, self.data)["dormant"], [])

    def test_missing_statements_and_reconcile_skip_dormant(self):
        scan = {"coverage": {"HoldCo": [{"start": "2026-05-01", "period_end": "2026-05-29"}], "OpCo": [{"start": "2026-07-01", "period_end": "2026-07-31"}]},
                "balances": {"HoldCo": {"date": "2026-05-29", "balance": 5.0}, "OpCo": {"date": "2026-07-31", "balance": 9.0}},
                "dormant": ["HoldCo"], "dormant_new": 0, "proposals": []}
        import datetime as dt
        miss = A.missing_statements(scan, dt.date(2026, 11, 5))
        self.assertNotIn("HoldCo", miss)
        self.assertIn("OpCo", miss)
        arch = A.archive(scan, [])
        self.assertEqual(arch[0]["account"], "HoldCo")
        self.assertEqual(arch[0]["final_balance"], 5.0)


if __name__ == "__main__":
    unittest.main()
