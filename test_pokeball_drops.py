import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot import PROFILE_DEFAULTS, PROFILE_STAT_DEFAULTS, render_profile_image, save_profile_inventory
from pokeball_drops import BALL_LIFETIME, INTERVAL, DyeInventoryView, PokeballDrops, PokeballView, level_for_xp, load_dyes
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
            {"name": "Radiant", "type": "any", "rarity": "radiant", "color": "#FFD700", "color2": "#FF00FF"},
            {"name": "Glow", "type": "any", "rarity": "glow", "color": "#00FFFF", "color2": "#FF00FF"},
        ]}), encoding="utf-8")

    async def test_level_boundaries_and_xp_persistence(self) -> None:
        self.assertEqual([level_for_xp(x) for x in (0, 499, 500, 1099, 1100)], [0, 0, 1, 1, 2])
        with patch("pokeball_drops.random.randrange", side_effect=[1, 1, 1, 0]), patch("pokeball_drops.random.randint", return_value=500):
            self.assertIn("level 1", self.drops.award(1))
        loaded = PokeballDrops(self.bot, self.drops.path, self.drops.catalog_path, save_profile_inventory)
        self.assertEqual(loaded.level(1), 1)

    async def test_coins_and_unlucky_zero(self) -> None:
        with patch("pokeball_drops.random.randrange", side_effect=[1, 1, 1, 1]), patch("pokeball_drops.random.randint", return_value=1000):
            self.assertIn("1,000", self.drops.award(1))
        self.assertEqual(self.bot.profile_inventory["1"]["balances"]["Pokédollar"], 1000)
        self.assertTrue(self.bot.profile_inventory_path.is_file())
        with patch("pokeball_drops.random.randrange", side_effect=[1, 1, 1, 0]), patch("pokeball_drops.random.randint", return_value=0):
            self.assertIn("unlucky", self.drops.award(1))

    async def test_rare_roll_boundaries_and_missing_catalog(self) -> None:
        self.catalog()
        for rolls, rarity in [([0, 5], "glow"), ([1, 0, 6], "radiant"), ([1, 1, 0, 7], "normal")]:
            with patch("pokeball_drops.random.randrange", side_effect=rolls), patch("pokeball_drops.random.choice", side_effect=lambda values: values[0]):
                self.assertIn(rarity, self.drops.award(1))
        self.assertEqual(len(self.drops.data["users"]["1"]["dyes"]), 3)
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
        with patch("pokeball_drops.random.randrange", side_effect=[1, 1, 0, 1]), patch("pokeball_drops.random.choice", side_effect=lambda values: values[0]):
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
        view.deadline = time.monotonic() + BALL_LIFETIME
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

    async def test_pokeball_expires_after_ten_seconds_even_when_claimed(self) -> None:
        self.assertEqual(INTERVAL, 180)
        self.assertEqual(BALL_LIFETIME, 10)
        for claimed in (False, True):
            with self.subTest(claimed=claimed):
                view = PokeballView(self.drops)
                view.message = Mock()
                view.message.delete = AsyncMock()
                view.message.edit = AsyncMock()
                view.claimed = claimed
                with (
                    patch("pokeball_drops.time", SimpleNamespace(monotonic=lambda: 100.0)),
                    patch("pokeball_drops.asyncio.sleep", new=AsyncMock()) as sleep,
                ):
                    view.start_expiry()
                    task = next(iter(self.drops.expiry_tasks))
                    await task
                sleep.assert_awaited_once_with(10)
                view.message.delete.assert_not_awaited()
                kwargs = view.message.edit.await_args.kwargs
                self.assertIs(kwargs["view"], view)
                self.assertTrue(view.open_ball.disabled)
                if claimed:
                    self.assertNotIn("content", kwargs)
                else:
                    self.assertEqual(kwargs["content"], "This Pokéball expired.")
                self.assertNotIn("attachments", kwargs)

    async def test_claim_rejected_at_expiry_without_reward(self) -> None:
        view = PokeballView(self.drops)
        view.deadline = 100.0
        interaction = Mock()
        interaction.user.id = 1
        interaction.response.send_message = AsyncMock()
        with (
            patch("pokeball_drops.time", SimpleNamespace(monotonic=lambda: 100.0)),
            patch.object(self.drops, "award") as award,
        ):
            await view.open_ball.callback(interaction)
        award.assert_not_called()
        self.assertIn("expired", interaction.response.send_message.await_args.args[0])

    async def test_timer_sends_to_configured_accessible_text_channel(self) -> None:
        guild = Mock()
        guild.id = 7
        guild.me = Mock()
        channel = Mock()
        channel.id = 8
        channel.mention = "<#8>"
        channel.category_id = 9
        drop = Mock()
        drop.jump_url = "https://discord.com/channels/7/8/99"
        drop.created_at = discord.utils.utcnow()
        channel.send = AsyncMock(return_value=drop)
        log_channel = Mock(spec=discord.TextChannel)
        log_channel.send = AsyncMock()
        guild.get_channel.return_value = log_channel
        permissions = channel.permissions_for.return_value
        permissions.view_channel = True
        permissions.send_messages = True
        permissions.attach_files = True
        permissions.embed_links = True
        guild.text_channels = [channel]
        self.bot.get_guild.return_value = guild
        self.drops.data["categories"]["7"] = [9]
        self.drops.data["log_channels"]["7"] = 55
        self.drops.last_spawn[7] = time.monotonic()
        with patch("pokeball_drops.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError])) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await self.drops.run_guild(7)
        self.assertEqual(sleep.await_args_list[0].args, (180,))
        channel.send.assert_awaited_once()
        drop_args = channel.send.await_args.kwargs
        self.assertEqual(drop_args["content"], "<@&1569492287732449411>")
        self.assertEqual(
            [role.id for role in drop_args["allowed_mentions"].roles],
            [1569492287732449411],
        )
        self.assertIsInstance(drop_args["view"], PokeballView)
        log_channel.send.assert_awaited_once()
        self.assertEqual(log_channel.send.await_args.kwargs["view"].children[0].url, drop.jump_url)

    async def test_invalid_dye_rarity_rejected(self) -> None:
        (self.root / "dyes.json").write_text(json.dumps({"dyes": [
            {"name": "Bad", "type": "background", "rarity": "mythic", "color": "#FFFFFF"},
        ]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_dyes(self.root / "dyes.json")

    async def test_shipped_catalog_is_valid(self) -> None:
        dyes = load_dyes(Path(__file__).with_name("data") / "dyes.json")
        for rarity in ("normal", "radiant", "glow"):
            self.assertEqual(sum(dye["rarity"] == rarity for dye in dyes), 50)
        self.assertTrue(all((Path(__file__).parent / dye["image"]).is_file() for dye in dyes))

    async def test_universal_dye_is_consumed_and_listed_as_used(self) -> None:
        self.catalog()
        self.bot.profile_inventory = {"1": {"balances": {}, "assets": [
            {"code": "CCCCCCC", "type": "frame", "key": "mystic"},
        ]}}
        with patch("pokeball_drops.random.randrange", side_effect=[0, 1]), patch("pokeball_drops.random.choice", side_effect=lambda values: values[0]):
            self.drops.award(1)
        code = self.drops.data["users"]["1"]["dyes"][0]["code"]
        message = Mock()
        message.author.id = 1
        message.reply = AsyncMock()
        message.content = f"v!dye {code} CCCCCCC"
        await self.drops.dye(message)
        user = self.drops.data["users"]["1"]
        self.assertEqual(user["dyes"], [])
        self.assertEqual(user["used"][0]["code"], code)
        message.content = "v!useddyes"
        await self.drops.used_dyes(message)
        embed = message.reply.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "Used dyes")
        self.assertEqual(embed.image.url, "attachment://dyes.png")
        PokeballDrops(self.bot, self.drops.path, self.drops.catalog_path, save_profile_inventory)

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
        message.content = "v!drops 10 11 10"
        await self.drops.configure(message)
        message.content = "v!drops add 12"
        await self.drops.configure(message)
        loaded = PokeballDrops(self.bot, self.drops.path, self.drops.catalog_path, save_profile_inventory)
        self.assertEqual(loaded.data["categories"]["7"], [9, 10, 11, 12])
        message.content = "v!drops list"
        await self.drops.configure(message)
        self.assertIn("`11`", message.reply.await_args.args[0])
        message.content = "v!drops remove 9 10"
        await self.drops.configure(message)
        self.assertEqual(self.drops.data["categories"]["7"], [11, 12])

    async def test_invalid_category_rejects_entire_batch(self) -> None:
        message = Mock()
        message.guild.id = 7
        message.guild.get_channel.side_effect = lambda category_id: (
            Mock(spec=discord.CategoryChannel) if category_id == 9 else None
        )
        message.author.guild_permissions.manage_guild = True
        message.content = "v!drops 9 10"
        message.reply = AsyncMock()
        await self.drops.configure(message)
        self.assertNotIn("7", self.drops.data["categories"])
        self.assertIn("`10`", message.reply.await_args.args[0])

    async def test_configure_drop_log_validates_and_persists_per_server(self) -> None:
        message = Mock()
        message.guild.id = 7
        message.author.guild_permissions.manage_guild = False
        message.reply = AsyncMock()
        log_channel = Mock(spec=discord.TextChannel)
        log_channel.id = 55
        log_channel.mention = "<#55>"
        log_channel.permissions_for.return_value.view_channel = True
        log_channel.permissions_for.return_value.send_messages = True
        message.guild.get_channel.return_value = log_channel
        message.content = "v!droplog <#55>"
        await self.drops.configure_log(message)
        self.assertEqual(self.drops.data["log_channels"], {})
        message.author.guild_permissions.manage_guild = True
        message.guild.get_channel.return_value = None
        await self.drops.configure_log(message)
        self.assertIn("text channel", message.reply.await_args.args[0])
        self.assertEqual(self.drops.data["log_channels"], {})
        message.guild.get_channel.return_value = log_channel
        log_channel.permissions_for.return_value.send_messages = False
        await self.drops.configure_log(message)
        self.assertIn("Send Messages", message.reply.await_args.args[0])
        self.assertEqual(self.drops.data["log_channels"], {})
        log_channel.permissions_for.return_value.send_messages = True
        await self.drops.configure_log(message)
        loaded = PokeballDrops(self.bot, self.drops.path, self.drops.catalog_path, save_profile_inventory)
        self.assertEqual(loaded.data["log_channels"], {"7": 55})
        message.guild.id = 8
        message.content = "v!droplog 55"
        await self.drops.configure_log(message)
        message.guild.id = 7
        message.content = "v!droplog off"
        await self.drops.configure_log(message)
        self.assertEqual(self.drops.data["log_channels"], {"8": 55})

    async def test_drop_logs_use_exact_message_link_and_remain_after_expiry(self) -> None:
        guild = Mock()
        guild.id = 7
        channel = Mock()
        channel.mention = "<#8>"
        log_channel = Mock(spec=discord.TextChannel)
        log_channel.send = AsyncMock()
        guild.get_channel.return_value = log_channel
        message = Mock()
        message.jump_url = "https://discord.com/channels/7/8/99"
        message.created_at = discord.utils.utcnow()
        message.delete = AsyncMock()
        message.edit = AsyncMock()
        self.drops.data["log_channels"]["7"] = 55
        await self.drops.log_drop(guild, channel, message)
        args = log_channel.send.await_args
        self.assertIn("<#8>", args.args[0])
        self.assertIn(f"<t:{int(message.created_at.timestamp())}:F>", args.args[0])
        self.assertEqual(args.kwargs["view"].children[0].url, message.jump_url)
        view = PokeballView(self.drops)
        view.message = message
        view.deadline = 100
        with (
            patch("pokeball_drops.time", SimpleNamespace(monotonic=lambda: 110)),
            patch("pokeball_drops.asyncio.sleep", new=AsyncMock()),
        ):
            await view.expire()
        message.delete.assert_not_awaited()
        message.edit.assert_awaited_once_with(content="This Pokéball expired.", view=view)
        self.assertTrue(view.open_ball.disabled)
        log_channel.send.assert_awaited_once()

    async def test_missing_log_channel_and_send_failure_are_logged(self) -> None:
        guild = Mock()
        guild.id = 7
        channel = Mock()
        message = Mock()
        self.drops.data["log_channels"]["7"] = 55
        guild.get_channel.return_value = None
        with self.assertLogs("vivillon_naming", level="WARNING") as logged:
            await self.drops.log_drop(guild, channel, message)
        self.assertIn("not found", logged.output[0])
        log_channel = Mock(spec=discord.TextChannel)
        response = Mock(status=403, reason="Forbidden")
        log_channel.send = AsyncMock(side_effect=discord.Forbidden(response, "No permission"))
        guild.get_channel.return_value = log_channel
        channel.mention = "<#8>"
        message.jump_url = "https://discord.com/channels/7/8/99"
        message.created_at = discord.utils.utcnow()
        with self.assertLogs("vivillon_naming", level="ERROR") as logged:
            await self.drops.log_drop(guild, channel, message)
        self.assertIn("Could not send", logged.output[0])

    async def test_inventory_pages_are_accessible(self) -> None:
        dyes = [{"code": f"{i:07X}", "name": "Pink", "type": "frame", "rarity": "normal", "color": "#FF88CC"} for i in range(11)]
        view = DyeInventoryView(1, dyes)
        interaction = Mock()
        interaction.response.edit_message = AsyncMock()
        await view.next.callback(interaction)
        self.assertEqual(view.items()[0]["code"], "000000A")
        self.assertIn("000000A", view.file().description)
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
            dyes={"frame": {"color": "#FF88CC", "rarity": "glow", "color2": "#00FFFF"}},
        )
        with Image.open(normal) as original, Image.open(radiant) as dyed:
            self.assertEqual(original.size, dyed.size)
            self.assertIsNotNone(ImageChops.difference(original.convert("RGB"), dyed.convert("RGB")).getbbox())


if __name__ == "__main__":
    unittest.main()
