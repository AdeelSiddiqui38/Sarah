import unittest

import sarah_core as sc


class VaultScope(unittest.TestCase):
    def test_remedy_slot_keeps_original_names(self):
        self.assertEqual(sc.vault_key("gmail_app_password", 0), "gmail_app_password")

    def test_other_projects_get_their_own_key(self):
        self.assertEqual(sc.vault_key("gmail_app_password", 1), "p1:gmail_app_password")
        self.assertNotEqual(sc.vault_key("wp_user", 1), sc.vault_key("wp_user", 0))

    def test_ai_keys_are_shared(self):
        for n in ("openai_api_key", "anthropic_api_key"):
            self.assertEqual(sc.vault_key(n, 1), n)


if __name__ == "__main__":
    unittest.main()
