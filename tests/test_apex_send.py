import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apex_mail as m
from test_apex_mail import mk, FakeIMAP


class FakeSMTP:
    sent = []
    def send_message(self, msg, from_addr=None, to_addrs=None):
        FakeSMTP.sent.append((msg, from_addr, to_addrs))
    def quit(self): pass


class T(unittest.TestCase):
    def setUp(self): FakeSMTP.sent = []

    def test_draft_does_not_send_and_validates(self):
        with tempfile.TemporaryDirectory() as d:
            rid = m.create_outbox(d, "a@b.com, c@d.org", "", "Hi", "Body")
            self.assertEqual(FakeSMTP.sent, [])
            self.assertEqual(m.outbox_view(d)[0]["status"], "draft")
            for bad in (("nope", "", "s", "b"), ("a@b.com", "", "", "b"), ("a@b.com", "x@", "s", "b"), ("a@b.com", "", "s", " ")):
                with self.assertRaises(ValueError): m.create_outbox(d, *bad)

    def test_send_with_attachment_once_only(self):
        with tempfile.TemporaryDirectory() as d:
            rid = m.create_outbox(d, "ally@x.ca", "cc@x.ca", "Void cheque", "Please update.", [{"uid": "1", "name": "inv 123.pdf"}])
            it = m.send_outbox(d, rid, imap_factory=lambda: FakeIMAP([mk("a")]), smtp_factory=FakeSMTP)
            self.assertEqual(it["status"], "sent")
            msg, frm, to = FakeSMTP.sent[0]
            self.assertEqual(frm, "info@apex-physio.ca"); self.assertEqual(to, ["ally@x.ca", "cc@x.ca"])
            self.assertEqual([p.get_filename() for p in msg.iter_attachments()], ["inv 123.pdf"])
            with self.assertRaises(ValueError): m.send_outbox(d, rid, imap_factory=lambda: FakeIMAP([mk("a")]), smtp_factory=FakeSMTP)
            self.assertEqual(len(FakeSMTP.sent), 1)

    def test_missing_attachment_fails_without_sending_and_can_retry_or_discard(self):
        with tempfile.TemporaryDirectory() as d:
            rid = m.create_outbox(d, "ally@x.ca", "", "S", "B", [{"uid": "1", "name": "nope.pdf"}])
            with self.assertRaises(ValueError): m.send_outbox(d, rid, imap_factory=lambda: FakeIMAP([mk("a")]), smtp_factory=FakeSMTP)
            self.assertEqual(FakeSMTP.sent, []); self.assertEqual(m.outbox_view(d)[0]["status"], "failed")
            m.discard_outbox(d, rid); self.assertEqual(m.outbox_view(d), [])

if __name__ == "__main__": unittest.main()
