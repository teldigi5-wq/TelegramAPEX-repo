import unittest

from desktop_media_policy import parse_media_page


class MediaPageSafetyTests(unittest.TestCase):
    def test_default_and_existing_app_pagination(self):
        self.assertEqual(parse_media_page(), (50, 0))
        self.assertEqual(parse_media_page("50", "1250234567"), (50, 1250234567))
        self.assertEqual(parse_media_page("100", "9223372036854775807"), (100, 9223372036854775807))

    def test_rejects_unbounded_and_invalid_page_sizes(self):
        for raw in ["0", "101", "10000", "-10", "1.0", "", "nan", "999999999999"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_media_page(raw, "0")

    def test_rejects_malformed_or_overflowing_cursors(self):
        for raw in ["-1", "1.5", "nan", "9223372036854775808", "999999999999999999999", "", "1 OR 1=1"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_media_page("50", raw)

    def test_rejects_url_encoded_and_unicode_digits(self):
        for raw in ["%35%30", "５０", "²", "+1", " 50"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_media_page(raw, "0")


if __name__ == "__main__":
    unittest.main()
