import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot import PROFILE_DEFAULTS, PROFILE_STAT_DEFAULTS, render_profile_image, save_profile_inventory
from pokeball_drops import DyeInventoryView, PokeballDrops, PokeballView, level_for_xp, load_dyes
from PIL import Image, ImageChops


class PokeballTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.bot = Mock()
        self.bot.profile_inventory = {}
        self.bot.profile_inventory_path = self.root / "inventory.json"
        self.bot.active_incenses = {}
        self.bot.muted_poketwo_channels = set()
        self.drops = PokeballDrops(self.bot, self.root / "drops.json", self.root / "dyes.json", save_profile_inventory)

    async def asyncTearDown(self) -> None:
        self.drops.close()
        await asyncio.sleep(0)
        self.directory.cleanup()

    def catalog(self) -> None:
        (self.root / "dyes.json").write_text(json.dumps({"dyes": [
            {"name": "Pink", "type": "background", "rarity": "normal", "color": "#FF88CC"},
            {"name": "Radiant", "type": "frame", "rarity": "radiant", "color": "#FFD700"},
        ]}), encoding="utf-8")

    async def test_level_boundaries_and_xp_persistence(self) -> None:
        self.assertEqual([level_for_xp(x) for x in (0, 499, 500, 1099, 1100)], [0, 0, 1, 1, 2])
        with patch("pokeball_drops.random.randrange", side_effect=[100, 0]), patch("pokeball_drops.random.randint", return_value=500):
            self.assertIn("level 1", self.drops.award(1))
        loaded = PokeballDrops(self.bot, self.drops.path, self.drops.catalog_path, save_profile_inventory)
        self.assertEqual(loaded.level(1), 1)

    async def test_coins_and_unlucky_zero(self) -> None:
        with patch("pokeball_drops.random.randrange", side_effect=[100, 1]), patch("pokeball_drops.random.randint", return_value=1000):
            self.assertIn("1,000", self.drops.award(1))
        self.assertEqual(self.bot.profile_inventory["1"]["balances"]["Pokédollar"], 1000)
        self.assertTrue(self.bot.profile_inventory_path.is_file())
        with patch("pokeball_drops.random.randrange", side_effect=[100, 0]), patch("pokeball_drops.random.randint", return_value=0):
            self.assertIn("unlucky", self.drops.award(1))

    async def test_rare_roll_boundaries_and_missing_catalog(self) -> None:
        self.catalog()
        for roll, rarity in [(0, "radiant"), (1, "radiant"), (2, "normal"), (16, "normal")]:
            with patch("pokeball_drops.random.randrange", side_effect=[roll, roll]), patch("pokeball_drops.random.choice", side_effect=lambda values: values[0]):
                self.assertIn(rarity, self.drops.award(1))
        self.assertEqual(len(self.drops.data["users"]["1"]["dyes"]), 4)
        (self.root / "dyes.json").unlink()
        with patch("pokeball_drops.random.randrange", side_effect=[0, 0]), patch("pokeball_drops.random.randint", return_value=1):
            self.assertIn("1 XP", self.drops.award(2))

    async def test_dye_and_select_individual_owned_copies(self) -> None:
        self.catalog()
        self.bot.profile_inventory = {"1": {"balances": {}, "assets": [
            {"code": "AAAAAAA", "type": "background", "key": "cosmog"},
            {"code": "BBBBBBB", "type": "background", "key": "cosmog"},
            {"code": "CCCCCCC", "type": "frame", "key": "mystic"},
        ]}}
        with patch("pokeball_drops.random.randrange", side_effect=[2, 1]), patch("pokeball_drops.random.choice", side_effect=lambda values: values[0]):
            self.drops.award(1)
        code = self.drops.data["users"]["1"]["dyes"][0]["code"]
        message = Mock()
        message.author.id = 1
        message.reply = AsyncMock()
        message.content = f"v!dye {code} CCCCCCC"
        await self.drops.dye(message)
        self.assertEqual(len(self.drops.data["users"]["1"]["dyes"]), 1)
        message.content = f"v!dye {code} AAAAAAA"
        await self.drops.dye(message)
        self.assertEqual(self.drops.data["users"]["1"]["dyes"], [])
        self.assertEqual(self.drops.appearance(1, {"background": "cosmog"})["background"]["color"], "#FF88CC")
        message.content = "v!equip BBBBBBB"
        await self.drops.equip(message)
        self.assertNotIn("background", self.drops.appearance(1, {"background": "cosmog"}))
        self.assertEqual(self.bot.set_profile_setting.call_args.args, (1, "background", "cosmog"))

    async def test_single_claim_and_failed_save_can_be_retried(self) -> None:
        view = PokeballView(self.drops)
        interaction = Mock()
        interaction.user.id = 1
        interaction.user.mention = "<@1>"
        interaction.response.edit_message = AsyncMock()
        interaction.response.send_message = AsyncMock()
        with patch.object(self.drops, "award", side_effect=[ValueError("write error"), "found XP!"]):
            await view.open_ball.callback(interaction)
            self.assertFalse(view.claimed)
            await view.open_ball.callback(interaction)
        self.assertTrue(view.claimed)
        await view.open_ball.callback(interaction)
        self.assertIn("already", interaction.response.send_message.await_args.args[0])

    async def test_only_live_incense_spawn_starts_timer(self) -> None:
        guild = Mock()
        guild.id = 7
        channel = Mock()
        channel.id = 8
        message = Mock(guild=guild, channel=channel)
        self.drops.data["categories"]["7"] = [9]
        self.drops.record_spawn(message)
        self.assertFalse(self.drops.tasks)
        self.bot.active_incenses["8"] = {"guild_id": 7, "expires_at": time.time() + 10}
        self.bot.muted_poketwo_channels.add(8)
        self.drops.record_spawn(message)
        self.assertFalse(self.drops.tasks)
        self.bot.muted_poketwo_channels.clear()
        self.drops.record_spawn(message)
        self.assertIn(7, self.drops.tasks)

    async def test_timer_sends_to_configured_accessible_text_channel(self) -> None:
        guild = Mock()
        guild.id = 7
        guild.me = Mock()
        channel = Mock()
        channel.id = 8
        channel.category_id = 9
        channel.send = AsyncMock(return_value=Mock())
        permissions = channel.permissions_for.return_value
        permissions.view_channel = True
        permissions.send_messages = True
        permissions.attach_files = True
        permissions.embed_links = True
        guild.text_channels = [channel]
        self.bot.get_guild.return_value = guild
        self.drops.data["categories"]["7"] = [9]
        self.drops.last_spawn[7] = time.monotonic()
        with patch("pokeball_drops.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError])):
            with self.assertRaises(asyncio.CancelledError):
                await self.drops.run_guild(7)
        channel.send.assert_awaited_once()
        self.assertIsInstance(channel.send.await_args.kwargs["view"], PokeballView)

    async def test_invalid_radiant_background_rejected(self) -> None:
        (self.root / "dyes.json").write_text(json.dumps({"dyes": [
            {"name": "Bad", "type": "background", "rarity": "radiant", "color": "#FFFFFF"},
        ]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_dyes(self.root / "dyes.json")

    async def test_category_configuration_requires_permission_and_persists(self) -> None:
        message = Mock()
        message.guild.id = 7
        message.guild.get_channel.return_value = Mock(spec=discord.CategoryChannel)
        message.author.guild_permissions.manage_guild = False
        message.content = "v!drops add 9"
        message.reply = AsyncMock()
        await self.drops.configure(message)
        self.assertNotIn("7", self.drops.data["categories"])
        message.author.guild_permissions.manage_guild = True
        await self.drops.configure(message)
        loaded = PokeballDrops(self.bot, self.drops.path, self.drops.catalog_path, save_profile_inventory)
        self.assertEqual(loaded.data["categories"]["7"], [9])
        message.content = "v!drops remove 9"
        await self.drops.configure(message)
        self.assertEqual(self.drops.data["categories"]["7"], [])

    async def test_inventory_pages_are_accessible(self) -> None:
        dyes = [{"code": f"{i:07X}", "name": "Pink", "type": "frame", "rarity": "normal", "color": "#FF88CC"} for i in range(11)]
        view = DyeInventoryView(1, dyes)
        interaction = Mock()
        interaction.response.edit_message = AsyncMock()
        await view.next.callback(interaction)
        self.assertIn("000000A", view.embed().description)
        self.assertTrue(view.next.disabled)

    async def test_profile_avatar_and_dye_render(self) -> None:
        from io import BytesIO
        avatar = BytesIO()
        Image.new("RGB", (110, 110), "red").save(avatar, format="PNG")
        normal = render_profile_image(PROFILE_DEFAULTS, PROFILE_STAT_DEFAULTS, username="Trainer", avatar=avatar.getvalue())
        dyed = render_profile_image(PROFILE_DEFAULTS, PROFILE_STAT_DEFAULTS, username="Trainer", avatar=avatar.getvalue(), dyes={"background": {"color": "#FF00FF", "rarity": "normal"}})
        with Image.open(normal) as image:
            self.assertEqual(image.getpixel((100, 100))[:3], (255, 0, 0))
            normal_pixel = image.getpixel((10, 10))
        with Image.open(dyed) as image:
            self.assertNotEqual(image.getpixel((10, 10)), normal_pixel)

    async def test_radiant_frame_dye_changes_render(self) -> None:
        settings = {**PROFILE_DEFAULTS, "frame": "mystic"}
        normal = render_profile_image(settings, PROFILE_STAT_DEFAULTS)
        radiant = render_profile_image(
            settings, PROFILE_STAT_DEFAULTS,
            dyes={"frame": {"color": "#FF88CC", "rarity": "radiant"}},
        )
        with Image.open(normal) as original, Image.open(radiant) as dyed:
            self.assertEqual(original.size, dyed.size)
            self.assertIsNotNone(ImageChops.difference(original.convert("RGB"), dyed.convert("RGB")).getbbox())


if __name__ == "__main__":
    unittest.main()
