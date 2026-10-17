"""URL-credential scrubbing and the remote-URL restore warning (Q4)."""

from __future__ import annotations

import unittest

from services.git.scrub import scrub_url_credentials


class ScrubUrlCredentialsTests(unittest.TestCase):
    def test_masks_userinfo_in_free_text(self) -> None:
        text = "fatal: unable to access 'https://user:tok3n@git.example.com/r.git/': 403"
        scrubbed = scrub_url_credentials(text)
        self.assertNotIn("tok3n", scrubbed)
        self.assertIn("https://***@git.example.com/r.git/", scrubbed)

    def test_text_without_credentials_is_unchanged(self) -> None:
        self.assertEqual(scrub_url_credentials("plain https://git.example.com/r.git"),
                         "plain https://git.example.com/r.git")

