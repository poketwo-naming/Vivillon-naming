import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord.components import _component_factory

from daycare import (
    BOX_LIMIT,
    BoxStore,
    DaycareFeature,
    build_candidates,
    egg_groups_for,
    find_pairs,
    load_settings,
    parse_pokemon_lines,
)

SAMPLE = """`52913`　<:litwick:123> **Litwick** <:male:1> "snack" • Lvl. 14 • 79.57%
`52916`　<:litwick:123> **✨ Litwick** <:female:2> • Lvl. 27 • 79.57%
`30113`　**Marine Vivillon** ♂ • Lvl. 3 • 75.81%
not a pokemon line"""


class DaycareTests(unittest.TestCase):
    def test_parse_lines(self) -> None:
        parsed = dict(parse_pokemon_lines([SAMPLE]))
        self.assertEqual(parsed["52913"], ["Litwick", "M", 79.57, False])
        self.assertEqual(parsed["52916"], ["Litwick", "F", 79.57, True])
        self.assertEqual(parsed["30113"], ["Marine Vivillon", "M", 75.81, False])
        self.assertEqual(len(parsed), 3)

    def test_nickname_does_not_change_gender(self) -> None:
        parsed = dict(
            parse_pokemon_lines(['`1` **Eevee** <:female:2> "male" • Lvl. 1 • 50.00%'])
        )
        self.assertEqual(parsed["1"][1], "F")

    def test_egg_groups(self) -> None:
        self.assertTrue(egg_groups_for("Marine Vivillon"))
        self.assertTrue(egg_groups_for("Alolan Raichu"))
        self.assertTrue(egg_groups_for("Mr. Mime"))
        self.assertEqual(egg_groups_for("Notapokemon"), ())

    def test_pairs_share_group_and_opposite_gender(self) -> None:
        entries = {
            "1": ["Litwick", "M", 90.0, False],
            "2": ["Litwick", "M", 50.0, False],
            "3": ["Litwick", "F", 80.0, False],
            "4": ["Pikachu", "F", 99.0, False],
            "5": ["Mewtwo", "F", 99.0, False],
            "6": ["Litwick", "F", 99.0, True],
        }
        pairs = find_pairs(build_candidates(entries, False), 2)
        self.assertEqual([(m.code, f.code) for m, f in pairs], [("1", "3")])
        shiny = find_pairs(build_candidates(entries, True), 1)
        self.assertEqual([(m.code, f.code) for m, f in shiny], [("1", "6")])

    def test_ditto_is_fallback_partner(self) -> None:
        entries = {
            "1": ["Pikachu", "M", 90.0, False],
            "2": ["Ditto", "N", 10.0, False],
        }
        pairs = find_pairs(build_candidates(entries, False), 1)
        self.assertEqual({c.code for c in pairs[0]}, {"1", "2"})

    def test_store_limit_and_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boxes.json"
            store = BoxStore(path)
            slug = store.create_box(1, "Draco")
            parsed = [(str(i), ["Litwick", "M", 1.0, False]) for i in range(BOX_LIMIT + 5)]
            added, present, skipped = store.add_entries(1, slug, parsed)
            self.assertEqual((added, present, skipped), (BOX_LIMIT, 0, 5))
            with self.assertRaises(ValueError):
                store.create_box(1, "draco")
            reloaded = BoxStore(path)
            self.assertEqual(len(reloaded.boxes(1)["draco"]["entries"]), BOX_LIMIT)
            self.assertEqual(reloaded.find_box(1, "Draco"), "draco")

    def test_settings_defaults(self) -> None:
        self.assertEqual(load_settings({"pairs": 5, "grace": "x"})["pairs"], 1)
        self.assertEqual(load_settings(None)["grace"], 1)


class DaycareAppendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.feature = DaycareFeature(Path(self.directory.name) / "boxes.json", 123)
        self.feature.store.create_box(1, "event")
        self.list_message = Mock(spec=discord.Message)
        self.list_message.id = 42
        self.list_message.author = SimpleNamespace(id=123)
        self.list_message.content = ""
        self.list_message.components = []
        self.list_message.embeds = [
            discord.Embed(
                title="Your pokémon",
                description=(
                    "`42615` <:eevee:123> **Eevee** ♀ • Lvl. 2 • 88.17%\n"
                    "`40427` <:eevee:123> **Eevee** ♂ • Lvl. 26 • 85.48%"
                ),
            )
        ]
        self.message = SimpleNamespace(
            author=SimpleNamespace(id=1),
            reference=SimpleNamespace(resolved=self.list_message, message_id=42),
            channel=SimpleNamespace(fetch_message=AsyncMock(return_value=self.list_message)),
            reply=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())),
        )

    async def test_reply_to_list_stores_pokemon_and_tracks_pages(self) -> None:
        await self.feature.box_append(self.message, "event")
        entries = self.feature.store.boxes(1)["event"]["entries"]
        self.assertEqual(entries["42615"], ["Eevee", "F", 88.17, False])
        self.assertEqual(entries["40427"], ["Eevee", "M", 85.48, False])
        self.assertIn(42, self.feature.tracked)
        self.message.channel.fetch_message.assert_not_awaited()

    async def test_incomplete_resolved_message_is_fetched(self) -> None:
        incomplete = Mock(spec=discord.Message)
        incomplete.author = SimpleNamespace(id=123)
        incomplete.content = ""
        incomplete.embeds = []
        incomplete.components = []
        self.message.reference.resolved = incomplete
        await self.feature.box_append(self.message, "event")
        self.message.channel.fetch_message.assert_awaited_once_with(42)
        self.assertEqual(len(self.feature.store.boxes(1)["event"]["entries"]), 2)

    async def test_wrong_author_reports_configuration_problem(self) -> None:
        self.list_message.author.id = 456
        await self.feature.box_append(self.message, "event")
        self.assertIn("POKETWO_BOT_ID", self.message.reply.await_args.args[0])
        self.assertFalse(self.feature.store.boxes(1)["event"]["entries"])

    async def test_fetched_message_without_embeds_reports_missing_access(self) -> None:
        self.list_message.embeds = []
        await self.feature.box_append(self.message, "event")
        self.assertIn("list content", self.message.reply.await_args.args[0].lower())
        self.assertFalse(self.feature.store.boxes(1)["event"]["entries"])

    async def test_fetch_failure_reports_permission_error(self) -> None:
        self.message.reference.resolved = None
        response = Mock(status=403, reason="Forbidden")
        self.message.channel.fetch_message.side_effect = discord.Forbidden(response, "Forbidden")
        await self.feature.box_append(self.message, "event")
        self.assertIn("403", self.message.reply.await_args.args[0])
        self.assertFalse(self.feature.store.boxes(1)["event"]["entries"])

    async def test_paging_adds_new_entries(self) -> None:
        await self.feature.box_append(self.message, "event")
        payload = SimpleNamespace(
            message_id=42,
            data={"embeds": [{"description": "`45258` **Eevee** ♂ • Lvl. 39 • 84.95%"}]},
        )
        await self.feature.handle_raw_edit(payload)
        self.assertEqual(
            self.feature.store.boxes(1)["event"]["entries"]["45258"],
            ["Eevee", "M", 84.95, False],
        )

    async def test_component_list_and_pages(self) -> None:
        self.list_message.embeds = []
        self.list_message.components = [
            _component_factory({
                "type": 17,
                "components": [
                    {"type": 10, "content": "**Your pokémon**"},
                    {"type": 10, "content": (
                        "`42615` <:eevee:123> **Eevee** ♀ • Lvl. 2 • 88.17%\n"
                        "`40427` <:eevee:123> **Eevee** ♂ • Lvl. 26 • 85.48%"
                    )},
                ],
            })
        ]
        await self.feature.box_append(self.message, "event")
        entries = self.feature.store.boxes(1)["event"]["entries"]
        self.assertEqual(entries["42615"], ["Eevee", "F", 88.17, False])
        self.assertEqual(entries["40427"], ["Eevee", "M", 85.48, False])
        self.message.channel.fetch_message.assert_not_awaited()
        await self.feature.handle_raw_edit(SimpleNamespace(
            message_id=42,
            data={"components": [{"type": 17, "components": [
                {"type": 10, "content": "`45258` **Eevee** ♂ • Lvl. 39 • 84.95%"}
            ]}]},
        ))
        self.assertEqual(entries["45258"], ["Eevee", "M", 84.95, False])

    async def test_plain_text_list(self) -> None:
        self.list_message.embeds = []
        self.list_message.content = "`42615` **Eevee** ♀ • Lvl. 2 • 88.17%"
        await self.feature.box_append(self.message, "event")
        self.assertEqual(
            self.feature.store.boxes(1)["event"]["entries"]["42615"],
            ["Eevee", "F", 88.17, False],
        )


if __name__ == "__main__":
    unittest.main()
