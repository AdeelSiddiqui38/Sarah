import unittest

import sarah_core as sc


class ProjectLinks(unittest.TestCase):
    def test_keeps_web_links(self):
        out = sc.clean_links([{"label": "Open Channel", "url": "https://www.youtube.com/channel/UC0Tq1paG_y63ilL0P4CjdOw"}])
        self.assertEqual(out[0]["label"], "Open Channel")

    def test_blank_label_uses_url(self):
        self.assertEqual(sc.clean_links([{"url": "https://example.com"}])[0]["label"], "https://example.com")

    def test_rejects_non_web_links(self):
        for bad in ("javascript:alert(1)", "file:///etc/passwd", 'https://x.com/"onload'):
            with self.assertRaises(ValueError):
                sc.clean_links([{"url": bad}])

    def test_caps_at_eight(self):
        self.assertEqual(len(sc.clean_links([{"url": f"https://e.com/{i}"} for i in range(12)])), 8)


if __name__ == "__main__":
    unittest.main()
