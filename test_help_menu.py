import unittest

from help_menu import build_help_menu_embeds


class HelpMenuTests(unittest.TestCase):
    def test_embed_fits_discord_limits(self) -> None:
        embeds = build_help_menu_embeds()

        self.assertGreater(len(embeds), 1)
        for embed in embeds:
            self.assertLessEqual(len(embed.fields), 25)
            self.assertLessEqual(len(embed), 6000)
            for field in embed.fields:
                self.assertLessEqual(len(field.name or ""), 256)
                self.assertLessEqual(len(field.value or ""), 1024)


if __name__ == "__main__":
    unittest.main()
