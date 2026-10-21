import unittest
from desktop_origin_policy import permitted_desktop_request as allowed

class LoopbackOriginTests(unittest.TestCase):
    def test_own_browser_origin(self):
        self.assertTrue(allowed("127.0.0.1:8734", "http://127.0.0.1:8734", "same-origin"))
        self.assertTrue(allowed("localhost:8734", "http://localhost:8734", "same-origin"))

    def test_cli_diagnostics_without_browser_metadata(self):
        self.assertTrue(allowed("127.0.0.1:8734", None, None))

    def test_untrusted_remote_site(self):
        for host, origin, site in [
            ("evil.example:8734", "http://evil.example:8734", "same-origin"),
            ("127.0.0.1.example.net:8734", None, None),
            ("127.0.0.1:8734", "https://evil.example", "cross-site"),
            ("127.0.0.1:8734", "http://localhost:8734", "same-site"),
            ("127.0.0.1:8734", "null", "cross-site"),
            ("127.0.0.1:8734", "http://127.0.0.1:8734", "cross-site"),
            ("127.0.0.1:8734", "http://127.0.0.1:8735", "same-origin"),
            ("localhost:8734@evil.example", None, None),
            ("localhost:99999", None, None)
        ]:
            with self.subTest(host=host, origin=origin, site=site):
                self.assertFalse(allowed(host, origin, site))

if __name__ == "__main__":
    unittest.main()
