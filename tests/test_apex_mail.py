import os, sys, tempfile, unittest
from email.message import EmailMessage
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apex_mail, apex_vendors


def mk(uid_subject, with_pdf=True):
    m = EmailMessage()
    m["From"] = "Billing Co <bill@vendor.com>"; m["To"] = "info@apex-physio.ca"
    m["Subject"] = uid_subject; m["Message-ID"] = f"<{uid_subject}@x>"
    m["Date"] = "Wed, 04 Nov 2026 10:00:00 +0000"
    m.set_content("Please find invoice attached.")
    if with_pdf:
        m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="inv 123.pdf")
        m.add_attachment(b"x", maintype="application", subtype="zip", filename="skip.zip")
    return m.as_bytes()


class FakeIMAP:
    def __init__(self, msgs): self.msgs = msgs; self.calls = []
    def select(self, box, readonly=False): self.calls.append(("select", readonly)); return "OK", [b"1"]
    def uid(self, cmd, *a):
        self.calls.append((cmd, a))
        if cmd == "SEARCH": return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.msgs)))]
        return "OK", [(b"1 (BODY[] {n})", self.msgs[int(a[0]) - 1]), b")"]
    def logout(self): pass


class T(unittest.TestCase):
    def test_check_files_attachments_once_and_is_readonly(self):
        with tempfile.TemporaryDirectory() as f, tempfile.TemporaryDirectory() as d:
            fake = FakeIMAP([mk("a"), mk("b", False)])
            st = apex_mail.check(f, d, lambda: fake)
            self.assertIsNone(st["error"]); self.assertEqual(st["new_files"], 1)
            self.assertTrue(all(c[1] is True for c in fake.calls if c[0] == "select"))
            self.assertTrue(all("PEEK" in c[1][1] for c in fake.calls if c[0] == "FETCH"))
            files = list(apex_vendors.inbox(f).iterdir()); self.assertEqual(len(files), 1)
            self.assertTrue(files[0].suffix == ".pdf")
            st2 = apex_mail.check(f, d, lambda: FakeIMAP([mk("a"), mk("b", False)]))
            self.assertEqual(st2["new_files"], 0); self.assertEqual(len(list(apex_vendors.inbox(f).iterdir())), 1)
            self.assertEqual(len(st2["messages"]), 2)

    def test_unconfigured_and_error_hide_password(self):
        os.environ.pop("SARAH_APEX_MAIL_PASS", None)
        with tempfile.TemporaryDirectory() as f, tempfile.TemporaryDirectory() as d:
            self.assertIn("password", apex_mail.check(f, d)["error"])
            def boom(): raise OSError("connection refused")
            self.assertIn("failed", apex_mail.check(f, d, boom)["error"])
            self.assertFalse(apex_mail.summary(d)["configured"])

if __name__ == "__main__": unittest.main()
