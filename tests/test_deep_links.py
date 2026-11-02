import unittest

from bot.services.deep_links import build_deep_link, generate_token, is_valid_token, validate_website_id


class DeepLinkTests(unittest.TestCase):
    def test_generated_tokens_are_valid_unique_and_non_sequential(self):
        tokens = {generate_token() for _ in range(100)}
        self.assertEqual(100, len(tokens))
        self.assertTrue(all(is_valid_token(token) for token in tokens))
        self.assertTrue(all(len(token) <= 64 for token in tokens))

    def test_link_contains_only_public_token(self):
        token = generate_token()
        link = build_deep_link("@HyperTeamITE_Bot", token)
        self.assertEqual(f"https://t.me/HyperTeamITE_Bot?start={token}", link)

    def test_invalid_token_and_website_id_are_rejected(self):
        self.assertFalse(is_valid_token("123"))
        with self.assertRaises(ValueError):
            validate_website_id("contains spaces")
