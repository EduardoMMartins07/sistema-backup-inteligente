import unittest
from unittest.mock import patch

from api.database import _force_ipv4_url


class DatabaseUrlTests(unittest.TestCase):

    def test_neon_url_keeps_hostname_and_adds_endpoint_option(self):
        url = (
            "postgresql://user:pass@"
            "ep-wispy-moon-a1b2c3.sa-east-1.aws.neon.tech/db?sslmode=require"
        )

        translated = _force_ipv4_url(url)

        self.assertIn("ep-wispy-moon-a1b2c3.sa-east-1.aws.neon.tech", translated)
        self.assertIn("sslmode=require", translated)
        self.assertIn("options=endpoint%3Dep-wispy-moon-a1b2c3", translated)

    def test_neon_url_does_not_duplicate_existing_endpoint_option(self):
        url = (
            "postgresql://user:pass@"
            "ep-wispy-moon-a1b2c3.sa-east-1.aws.neon.tech/db"
            "?sslmode=require&options=endpoint%3Dep-wispy-moon-a1b2c3"
        )

        translated = _force_ipv4_url(url)

        self.assertEqual(url, translated)

    def test_non_neon_url_can_still_be_forced_to_ipv4(self):
        with patch("api.database.socket.getaddrinfo") as getaddrinfo:
            getaddrinfo.return_value = [(None, None, None, None, ("203.0.113.10", 5432))]

            translated = _force_ipv4_url(
                "postgresql://user:pass@db.example.com:5432/app"
            )

        self.assertEqual("postgresql://user:pass@203.0.113.10:5432/app", translated)


if __name__ == "__main__":
    unittest.main()
