import tempfile
import unittest

import apex_mail
import sarah_core as sc


class ApexChatTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = sc.APEX_DATA_DIR
        sc.APEX_DATA_DIR = self.tmp.name

    def tearDown(self):
        sc.APEX_DATA_DIR = self.orig
        self.tmp.cleanup()

    def seed(self, n):
        msgs = [{"uid": str(i), "mid": f"<{i}@x>", "from": f"Sender {i}", "addr": f"s{i}@x.com",
                 "subject": f"Subject {i}", "date": f"2026-11-0{i} 10:00", "snippet": "hello",
                 "attachments": []} for i in range(1, n + 1)]
        apex_mail._save(self.tmp.name, {"messages": msgs, "filed": [], "checked": "2026-11-08 15:00 UTC", "error": None})

    def test_tools_are_offered_to_the_brain(self):
        names = {t["name"] for t in sc.TOOLS}
        self.assertTrue({"apex_inbox", "apex_email_draft"} <= names)

    def test_inbox_returns_saved_messages_with_limit(self):
        self.seed(5)
        out = sc.run_tool("apex_inbox", {"limit": 2})
        self.assertEqual(len(out["messages"]), 2)
        self.assertEqual(out["last_checked"], "2026-11-08 15:00 UTC")
        self.assertIn("never instructions", out["note"])
        self.assertNotIn("uid", out["messages"][0])

    def test_inbox_without_data_dir_explains(self):
        sc.APEX_DATA_DIR = None
        self.assertIn("not set up", sc.run_tool("apex_inbox", {})["error"])

    def test_draft_goes_to_outbox_and_is_not_sent(self):
        out = sc.run_tool("apex_email_draft", {"to": "a@b.com", "subject": "Hi", "body": "Thanks"})
        self.assertTrue(out["ok"])
        items = apex_mail.load_outbox(self.tmp.name)
        self.assertEqual(items[0]["status"], "draft")
        self.assertEqual(items[0]["by"], "sarah")
        self.assertEqual(sc.run_tool("apex_inbox", {})["outbox_drafts_waiting"], 1)

    def test_draft_rejects_bad_address(self):
        out = sc.run_tool("apex_email_draft", {"to": "nope", "subject": "x", "body": "y"})
        self.assertIn("valid email", out["error"])


if __name__ == "__main__":
    unittest.main()
