import asyncio
import image_match
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast
from unittest import mock
from unittest.mock import AsyncMock, Mock, call, patch

import discord
import bot as bot_module
from data_paths import data_path
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from bot import (
    add_shinyhunter,
    add_reserve_category,
    append_reserve_category_pokemon,
    clear_shinyhunter,
    delete_reserve_category,
    expand_reserve_category_names,
    format_reserve_category_embeds,
    add_reservations_bulk,
    build_grab_lines,
    grab_display_name,
    grab_reserve_pairs,
    parse_grab_entries,
    exchange_reservations,
    parse_exchange_list,
    add_collection_pokemon,
    migrate_legacy_all_keys,
    all_forms_reservation_key,
    clear_guild_reservations,
    clear_guild_collection,
    clear_guild_type_pings,
    clear_guild_shinyhunts,
    clear_user_collection,
    collection_pokemon_for_user,
    collection_user_ids_for_pokemon,
    split_collection_add_names,
    format_catch_command,
    format_guess,
    shown_form_name,
    format_all_forms_reservation_embeds,
    format_collection_embeds,
    format_collection_add_confirmation,
    format_pokemon_reserver_embeds,
    format_remove_confirmation,
    format_reservation_embeds,
    format_server_reservation_embeds,
    format_shinyhunt_confirmation,
    format_type_spawn_embed,
    format_pc_catch_embed,
    catch_card_files,
    format_custom_type_spawn_reply,
    fire_companion_icon_filename_for_pokemon,
    is_normal_icon_pokemon,
    normal_companion_icon_filename_for_pokemon,
    is_electric_icon_pokemon,
    electric_companion_icon_filename_for_pokemon,
    is_fire_icon_pokemon,
    is_water_icon_pokemon,
    is_grass_icon_pokemon,
    is_ice_icon_pokemon,
    water_companion_icon_filename_for_pokemon,
    format_spawn_mention_lines,
    format_spawn_reply,
    format_shinyhunt_status,
    format_starboard_embed,
    is_valid_pokemon_name,
    is_image_test_command,
    command_permission_group,
    collection_user_ids_for_pokemon,
    format_reserved_pokemon_names,
    is_premium_only_command,
    can_use_permission_group,
    has_manage_server_access,
    is_missingno_name,
    is_normal_starboard_pokemon,
    is_single_type_fire_pokemon,
    is_single_type_normal_pokemon,
    is_single_type_water_pokemon,
    is_single_type_ice_pokemon,
    is_single_type_electric_pokemon,
    type_icon_filename_for_pokemon,
    load_pokemon_forms,
    load_server_settings,
    load_command_permissions,
    load_command_locks,
    load_auto_pause_incense_settings,
    load_starboard_settings,
    load_reservations,
    load_reserve_categories,
    _org_api_port_from_environment,
    is_known_pokemon_name,
    parse_reserve_add_command,
    parse_reserve_remove_command,
    parse_add_reserve_category_command,
    parse_create_reserve_category_command,
    parse_delete_reserve_category_command,
    parse_collection_add_command,
    parse_shinyhunt_command,
    parse_shinyhunt_remove_command,
    ReservationPagesView,
    NamingSettingsView,
    StarboardSettingsView,
    parse_catch_details,
    starboard_art_url,
    starboard_category,
    ServerSettingsView,
    remove_reservation,
    remove_reservations,
    remove_collection_pokemon,
    reservation_key,
    reservation_key_for_command,
    reserved_pokemon_for_user,
    reserved_user_ids_for_pokemon,
    save_reservations,
    save_command_permissions,
    save_reserve_categories,
    shinyhunt_pokemon_for_user,
    shinyhunter_user_ids_for_pokemon,
    remove_shinyhunter,
    pokemon_matches_all_forms_reservation,
    poketwo_incense_action,
    POKETWO_COMMAND_BOT_ID,
    SERVER_ID,
    SERVER_IDS,
    RESERVE_ROLE_ID,
    ActiveIncense,
    reservation_key,
    Config,
    NamingBot,
    AFKSettingsView,
    format_profile_iv_record,
    load_afk_settings,
    load_type_pings,
    load_profile_data,
    ProfileIvRecord,
    PROFILE_EMOJI_URLS,
    PROFILE_FRAME_ALPHA_GAMMA,
    PROFILE_FRAME_CANVAS_SIZE,
    PROFILE_FRAME_CORNER_RADIUS,
    PROFILE_FRAME_OPENINGS,
    PROFILE_FRAME_SCALES,
    PROFILE_CARD_SCALES,
    PROFILE_FLOWER_SPRING_USER_ID,
    PROFILE_JIRACHI_USER_ID,
    PROFILE_RETURN_TO_ME,
    PROFILE_MARSHADOW_USER_ID,
    PROFILE_MOONLIT_USER_ID,
    PROFILE_DEFAULTS,
    save_profile_data,
    save_type_pings,
    type_ping_user_ids_for_pokemon,
    TYPE_PING_TYPES,
    TypePingView,
    ClearTypePingsView,
    render_profile_image,
    profile_background_tint,
    ProfileView,
    ProfileEditView,
    ProfileMusicSelect,
    count_qualifying_sentences,
    ChatEventSession,
    EventMenuView,
    parse_chat_event_duration,
)


T = TypeVar("T")


def require_not_none(value: T | None) -> T:
    if value is None:
        raise AssertionError("Expected a non-None value")
    return value


def awaited_kwargs(mock: Any) -> dict[str, Any]:
    call_args = mock.await_args
    if call_args is None:
        raise AssertionError("Expected the mock to be awaited")
    return call_args.kwargs


def awaited_args(mock: Any) -> tuple[Any, ...]:
    call_args = mock.await_args
    if call_args is None:
        raise AssertionError("Expected the mock to be awaited")
    return call_args.args


def runtime_attribute(value: object, name: str) -> Any:
    try:
        return getattr(value, name)
    except AttributeError as error:
        raise AssertionError(f"Expected runtime attribute {name!r}") from error


def set_runtime_attribute(value: object, name: str, new_value: Any) -> None:
    if not hasattr(value, name):
        raise AssertionError(f"Expected runtime attribute {name!r}")
    setattr(value, name, new_value)


def embed_description(embed: discord.Embed) -> str:
    return require_not_none(embed.description)


def rgba_pixel(image: Image.Image, position: tuple[int, int]) -> tuple[int, int, int, int]:
    pixel = image.getpixel(position)
    if not isinstance(pixel, tuple) or len(pixel) != 4:
        raise AssertionError("Expected an RGBA pixel")
    return cast(tuple[int, int, int, int], pixel)


def profile_frame_alpha(alpha: int) -> int:
    return round(255 * (alpha / 255) ** PROFILE_FRAME_ALPHA_GAMMA)


class ConfigTests(unittest.TestCase):
    def load_config(self, **environment: str) -> Config:
        variables = {
            "DISCORD_TOKEN": "test-token",
            "POKETWO_BOT_ID": "12345",
            "CODESPACES": "true",
            "CODESPACE_NAME": "bookish-space-xylophone-gx67456vpq4whwpqx",
            **environment,
        }
        with patch.dict("os.environ", variables, clear=True):
            return Config.from_environment()

    def test_rejects_unauthorized_codespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "designated Codespace"):
            self.load_config(CODESPACE_NAME="another-codespace")

    def test_rejects_non_codespace_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "designated Codespace"):
            self.load_config(CODESPACES="false")

    def test_allows_external_host_when_opted_in(self) -> None:
        config = self.load_config(CODESPACES="false", ALLOW_EXTERNAL_HOST="true")
        self.assertEqual(config.poketwo_bot_id, 12345)

    def test_openai_key_is_optional(self) -> None:
        self.assertIsNone(self.load_config().openai_api_key)
        self.assertEqual(
            self.load_config(OPENAI_API_KEY=" abc ").openai_api_key, "abc"
        )

    def test_configures_concurrent_vision_request_limit(self) -> None:
        config = self.load_config(MAX_CONCURRENT_VISION_REQUESTS="8")

        self.assertEqual(config.max_concurrent_vision_requests, 8)


    def test_defaults_to_300_concurrent_vision_requests(self) -> None:
        self.assertEqual(
            self.load_config().max_concurrent_vision_requests,
            300,
        )

    def test_allows_300_concurrent_vision_requests(self) -> None:
        config = self.load_config(MAX_CONCURRENT_VISION_REQUESTS="300")

        self.assertEqual(config.max_concurrent_vision_requests, 300)

    def test_rejects_invalid_vision_request_limit(self) -> None:
        for value in ("0", "-1", "301", "many"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load_config(MAX_CONCURRENT_VISION_REQUESTS=value)

    def test_org_api_port_prefers_explicit_then_host_then_generic_port(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ORG_API_PORT": "1111",
                "SERVER_PORT": "2222",
                "PORT": "3333",
            },
            clear=True,
        ):
            self.assertEqual(_org_api_port_from_environment(), 1111)
        with patch.dict(
            "os.environ", {"SERVER_PORT": "2222", "PORT": "3333"}, clear=True
        ):
            self.assertEqual(_org_api_port_from_environment(), 2222)
        with patch.dict("os.environ", {"PORT": "3333"}, clear=True):
            self.assertEqual(_org_api_port_from_environment(), 3333)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_org_api_port_from_environment(), 8080)

    def test_org_api_port_reports_invalid_environment_value(self) -> None:
        with patch.dict("os.environ", {"SERVER_PORT": "invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "SERVER_PORT"):
                _org_api_port_from_environment()


class RecognitionValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_vision_prompt_includes_custom_form_names(self) -> None:
        import bot

        client = Mock()
        client.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"name":"Enchanted Applin","confidence":98}'
                        )
                    )
                ]
            )
        )

        result = await bot.request_prediction(
            "https://example.test/spawn.png",
            client=client,
            model="test-model",
            detail="low",
        )

        self.assertEqual(result, ("Enchanted Applin", 98.0))
        prompt = awaited_kwargs(client.chat.completions.create)["messages"][0][
            "content"
        ]
        self.assertIn("Enchanted Applin (base species: Applin)", prompt)
        self.assertIn("return its exact listed form name", prompt)
        self.assertIn("Palafin has a red, heart-shaped mark", prompt)
        self.assertIn("Finizen does not", prompt)
        self.assertIn("focus on the largest embedded wild-spawn artwork", prompt)
        self.assertIn("ignore surrounding chat, UI text, other bot", prompt)
        self.assertIn("reserve low confidence for genuinely ambiguous", prompt)
        self.assertIn("Always provide your single best Pokémon guess", prompt)

    async def test_inconclusive_local_match_uses_vision_prediction(self) -> None:
        import bot

        image_bytes = b"spawn image"
        matcher = Mock(entries=["Finizen"])
        client = Mock()
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(image_bytes, "image/png")),
            ),
            patch("bot.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch(
                "bot.request_prediction",
                new=AsyncMock(return_value=("Palafin", 97.0)),
            ) as request_prediction,
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=client,
                http=Mock(),
                model="test-model",
                matcher=matcher,
            )

        self.assertEqual(result, ("Palafin", 97.0))
        request_prediction.assert_awaited_once()

    async def test_unverified_vision_vivillon_prediction_is_named_at_low_confidence(
        self,
    ) -> None:
        import bot

        image_bytes = b"spawn image"
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(image_bytes, "image/png")),
            ),
            patch("bot.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch(
                "bot.request_prediction",
                new=AsyncMock(return_value=("Vivillon", 99.0)),
            ),
            patch("bot.vivillon_form_by_pattern", return_value=None),
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=Mock(),
                http=Mock(),
                model="test-model",
            )

        self.assertEqual(result, ("Vivillon", 49.99))

    def test_squawkabilly_colour_confirmed_guess_is_not_low_confidence(self) -> None:
        import bot

        name = "Yellow-Plumage Squawkabilly"
        matcher = Mock()
        matcher.best_guess.return_value = (name, 20)

        with patch("bot.squawkabilly_form_by_color", return_value=name):
            self.assertEqual(
                bot.local_fallback_prediction(matcher, b"x"),
                (name, bot.CORROBORATED_CONFIDENCE_FLOOR),
            )
        with patch("bot.squawkabilly_form_by_color", return_value=None):
            prediction = bot.local_fallback_prediction(matcher, b"x")
            if prediction is None:
                self.fail("Expected a low-confidence fallback prediction")
            self.assertLess(prediction[1], 50)

    async def test_local_matcher_agreement_raises_low_confidence_prediction_to_alert_cutoff(
        self,
    ) -> None:
        import bot

        matcher = Mock(entries=["Wiglett"])
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ),
            patch(
                "bot.asyncio.to_thread",
                new=AsyncMock(side_effect=[None, ("Wiglett", 6)]),
            ),
            patch(
                "bot.request_prediction",
                new=AsyncMock(return_value=("Wiglett", 2.0)),
            ),
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=Mock(),
                http=Mock(),
                model="test-model",
                matcher=matcher,
            )

        self.assertEqual(result, ("Wiglett", 85.0))

    async def test_weak_local_agreement_does_not_raise_low_confidence_prediction(
        self,
    ) -> None:
        import bot

        matcher = Mock(entries=["Wiglett"])
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ),
            patch(
                "bot.asyncio.to_thread",
                new=AsyncMock(side_effect=[None, ("Wiglett", 3)]),
            ),
            patch(
                "bot.request_prediction",
                new=AsyncMock(return_value=("Wiglett", 2.0)),
            ),
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=Mock(),
                http=Mock(),
                model="test-model",
                matcher=matcher,
            )

        self.assertEqual(result, ("Wiglett", 2.0))

    async def test_reference_match_log_includes_split_timings(self) -> None:
        import bot

        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ),
            patch(
                "bot.asyncio.to_thread",
                new=AsyncMock(return_value=("Pikachu", 12)),
            ),
            patch("bot.logger.info") as log_info,
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=None,
                http=Mock(),
                model="test-model",
                matcher=Mock(entries=["Pikachu"]),
            )

        self.assertEqual(result, ("Pikachu", 100.0))
        self.assertEqual(
            log_info.call_args.args[0],
            "Matched %s from reference images (%d votes) "
            "[download %.2fs, match %.2fs]",
        )
        rendered_log = log_info.call_args.args[0] % log_info.call_args.args[1:]
        self.assertRegex(
            rendered_log,
            r"\[download \d+\.\d{2}s, match \d+\.\d{2}s\]$",
        )

    @unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
    async def test_user_reference_images_recognized_at_full_confidence(self) -> None:
        matcher = image_match.ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        root = Path(__file__).with_name("pokemon_images")
        for folder, display in (
            ("Alolan Vulpix", "Alolan Vulpix"),
            ("Unown Variant 4", "D Unown"),
            ("Drizzile", "Drizzile"),
            ("Flamigo", "Flamigo"),
            ("Milcery", "Milcery"),
            ("Ralts", "Ralts"),
            ("Toedscool", "Toedscool"),
            ("Wingull", "Wingull"),
            ("Ditto", "Ditto"),
        ):
            with self.subTest(pokemon=folder):
                image = (root / folder / "user-reference-2026-11-07.png").read_bytes()
                with patch(
                    "bot.download_image",
                    new=AsyncMock(return_value=(image, "image/png")),
                ):
                    name, confidence = await bot_module.recognize_pokemon(
                        "https://example.test/spawn.png",
                        client=None,
                        http=Mock(),
                        model="test-model",
                        matcher=matcher,
                    )
                self.assertEqual(name, folder)
                self.assertEqual(bot_module.display_pokemon_name(name), display)
                self.assertEqual(confidence, 100.0)

    @unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
    async def test_user_q_unown_reference_is_recognized_at_full_confidence(self) -> None:
        matcher = image_match.ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image = (
            Path(__file__).with_name("pokemon_images")
            / "Q Unown"
            / "user-reference-2026-11-13.png"
        ).read_bytes()
        decoded = image_match.cv2.imdecode(
            image_match.np.frombuffer(image, image_match.np.uint8),
            image_match.cv2.IMREAD_UNCHANGED,
        )
        success, flipped = image_match.cv2.imencode(
            ".png", image_match.cv2.flip(decoded, 1)
        )
        self.assertTrue(success)
        for candidate in (image, flipped.tobytes()):
            with self.subTest(mirrored=candidate is not image):
                with patch(
                    "bot.download_image",
                    new=AsyncMock(return_value=(candidate, "image/png")),
                ):
                    name, confidence = await bot_module.recognize_pokemon(
                        "https://example.test/spawn.png",
                        client=None,
                        http=Mock(),
                        model="test-model",
                        matcher=matcher,
                    )
                self.assertEqual(name, "Q Unown")
                self.assertEqual(confidence, 100.0)

    async def test_no_reference_match_uses_low_confidence_local_guess(self) -> None:
        import bot

        matcher = Mock(entries=["Pikachu"])
        matcher.best_guess.return_value = ("Pikachu", 3)
        with (
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ),
            patch("bot.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch("bot.logger.info") as log_info,
            patch("bot.logger.warning") as log_warning,
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=None,
                http=Mock(),
                model="test-model",
                matcher=matcher,
            )

        self.assertEqual(result, ("Pikachu", 25.0))
        matcher.best_guess.assert_called_once_with(b"spawn image")
        log_warning.assert_called_once_with(
            "Using low-confidence local guess %s (%d reference votes)",
            "Pikachu",
            3,
        )
        no_match_log = next(
            call for call in log_info.call_args_list
            if call.args[0].startswith("No reference match")
        )
        self.assertEqual(
            no_match_log.args[0],
            "No reference match [download %.2fs, match %.2fs]",
        )
        self.assertEqual(len(no_match_log.args), 3)
        rendered_log = no_match_log.args[0] % no_match_log.args[1:]
        self.assertRegex(
            rendered_log,
            r"\[download \d+\.\d{2}s, match \d+\.\d{2}s\]$",
        )

    async def test_no_client_and_no_local_candidate_raises_no_match(self) -> None:
        import bot

        with self.assertRaises(bot.NoMatchError):
            await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=None,
                http=Mock(),
                model="test-model",
            )

    async def test_vision_timeout_uses_low_confidence_local_guess(self) -> None:
        import bot

        matcher = Mock(entries=["Pikachu"])
        matcher.best_guess.return_value = ("Pikachu", 3)
        with (
            patch(
                "bot.request_prediction",
                new=AsyncMock(side_effect=asyncio.TimeoutError),
            ),
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ),
            patch("bot.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch("bot.logger.exception"),
        ):
            result = await bot.recognize_pokemon(
                "https://example.test/spawn.png",
                client=Mock(),
                http=Mock(),
                model="test-model",
                matcher=matcher,
            )

        self.assertEqual(result, ("Pikachu", 25.0))
        matcher.best_guess.assert_called_once_with(b"spawn image")


class ReserveReportPriceTests(unittest.TestCase):
    def test_spawn_rate_tier_boundaries(self) -> None:
        tiers = bot_module.RESERVE_REPORT_PRICES
        for index, (denominator, price) in enumerate(tiers):
            for chance, expected in (
                (denominator, price),
                (denominator - 1, tiers[index - 1][1] if index else 2500),
            ):
                with self.subTest(chance=chance):
                    with patch("bot.load_report_spawn_chances", return_value=[
                        ("Pikachu", chance)
                    ]):
                        self.assertEqual(bot_module.report_spawn_price("Pikachu"), expected)

    def test_category_precedence_and_exact_forms(self) -> None:
        categories = {"1": {
            "gmax": ["Pikachu"], "rare": ["Pikachu"],
            "regional": ["all Sneasel"], "paradox": ["Witch Meowscarada"],
        }}
        self.assertEqual(bot_module.report_category_price(categories, 1, "Pikachu"), 45000)
        self.assertEqual(bot_module.report_category_price(categories, 1, "Hisuian Sneasel"), 45000)
        self.assertEqual(bot_module.report_category_price(categories, 1, "Witch Meowscarada"), 45000)
        self.assertIsNone(bot_module.report_category_price(categories, 1, "Meowscarada"))
        self.assertEqual(bot_module.report_category_price(categories, 1, "Eevee", gigantamax=True), 35000)

    def test_spawn_form_uses_exact_candidate(self) -> None:
        self.assertEqual(
            bot_module.report_spawn_form("<:grass:123> Oracle Meowscarada: 99.00%", "Meowscarada"),
            "Oracle Meowscarada",
        )
        self.assertEqual(bot_module.report_spawn_form("Meowscarada: 90.00%", "Meowscarada"), "Meowscarada")
        self.assertIsNone(bot_module.report_spawn_form("Pikachu: 99.00%", "Meowscarada"))
        self.assertIsNone(bot_module.report_spawn_form("Other Meowscarada: 90.00%", "Meowscarada"))
        self.assertEqual(
            bot_module.report_spawn_form("Celebi <:psychic:123> <:grass:456>: 99.63%", "Celebi"),
            "Celebi",
        )

    def test_only_reserve_line_mentions_count(self) -> None:
        self.assertEqual(
            bot_module.report_reserve_pings(
                "Celebi: 99.63%\nShinyhunt: <@999>\n"
                "**Reserve pings:** <@111>, <@!222>\nOther: <@333>"
            ),
            {111, 222},
        )

    def test_public_chances_include_species_and_forms(self) -> None:
        self.assertEqual(bot_module.report_spawn_price("Celebi"), 40000)
        self.assertEqual(bot_module.report_spawn_price("Bagon"), 5000)
        self.assertEqual(bot_module.report_spawn_price("Winter Deerling"), 15000)
        self.assertEqual(
            bot_module.report_spawn_price("Caramel Swirl Strawberry Sweet Alcremie"),
            50000,
        )
        with patch("bot.load_report_spawn_chances", return_value=[
            ("Pikachu", 337), ("Other", 336)
        ]):
            self.assertEqual(bot_module.report_spawn_price("Pikachu"), 5000)
            self.assertIsNone(bot_module.report_spawn_price("Unlisted"))


class ReserveReportCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())
        self.bot.reservations = {}
        self.bot.reserve_categories = {}
        self.catch = Mock(spec=discord.Message)
        self.catch.id = 42
        self.catch.author.id = 12345
        self.catch.content = "Congratulations <@222>! You caught a Level 5 Celebi! (56.45%)!"
        self.catch.embeds = []
        self.catch.created_at = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.catch.jump_url = "https://discord.com/channels/1/2/42"
        self.message = Mock(spec=discord.Message)
        self.message.guild.id = 1
        self.message.channel.id = 2
        self.message.author.id = 111
        self.message.reference.channel_id = 2
        self.message.reference.message_id = 42
        self.message.reference.resolved = self.catch
        self.message.reply = AsyncMock()
        self.destination = Mock(spec=discord.TextChannel)
        self.destination.guild.id = 1
        self.destination.send = AsyncMock()
        self.bot.get_channel = Mock(return_value=self.destination)

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_reserved_catch_sends_report_to_channel(self) -> None:
        self.bot.reservations = {reservation_key(1, "Celebi"): [111]}
        await self.bot.handle_reserve_report(self.message)
        content = self.destination.send.await_args.args[0]
        self.assertIn("<@222> hey you stole", content)
        self.assertIn("Pokémon: Celebi\nPC: 40,000 PC", content)
        self.assertIn("<@222> trade <@111> in <#1538294047095922748>", content)
        self.assertIn(self.catch.jump_url, content)
        self.message.reply.assert_awaited_once_with("Report sent.", mention_author=False)

    async def test_rejects_non_reserver_fake_catch_and_own_catch(self) -> None:
        self.bot.report_spawn_evidence = AsyncMock(return_value=[])
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("don't have", self.message.reply.await_args.args[0])
        self.bot.reservations = {reservation_key(1, "Celebi"): [111]}
        self.catch.author.id = 999
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("Pokétwo catch", self.message.reply.await_args.args[0])
        self.catch.author.id = 12345
        self.message.author.id = 222
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("own catch", self.message.reply.await_args.args[0])
        self.destination.send.assert_not_awaited()

    async def test_event_requires_matching_spawn_form(self) -> None:
        self.catch.content = "Congratulations <@222>! You caught a Level 5 Meowscarada!"
        self.bot.reservations = {reservation_key(1, "Oracle Meowscarada"): [111]}
        self.bot.report_spawn_evidence = AsyncMock(return_value=[("Witch Meowscarada", set())])
        await self.bot.handle_reserve_report(self.message)
        self.destination.send.assert_not_awaited()
        self.bot.report_spawn_evidence.return_value = []
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("couldn't identify", self.message.reply.await_args.args[0])
        self.bot.report_spawn_evidence.return_value = [("Oracle Meowscarada", set())]
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("Oracle Meowscarada\nPC: 45,000 PC", self.destination.send.await_args.args[0])

    async def test_identified_form_uses_its_spawn_rate(self) -> None:
        self.catch.content = "Congratulations <@222>! You caught a Level 5 Alcremie!"
        self.bot.report_spawn_evidence = AsyncMock(
            return_value=[("Caramel Swirl Strawberry Sweet Alcremie", {111})]
        )
        await self.bot.handle_reserve_report(self.message)
        content = self.destination.send.await_args.args[0]
        self.assertIn(
            "Pokémon: Caramel Swirl Strawberry Sweet Alcremie\nPC: 50,000 PC",
            content,
        )

    async def test_unavailable_price_does_not_send_report(self) -> None:
        self.bot.reservations = {reservation_key(1, "Celebi"): [111]}
        with patch("bot.report_spawn_price", return_value=None):
            await self.bot.handle_reserve_report(self.message)
        self.destination.send.assert_not_awaited()
        self.assertIn("No spawn-rate price", self.message.reply.await_args.args[0])

    async def test_missing_reference_is_rejected(self) -> None:
        self.message.reference = None
        await self.bot.handle_reserve_report(self.message)
        self.destination.send.assert_not_awaited()
        self.assertIn("Reply to", self.message.reply.await_args.args[0])

    async def test_on_message_routes_report_for_members(self) -> None:
        self.message.content = "v!report"
        self.message.embeds = []
        self.message.author.bot = False
        self.bot.org_rpc = None
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.track_incense_command = Mock(return_value=None)
        self.bot.track_chat_event_message = Mock()
        self.bot.handle_reserve_report = AsyncMock()
        await self.bot.on_message(self.message)
        self.bot.handle_reserve_report.assert_awaited_once_with(self.message)

    async def test_find_spawn_reply_even_after_catch(self) -> None:
        spawn = Mock(spec=discord.Message)
        spawn.id = 40
        spawn.author.id = 12345
        spawn.content = ""
        spawn.embeds = [discord.Embed(title="A wild Pokémon has appeared!")]
        reply = Mock(spec=discord.Message)
        reply.author.id = 9999
        reply.author.bot = True
        reply.webhook_id = None
        reply.reference.message_id = 40
        reply.content = "Oracle Meowscarada: 99.00%"
        reply.embeds = []
        self.bot._connection.user = Mock(id=9999)

        async def history(**kwargs: Any):
            for item in [reply] if "after" in kwargs else [spawn]:
                yield item

        self.message.channel.history = history
        evidence = await self.bot.report_spawn_evidence(self.message, self.catch, "Meowscarada")
        self.assertEqual(evidence, [("Oracle Meowscarada", set())])

    async def test_other_naming_bot_reserve_ping_authorizes_report(self) -> None:
        spawn = Mock(spec=discord.Message)
        spawn.id = 40
        spawn.author.id = 12345
        spawn.content = ""
        spawn.embeds = [discord.Embed(title="A wild Pokémon has appeared!")]
        reply = Mock(spec=discord.Message)
        reply.author.id = 1307910235737948252
        reply.author.bot = True
        reply.webhook_id = None
        reply.reference.message_id = 40
        reply.content = (
            "Celebi <:psychic:123> <:grass:456>: 99.63%\n"
            "Best name: serebi\nReserve pings: <@111>\n"
            "Click to Copy -> `@Pokétwo c serebi`"
        )
        reply.embeds = []

        async def history(**kwargs: Any):
            for item in [reply] if "after" in kwargs else [spawn]:
                yield item

        self.message.channel.history = history
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("Pokémon: Celebi\nPC: 40,000 PC", self.destination.send.await_args.args[0])
        self.destination.send.reset_mock()
        for field, value in (
            ("reference", 41),
            ("name", "Pikachu: 99.63%\nReserve pings: <@111>"),
            ("webhook", 123),
            ("human", False),
        ):
            with self.subTest(field=field):
                reply.reference.message_id = 41 if field == "reference" else 40
                reply.content = value if field == "name" else (
                    "Celebi <:psychic:123> <:grass:456>: 99.63%\n"
                    "Best name: serebi\nReserve pings: <@111>"
                )
                reply.webhook_id = value if field == "webhook" else None
                reply.author.bot = value if field == "human" else True
                await self.bot.handle_reserve_report(self.message)
                self.destination.send.assert_not_awaited()

    async def test_other_bot_requires_matching_spawn_and_reserve_ping(self) -> None:
        self.bot.report_spawn_evidence = AsyncMock(return_value=[("Celebi", {333})])
        await self.bot.handle_reserve_report(self.message)
        self.destination.send.assert_not_awaited()
        self.assertIn("don't have", self.message.reply.await_args.args[0])

    async def test_other_bot_event_form_is_used_for_price(self) -> None:
        self.catch.content = "Congratulations <@222>! You caught a Level 5 Meowscarada!"
        self.bot.report_spawn_evidence = AsyncMock(
            return_value=[("Oracle Meowscarada", {111})]
        )
        await self.bot.handle_reserve_report(self.message)
        self.assertIn("Oracle Meowscarada\nPC: 45,000 PC", self.destination.send.await_args.args[0])

    async def test_conflicting_form_identifications_are_rejected(self) -> None:
        self.catch.content = "Congratulations <@222>! You caught a Level 5 Meowscarada!"
        self.bot.report_spawn_evidence = AsyncMock(
            return_value=[("Oracle Meowscarada", {111}), ("Witch Meowscarada", {111})]
        )
        await self.bot.handle_reserve_report(self.message)
        self.destination.send.assert_not_awaited()
        self.assertIn("conflicting", self.message.reply.await_args.args[0])


class PremiumAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.bot = NamingBot(ConfigTests().load_config())
        self.bot.premium_servers_path = Path(self.directory.name) / "premium.json"
        self.bot.premium_servers = {}

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self.directory.cleanup()

    async def test_premium_tiers_persist_and_owner_can_assign_one(self) -> None:
        import bot

        self.bot.is_application_owner = AsyncMock(return_value=True)
        message = Mock()
        message.content = "v!premium add silver 987654321"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.bot = False
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        self.assertEqual(self.bot.premium_servers, {"987654321": "silver"})
        self.assertEqual(
            bot.load_premium_servers(self.bot.premium_servers_path),
            {"987654321": "silver"},
        )
        self.assertIn("Silver", message.reply.await_args.args[0])
        self.assertEqual(
            self.bot.premium_limit_for_guild(987654321),
            200,
        )

    async def test_non_owner_cannot_grant_a_premium_tier(self) -> None:
        self.bot.is_application_owner = AsyncMock(return_value=False)
        message = Mock()
        message.content = "v!premium add gold 987654321"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.reply = AsyncMock()

        await self.bot.handle_premium_command(message)

        self.assertEqual(self.bot.premium_servers, {})
        self.assertIn("Only the bot owner", message.reply.await_args.args[0])

    async def test_premium_cannot_be_granted_outside_the_main_server(self) -> None:
        self.bot.is_application_owner = AsyncMock(return_value=True)
        message = Mock()
        message.content = "v!premium add gold 987654321"
        message.guild.id = SERVER_ID + 1
        message.author.id = 123
        message.reply = AsyncMock()

        await self.bot.handle_premium_command(message)

        self.assertEqual(self.bot.premium_servers, {})
        self.assertIn("main server", message.reply.await_args.args[0])

    async def test_application_team_owner_is_authorized_and_owner_lookup_is_cached(
        self,
    ) -> None:
        self.bot.application_info = AsyncMock(
            return_value=SimpleNamespace(
                owner=None,
                team=SimpleNamespace(owner_id=456),
            )
        )

        self.assertTrue(await self.bot.is_application_owner(456))
        self.assertFalse(await self.bot.is_application_owner(789))
        self.bot.application_info.assert_awaited_once()

    def test_premium_tiers_have_the_requested_server_limits(self) -> None:
        self.bot.premium_servers = {
            "100": "bronze",
            "200": "silver",
            "300": "gold",
        }

        self.assertEqual(
            [
                self.bot.premium_limit_for_guild(guild_id)
                for guild_id in (100, 200, 300)
            ],
            [100, 200, 300],
        )

    async def test_premium_status_shows_all_tiers_or_only_the_active_one(
        self,
    ) -> None:
        message = Mock()
        message.content = "v!premium"
        message.guild.id = 987654321
        message.reply = AsyncMock()

        await self.bot.handle_premium_command(message)

        embeds = awaited_kwargs(message.reply)["embeds"]
        self.assertEqual(
            [embed.title for embed in embeds],
            ["Bronze Premium", "Silver Premium", "Gold Premium"],
        )
        self.assertEqual(
            [embed.thumbnail.url for embed in embeds],
            [
                "attachment://butterfly-bronze.png",
                "attachment://butterfly-silver.png",
                "attachment://butterfly-gold.png",
            ],
        )
        self.assertIn("100 simultaneous", embeds[0].description)
        self.assertIn("200 simultaneous", embeds[1].description)
        self.assertIn("300 simultaneous", embeds[2].description)
        self.assertTrue(
            all("Not active" in embed_description(embed) for embed in embeds)
        )

        self.bot.premium_servers[str(message.guild.id)] = "silver"
        await self.bot.handle_premium_command(message)
        embeds = awaited_kwargs(message.reply)["embeds"]
        self.assertEqual([embed.title for embed in embeds], ["Silver Premium"])
        self.assertIn("Active for this server", embeds[0].description)
        self.assertEqual(
            [file.filename for file in awaited_kwargs(message.reply)["files"]],
            ["butterfly-silver.png"],
        )

    async def test_spawn_naming_requires_premium_but_other_commands_remain_available(
        self,
    ) -> None:
        message = Mock()
        message.id = 5678
        message.guild.id = 987654321
        message.reply = AsyncMock()

        with patch("bot.image_url") as image_url:
            await self.bot.handle_spawn(message)

        image_url.assert_not_called()
        message.reply.assert_not_awaited()

        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.handle_ping_command = AsyncMock()
        command = Mock()
        command.author.bot = False
        command.author.id = 123
        command.content = "v!ping"
        command.guild.id = 987654321
        command.channel.id = 111
        command.channel.guild.id = command.guild.id
        command.embeds = []
        command.attachments = []
        command.reply = AsyncMock()

        await self.bot.on_message(command)

        self.bot.handle_ping_command.assert_awaited_once_with(command)

    async def test_global_concurrency_ceiling_is_shared_across_servers(self) -> None:
        self.bot.config = replace(
            self.bot.config,
            max_concurrent_vision_requests=2,
        )
        self.bot.premium_servers = {
            "100": "gold",
            "200": "gold",
        }

        await self.bot.acquire_vision_capacity(100)
        await self.bot.acquire_vision_capacity(100)
        waiting = asyncio.create_task(self.bot.acquire_vision_capacity(200))
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())

        await self.bot.release_vision_capacity(100)
        await asyncio.wait_for(waiting, timeout=1)
        self.assertEqual(self.bot.active_vision_requests, 2)

        await self.bot.release_vision_capacity(100)
        await self.bot.release_vision_capacity(200)
        self.assertEqual(self.bot.active_vision_requests, 0)


class ImageCorrectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.corrections = Path(self.directory.name) / "corrections.csv"
        self.env = patch.dict(
            "os.environ",
            {
                "POKEMON_CORRECTIONS_FILE": str(self.corrections),
                "IMAGE_BANK_FILE": str(Path(self.directory.name) / "missing.npz"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = ConfigTests().load_config()
        self.bot = NamingBot(self.config)
        self.bot.application_owner_ids = {123}
        self.bot._connection.user = Mock(id=555)
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.low_accuracy_channels = {}
        self.source = Mock()
        self.source.guild.id = 1
        self.source.author.id = self.config.poketwo_bot_id
        self.source.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        self.source.embeds = []
        self.source_channel = Mock(spec=discord.TextChannel)
        self.source_channel.fetch_message = AsyncMock(return_value=self.source)
        self.bot.get_channel = Mock(return_value=self.source_channel)
        self.alert = Mock()
        self.alert.author.id = 555
        self.alert.content = (
            f"<@{bot_module.RECOGNITION_ALERT_USER_ID}> ⚠️ Low accuracy: "
            "**Pikachu** at 25.00% (below 50%)\n"
            "https://discord.com/channels/1/2/3"
        )
        self.message = Mock()
        self.message.author.id = 123
        self.message.author.bot = False
        self.message.content = "v!correct Zygarde Core"
        self.message.guild.id = SERVER_ID
        self.message.channel.id = bot_module.RECOGNITION_ALERT_CHANNEL_ID
        self.message.channel.fetch_message = AsyncMock(return_value=self.alert)
        self.message.reference.message_id = 4
        self.message.reply = AsyncMock()

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_reply_teaches_exact_image_and_survives_restart(self) -> None:
        import hashlib

        image = b"original spawn image"
        digest = hashlib.sha256(image).hexdigest()
        self.bot.image_matcher.exact_references[digest] = "Pikachu"
        with patch("bot.download_image", new=AsyncMock(return_value=(image, "image/png"))):
            await self.bot.on_message(self.message)
            self.assertEqual(
                await bot_module.recognize_pokemon(
                    "https://example.test/spawn.png",
                    client=None,
                    http=Mock(),
                    model="test",
                    matcher=self.bot.image_matcher,
                ),
                ("Zygarde Core", 100.0),
            )
        self.assertIn("Saved **Zygarde Core**", self.message.reply.await_args.args[0])
        self.assertIsNone(self.bot.image_matcher.match(b"another image"))
        with self.corrections.open(encoding="utf-8", newline="") as file:
            import csv

            rows = list(csv.DictReader(file))
        self.assertEqual(rows, [{
            "image_sha256": digest,
            "correct_name": "Zygarde Core",
            "source_message_id": "3",
            "previous_guess": "Pikachu",
            "previous_confidence": "25.00",
            "corrected_by": "123",
            "alert_message_id": "4",
        }])
        restarted = NamingBot(self.config)
        try:
            self.assertEqual(restarted.image_matcher.match(image), ("Zygarde Core", 0))
        finally:
            await restarted.close()

    async def test_non_owner_and_untrusted_alert_cannot_change_references(self) -> None:
        self.message.author.id = 456
        await self.bot.on_message(self.message)
        self.assertIn("Only the bot owner", self.message.reply.await_args.args[0])
        self.assertFalse(self.corrections.exists())
        self.message.author.id = 123
        self.alert.author.id = 999
        await self.bot.on_message(self.message)
        self.assertIn("alert sent by this bot", self.message.reply.await_args.args[0])
        self.assertFalse(self.corrections.exists())

    async def test_write_failure_does_not_teach_image(self) -> None:
        with (
            patch("bot.download_image", new=AsyncMock(return_value=(b"image", "image/png"))),
            patch("bot.append_image_correction", side_effect=OSError("disk full")),
        ):
            await self.bot.on_message(self.message)
        self.assertIn("couldn't save", self.message.reply.await_args.args[0])
        self.assertIsNone(self.bot.image_matcher.match(b"image"))

    async def test_failure_alert_can_be_corrected(self) -> None:
        self.alert.content = (
            f"<@{bot_module.RECOGNITION_ALERT_USER_ID}> Vivillon couldn't confidently identify "
            "the spawn in <#2>.\nJump to the spawn: https://discord.com/channels/1/2/3"
        )
        with patch("bot.download_image", new=AsyncMock(return_value=(b"image", "image/png"))):
            await self.bot.on_message(self.message)
        self.assertEqual(self.bot.image_matcher.match(b"image"), ("Zygarde Core", 0))

    async def test_form_names_and_latest_correction_are_preserved(self) -> None:
        self.message.content = "v!correct D Unown"
        with patch("bot.download_image", new=AsyncMock(return_value=(b"image", "image/png"))):
            await self.bot.on_message(self.message)
            self.assertEqual(self.bot.image_matcher.match(b"image"), ("Unown Variant 4", 0))
            self.message.content = "v!correct Busted Mimikyu"
            await self.bot.on_message(self.message)
        self.assertEqual(self.bot.image_matcher.match(b"image"), ("Busted Mimikyu", 0))
        restarted = NamingBot(self.config)
        try:
            self.assertEqual(restarted.image_matcher.match(b"image"), ("Busted Mimikyu", 0))
        finally:
            await restarted.close()

    async def test_invalid_name_or_unavailable_spawn_is_not_saved(self) -> None:
        self.message.content = "v!correct not a pokemon"
        await self.bot.on_message(self.message)
        self.assertIn("don't recognize", self.message.reply.await_args.args[0])
        self.message.content = "v!correct Pikachu"
        self.source.author.id = 42
        await self.bot.on_message(self.message)
        self.assertIn("couldn't save", self.message.reply.await_args.args[0])
        self.assertFalse(self.corrections.exists())


class ApiStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ConfigTests().load_config()
        self.bot = NamingBot(self.config)
        self.bot.premium_servers = {str(SERVER_ID): "gold"}

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_slow_recognition_warning_uses_one_second_threshold(self) -> None:
        import bot

        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        message = Mock()
        message.id = 9001
        message.guild.id = SERVER_ID
        message.channel.id = 9002
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with (
            patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Pikachu", 99.0)),
            ),
            patch(
                "bot.time",
                SimpleNamespace(monotonic=Mock(side_effect=[100.0, 100.1, 100.2, 101.0])),
            ),
            patch("bot.logger.warning") as log_warning,
        ):
            await self.bot.handle_spawn(message)

        self.assertEqual(bot.RECOGNITION_WINDOW_SECONDS, 1.0)
        log_warning.assert_called_once_with(
            "SLOW recognition for spawn %s took %.2fs",
            9001,
            1.0,
        )

    async def test_low_confidence_guess_is_posted_and_reported(
        self,
    ) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        self.bot.low_accuracy_channels = {}
        confidence_dir = tempfile.TemporaryDirectory()
        self.addCleanup(confidence_dir.cleanup)
        self.bot.pokemon_confidence_path = (
            Path(confidence_dir.name) / "pokemon_confidence.csv"
        )
        self.bot.pokemon_confidence_review_dir = (
            Path(confidence_dir.name) / "pokemon_confidence_review"
        )
        message = Mock()
        message.id = 9003
        message.guild.id = SERVER_ID
        message.channel.id = 9004
        message.jump_url = "https://discord.com/channels/1/9004/9003"
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()
        alert_channel = Mock(spec=discord.TextChannel)
        alert_channel.send = AsyncMock()

        with (
            patch.object(
                self.bot,
                "get_channel",
                return_value=alert_channel,
            ) as get_channel,
            patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Pikachu", 49.99)),
            ),
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ),
        ):
            await self.bot.handle_spawn(message)

        self.assertEqual(
            self.bot.pokemon_confidence_path.read_text(encoding="utf-8").splitlines(),
            ["pokemon_name,confidence_percent", "Pikachu,49.99"],
        )
        bot_module.append_pokemon_confidence(
            self.bot.pokemon_confidence_path,
            "Oddish",
            12.5,
        )
        self.assertEqual(
            self.bot.pokemon_confidence_path.read_text(encoding="utf-8").splitlines(),
            [
                "pokemon_name,confidence_percent",
                "Pikachu,49.99",
                "Oddish,12.50",
            ],
        )
        saved_images = list(self.bot.pokemon_confidence_review_dir.glob("*.png"))
        self.assertEqual(len(saved_images), 1)
        self.assertTrue(saved_images[0].name.endswith("_pikachu.png"))
        self.assertEqual(saved_images[0].read_bytes(), b"spawn image")
        message.reply.assert_awaited_once()
        self.assertIn("Pikachu: 49.99%", message.reply.await_args.args[0])
        self.assertNotIn("below 50%", message.reply.await_args.args[0])
        self.assertEqual(self.bot.pokemon_named_count, 1)
        self.assertEqual(self.bot.failed_recognition_count, 0)
        get_channel.assert_called_once_with(bot_module.RECOGNITION_ALERT_CHANNEL_ID)
        alert_channel.send.assert_awaited_once()
        alert = alert_channel.send.await_args.args[0]
        self.assertIn(f"<@{bot_module.RECOGNITION_ALERT_USER_ID}>", alert)
        self.assertIn("Pikachu", alert)
        self.assertIn("49.99%", alert)
        self.assertIn("below 50%", alert)
        self.assertIn(message.jump_url, alert)
        allowed_mentions = awaited_kwargs(alert_channel.send)["allowed_mentions"]
        self.assertEqual(
            [user.id for user in allowed_mentions.users],
            [bot_module.RECOGNITION_ALERT_USER_ID],
        )
        self.assertFalse(allowed_mentions.roles)
        self.assertFalse(allowed_mentions.everyone)

    @unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
    async def test_weak_zygarde_core_spawn_is_named_and_alerted(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.openai = None
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        message = Mock()
        message.id = 9010
        message.guild.id = SERVER_ID
        message.channel.id = 9011
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()
        image = (
            Path(__file__).with_name("test")
            / "fixtures"
            / "zygarde-core-spawn.png"
        ).read_bytes()

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "bot.download_image",
                new=AsyncMock(return_value=(image, "image/png")),
            ),
            patch.object(self.bot, "report_low_accuracy", new=AsyncMock()) as alert,
            patch.object(self.bot, "save_flagged_pokemon_spawn_image", new=AsyncMock()),
        ):
            self.bot.pokemon_confidence_path = Path(directory) / "confidence.csv"
            await self.bot.handle_spawn(message)

        message.reply.assert_awaited_once()
        alert.assert_awaited_once()
        alert_message, name, confidence = alert.await_args.args
        self.assertIs(alert_message, message)
        self.assertEqual(name, "Zygarde Core")
        self.assertGreater(confidence, 0)
        self.assertLess(confidence, 50)
        self.assertIn(
            f"Zygarde Core: {confidence:.2f}%", message.reply.await_args.args[0]
        )

    async def test_low_confidence_test_mode_posts_normal_preview(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        message = Mock()
        message.id = 9012
        message.guild.id = SERVER_ID
        message.channel.id = 9013
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with (
            patch("bot.recognize_pokemon", new=AsyncMock(return_value=("Pikachu", 25.0))),
            patch.object(self.bot, "report_low_accuracy", new=AsyncMock()) as alert,
            patch.object(self.bot, "post_test_starboard", new=AsyncMock()),
        ):
            await self.bot.handle_spawn(message, test_mode=True)

        message.reply.assert_awaited_once()
        self.assertIn("Pikachu: 25.00%", message.reply.await_args.args[0])
        alert.assert_awaited_once_with(message, "Pikachu", 25.0)
        self.assertEqual(self.bot.pokemon_named_count, 0)
        self.assertEqual(self.bot.failed_recognition_count, 0)

    async def test_guess_at_50_percent_uses_normal_spawn_reply(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        message = Mock()
        message.id = 9005
        message.guild.id = SERVER_ID
        message.channel.id = 9006
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            self.bot.pokemon_confidence_path = Path(temp_dir) / "pokemon_confidence.csv"
            self.bot.pokemon_confidence_review_dir = (
                Path(temp_dir) / "pokemon_confidence_review"
            )
            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Pikachu", 50.0)),
            ), patch(
                "bot.download_image",
                new=AsyncMock(return_value=(b"spawn image", "image/png")),
            ):
                await self.bot.handle_spawn(message)

            self.assertEqual(
                self.bot.pokemon_confidence_path.read_text(encoding="utf-8").splitlines(),
                ["pokemon_name,confidence_percent", "Pikachu,50.00"],
            )
            self.assertEqual(
                len(list(self.bot.pokemon_confidence_review_dir.glob("*.png"))),
                1,
            )
        message.reply.assert_awaited_once()
        self.assertIn("Pikachu: 50.00%", message.reply.await_args.args[0])
        self.assertNotIn("below 50%", message.reply.await_args.args[0])

    async def test_flagged_pokemon_spawn_is_saved_even_with_high_confidence(
        self,
    ) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            self.bot.pokemon_confidence_path = temp_path / "pokemon_confidence.csv"
            self.bot.pokemon_confidence_review_dir = temp_path / "pokemon_confidence_review"
            bot_module.append_pokemon_confidence(
                self.bot.pokemon_confidence_path,
                "Inteleon",
                33.33,
            )
            message = Mock()
            message.id = 9007
            message.guild.id = SERVER_ID
            message.channel.id = 9008
            message.attachments = [
                Mock(content_type="image/png", url="https://example.test/spawn.png")
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with (
                patch(
                    "bot.recognize_pokemon",
                    new=AsyncMock(return_value=("Inteleon", 95.0)),
                ),
                patch(
                    "bot.download_image",
                    new=AsyncMock(return_value=(b"inteleon spawn", "image/png")),
                ),
            ):
                await self.bot.handle_spawn(message)

            saved_images = list(self.bot.pokemon_confidence_review_dir.glob("*.png"))
            self.assertEqual(len(saved_images), 1)
            self.assertTrue(saved_images[0].name.endswith("_inteleon.png"))
            self.assertEqual(saved_images[0].read_bytes(), b"inteleon spawn")

    def test_recognizes_only_poketwo_incense_commands(self) -> None:
        self.assertEqual(
            poketwo_incense_action(
                f"<@{self.config.poketwo_bot_id}> inc buy -y",
                self.config.poketwo_bot_id,
            ),
            "buy",
        )
        self.assertEqual(
            poketwo_incense_action(
                f"<@{self.config.poketwo_bot_id}> buy incense",
                self.config.poketwo_bot_id,
            ),
            "start",
        )
        self.assertEqual(
            poketwo_incense_action(
                f"<@!{self.config.poketwo_bot_id}> stopincense",
                self.config.poketwo_bot_id,
            ),
            "stop",
        )
        self.assertEqual(
            poketwo_incense_action("p!buy incense", self.config.poketwo_bot_id),
            "start",
        )
        self.assertEqual(
            poketwo_incense_action("p!stopincense", self.config.poketwo_bot_id),
            "stop",
        )
        self.assertIsNone(
            poketwo_incense_action(
                "<@999> buy incense",
                self.config.poketwo_bot_id,
            )
        )
        self.assertIsNone(
            poketwo_incense_action(
                f"<@{self.config.poketwo_bot_id}> buy shard 50",
                self.config.poketwo_bot_id,
            )
        )

    async def test_incense_purchase_pauses_only_after_poketwo_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.incense_path = Path(directory) / "incenses.json"
            self.bot.is_allowed_channel = Mock(return_value=False)
            self.bot.set_poketwo_blocked = AsyncMock(return_value=True)
            message = Mock()
            message.author.bot = False
            message.author.id = 100
            message.guild.id = SERVER_ID
            message.guild.name = "Test server"
            message.channel.id = 200
            message.channel.name = "incense-room"
            message.content = f"<@{self.config.poketwo_bot_id}> inc buy -y"
            message.embeds = []
            message.reply = AsyncMock()

            await self.bot.on_message(message)

            self.bot.set_poketwo_blocked.assert_not_awaited()
            message.reply.assert_not_awaited()
            self.assertNotIn("200", self.bot.active_incenses)

            response = Mock()
            response.author.bot = True
            response.author.id = self.config.poketwo_bot_id
            response.guild = message.guild
            response.channel = message.channel
            response.content = "You do not have enough shards."
            response.embeds = []
            response.reply = AsyncMock()

            await self.bot.on_message(response)

            self.bot.set_poketwo_blocked.assert_not_awaited()
            response.reply.assert_not_awaited()

            response.content = "You purchased an Incense for 50 shards!"

            await self.bot.on_message(response)

            self.assertIn(200, self.bot.muted_poketwo_channels)
            self.bot.set_poketwo_blocked.assert_awaited_once_with(
                message.channel,
                True,
            )
            response.reply.assert_awaited_once_with(
                "Incense has been paused.",
                mention_author=False,
            )
            self.assertIn("200", self.bot.active_incenses)

    async def test_auto_pause_incense_commands_persist_per_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.auto_pause_incense_settings_path = (
                Path(directory) / "auto_pause_incense_settings.json"
            )
            self.bot.auto_pause_incense_settings = {}
            self.bot.is_allowed_channel = Mock(return_value=True)
            self.bot.track_chat_event_message = Mock()

            def command_message(content: str) -> Mock:
                message = Mock()
                message.author = Mock(spec=discord.Member)
                message.author.id = 100
                message.author.bot = False
                message.author.roles = []
                message.guild.id = SERVER_ID
                message.channel.id = 200
                message.channel.guild.id = SERVER_ID
                message.content = content
                message.embeds = []
                message.attachments = []
                message.reply = AsyncMock()
                return message

            off_command = command_message("v!poff")
            await self.bot.on_message(off_command)
            self.assertFalse(
                self.bot.auto_pause_incense_enabled_for_guild(SERVER_ID)
            )
            off_command.reply.assert_awaited_once_with(
                "Automatic incense pausing is now off for this server.",
                mention_author=False,
            )

            on_command = command_message("v!pon")
            await self.bot.on_message(on_command)
            self.assertTrue(
                self.bot.auto_pause_incense_enabled_for_guild(SERVER_ID)
            )
            self.assertTrue(
                self.bot.auto_pause_incense_enabled_for_guild(SERVER_ID + 1)
            )
            on_command.reply.assert_awaited_once_with(
                "Automatic incense pausing is now on for this server.",
                mention_author=False,
            )
            self.assertEqual(
                load_auto_pause_incense_settings(
                    self.bot.auto_pause_incense_settings_path
                ),
                {str(SERVER_ID): True},
            )

    async def test_auto_pause_disabled_skips_confirmed_purchase_pause(self) -> None:
        self.bot.auto_pause_incense_settings = {str(SERVER_ID): False}
        self.bot.set_poketwo_blocked = AsyncMock(return_value=True)
        message = Mock()
        message.author.id = self.config.poketwo_bot_id
        message.guild.id = SERVER_ID
        message.channel.id = 200
        message.reply = AsyncMock()

        await self.bot.pause_confirmed_incense_purchase(message)

        self.bot.set_poketwo_blocked.assert_not_awaited()
        message.reply.assert_not_awaited()

    async def test_pause_aliases_and_resume_command(self) -> None:
        self.bot.command_permissions = {}
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.track_chat_event_message = Mock()
        self.bot.set_poketwo_blocked = AsyncMock(return_value=True)

        def command_message(content: str, channel_id: int) -> Mock:
            message = Mock()
            message.author = Mock(spec=discord.Member)
            message.author.id = 100
            message.author.bot = False
            message.author.roles = []
            message.guild.id = SERVER_ID
            message.channel.id = channel_id
            message.channel.guild.id = SERVER_ID
            message.content = content
            message.embeds = []
            message.attachments = []
            message.reply = AsyncMock()
            return message

        for channel_id, pause_command in ((210, "v!p"), (211, "v!pause")):
            with self.subTest(pause_command=pause_command):
                pause = command_message(pause_command, channel_id)
                await self.bot.on_message(pause)

                self.assertIn(channel_id, self.bot.muted_poketwo_channels)
                pause.reply.assert_awaited_once_with(
                    "Incense paused.",
                    mention_author=False,
                )

                resume = command_message("v!r", channel_id)
                await self.bot.on_message(resume)

                self.assertNotIn(channel_id, self.bot.muted_poketwo_channels)
                resume.reply.assert_awaited_once_with(
                    "Incense resumed.",
                    mention_author=False,
                )

    async def test_reserve_search_is_public_and_does_not_resume_channel(self) -> None:
        channel_id = 212
        self.bot.command_permissions = {str(SERVER_ID): 900}
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.track_chat_event_message = Mock()
        self.bot.set_poketwo_blocked = AsyncMock(return_value=True)
        self.bot.muted_poketwo_channels.add(channel_id)
        self.bot.handle_reserve_command = AsyncMock()

        message = Mock()
        message.author = Mock(spec=discord.Member)
        message.author.id = 100
        message.author.bot = False
        message.author.roles = []
        message.guild.id = SERVER_ID
        message.channel.id = channel_id
        message.channel.guild.id = SERVER_ID
        message.content = "v!r search pikachu"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_reserve_command.assert_awaited_once_with(message)
        self.bot.set_poketwo_blocked.assert_not_awaited()
        self.assertIn(channel_id, self.bot.muted_poketwo_channels)
        message.reply.assert_not_awaited()

    async def test_pause_all_pauses_active_incense_channels_in_current_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time())
            self.bot.incense_path = Path(directory) / "incenses.json"
            self.bot.active_incenses = cast(dict[str, ActiveIncense], {
                "210": {
                    "guild": "Current server",
                    "channel": "incense-room",
                    "guild_id": SERVER_ID,
                    "expires_at": now + 3600,
                },
                "211": {
                    "guild": "Other server",
                    "channel": "other-room",
                    "guild_id": SERVER_ID + 1,
                    "expires_at": now + 3600,
                },
                "212": {
                    "guild": "Current server",
                    "channel": "expired-room",
                    "guild_id": SERVER_ID,
                    "expires_at": now - 1,
                },
            })
            guild = Mock()
            guild.id = SERVER_ID
            guild.name = "Current server"
            guild.text_channels = []
            channel = Mock()
            channel.id = 210
            channel.guild.id = SERVER_ID
            guild.get_channel = Mock(side_effect={210: channel}.get)
            guild.get_thread = Mock(return_value=None)
            self.bot.command_permissions = {}
            self.bot.is_allowed_channel = Mock(return_value=True)
            self.bot.track_chat_event_message = Mock()
            self.bot.set_poketwo_blocked = AsyncMock(return_value=True)
            message = Mock()
            message.author = Mock(spec=discord.Member)
            message.author.id = 100
            message.author.bot = False
            message.author.roles = []
            message.guild = guild
            message.channel.id = 213
            message.channel.guild.id = SERVER_ID
            message.content = "v!p all"
            message.embeds = []
            message.attachments = []
            message.reply = AsyncMock()

            await self.bot.on_message(message)

            self.bot.set_poketwo_blocked.assert_awaited_once_with(channel, True)
            self.assertEqual(self.bot.muted_poketwo_channels, {210})
            self.assertNotIn("212", self.bot.active_incenses)
            self.assertIn("211", self.bot.active_incenses)
            message.reply.assert_awaited_once_with(
                "Incense paused in 1 channel(s).",
                mention_author=False,
            )

    async def test_pause_all_recovers_untracked_active_incense_from_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time())
            self.bot.incense_path = Path(directory) / "incenses.json"
            self.bot.active_incenses = cast(dict[str, ActiveIncense], {
                "210": {
                    "guild": "Current server",
                    "channel": "tracked-room",
                    "guild_id": SERVER_ID,
                    "expires_at": now + 3600,
                },
            })
            guild = Mock()
            guild.id = SERVER_ID
            guild.name = "Current server"
            tracked_channel = Mock()
            tracked_channel.id = 210
            tracked_channel.guild = guild
            recovered_channel = Mock()
            recovered_channel.id = 214
            recovered_channel.name = "missed-room"
            recovered_channel.guild = guild

            async def history():
                yield SimpleNamespace(
                    author=SimpleNamespace(id=self.config.poketwo_bot_id),
                    content="",
                    embeds=[
                        SimpleNamespace(
                            title="",
                            description="Incense: Active",
                            author=SimpleNamespace(name=""),
                            footer=SimpleNamespace(text=""),
                            fields=[],
                        )
                    ],
                    created_at=SimpleNamespace(
                        timestamp=lambda: now - 30,
                    ),
                )

            recovered_channel.history = Mock(
                return_value=history(),
            )
            guild.text_channels = [tracked_channel, recovered_channel]
            channels = {210: tracked_channel, 214: recovered_channel}
            guild.get_channel = Mock(side_effect=channels.get)
            guild.get_thread = Mock(return_value=None)
            self.bot.command_permissions = {}
            self.bot.is_allowed_channel = Mock(return_value=True)
            self.bot.track_chat_event_message = Mock()
            self.bot.set_poketwo_blocked = AsyncMock(return_value=True)
            message = Mock()
            message.author = Mock(spec=discord.Member)
            message.author.id = 100
            message.author.bot = False
            message.author.roles = []
            message.guild = guild
            message.channel.id = 213
            message.channel.guild.id = SERVER_ID
            message.content = "v!p all"
            message.embeds = []
            message.attachments = []
            message.reply = AsyncMock()

            await self.bot.on_message(message)

            self.assertEqual(
                self.bot.set_poketwo_blocked.await_args_list,
                [call(tracked_channel, True), call(recovered_channel, True)],
            )
            recovered_channel.history.assert_called_once_with(limit=100)
            self.assertIn("214", self.bot.active_incenses)
            self.assertEqual(
                self.bot.active_incenses["214"]["expires_at"],
                now - 30 + bot_module.INCENSE_DURATION_SECONDS,
            )
            message.reply.assert_awaited_once_with(
                "Incense paused in 2 channel(s).",
                mention_author=False,
            )

    async def test_tracks_incense_commands_across_guilds_and_persists_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.incense_path = Path(directory) / "incenses.json"
            message = Mock()
            message.author.bot = False
            message.author.id = 100
            message.guild.id = SERVER_ID + 1
            message.guild.name = "Other server"
            message.channel.id = 200
            message.channel.name = "incense-room"
            message.content = f"<@{self.config.poketwo_bot_id}> buy incense"
            message.embeds = []

            await self.bot.on_message(message)

            self.assertIn("200", self.bot.active_incenses)
            active = self.bot.current_active_incenses()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["guild"], "Other server")
            self.assertEqual(active[0]["channel"], "incense-room")
            self.assertTrue(self.bot.incense_path.is_file())

            second_server_message = Mock()
            second_server_message.author.bot = False
            second_server_message.author.id = 101
            second_server_message.guild.id = SERVER_ID + 2
            second_server_message.guild.name = "Another server"
            second_server_message.channel.id = 201
            second_server_message.channel.name = "another-incense-room"
            second_server_message.content = "p!buy incense"
            second_server_message.embeds = []
            await self.bot.on_message(second_server_message)
            self.assertEqual(len(self.bot.current_active_incenses()), 2)

            message.content = f"<@{self.config.poketwo_bot_id}> stopincense"
            await self.bot.on_message(message)
            active = self.bot.current_active_incenses()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["guild"], "Another server")

    async def test_api_status_counts_incenses_across_all_servers(self) -> None:
        now = int(time.time())
        self.bot.active_incenses = cast(dict[str, ActiveIncense], {
            "200": {
                "guild": "First server",
                "channel": "incense-room",
                "guild_id": SERVER_ID,
                "expires_at": now + 3600,
            },
            "201": {
                "guild": "Second server",
                "channel": "incense-room",
                "guild_id": SERVER_ID + 1,
                "expires_at": now + 3600,
            },
        })
        message = Mock()
        message.reply = AsyncMock()

        await self.bot.handle_api_status(message)

        embed = awaited_kwargs(message.reply)["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Active Incense"], "2")

    async def test_api_status_tracks_poketwo_incense_spawn_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.incense_path = Path(directory) / "incenses.json"
            message = Mock()
            message.author.bot = True
            message.author.id = self.config.poketwo_bot_id
            message.guild.id = SERVER_ID + 100
            message.guild.name = "Other server"
            message.channel.id = 500
            message.channel.name = "incense-room"
            message.channel.guild = message.guild
            message.content = ""
            message.embeds = [
                discord.Embed(
                    description="Spawns Remaining: 42"
                )
            ]
            message.embeds[0].set_footer(text="Incense: Active")

            await self.bot.on_message(message)

            status_message = Mock()
            status_message.reply = AsyncMock()
            await self.bot.handle_api_status(status_message)
            embed = awaited_kwargs(status_message.reply)["embed"]
            fields = {field.name: field.value for field in embed.fields}
            self.assertEqual(fields["Active Incense"], "1")

            inactive_embed = discord.Embed(description="Spawns Remaining: 0")
            inactive_embed.set_footer(text="Incense: Inactive")
            message.embeds = [inactive_embed]
            await self.bot.on_message_edit(Mock(), message)
            status_message.reply.reset_mock()
            await self.bot.handle_api_status(status_message)
            embed = awaited_kwargs(status_message.reply)["embed"]
            fields = {field.name: field.value for field in embed.fields}
            self.assertEqual(fields["Active Incense"], "0")

    async def test_naming_settings_toggle_persists_per_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.server_settings_path = Path(directory) / "settings.json"
            self.bot.server_settings = {}

            self.assertEqual(
                self.bot.naming_settings_for_guild(SERVER_ID),
                {"enabled": True, "assisted": True, "only_pings": False},
            )
            updated = self.bot.toggle_naming_setting(SERVER_ID, "enabled")
            self.assertFalse(updated["enabled"])
            self.assertTrue(updated["assisted"])
            updated = self.bot.toggle_naming_setting(SERVER_ID, "assisted")
            self.assertFalse(updated["assisted"])
            self.assertTrue(
                self.bot.naming_settings_for_guild(SERVER_ID + 1)["enabled"]
            )
            self.assertEqual(
                load_server_settings(self.bot.server_settings_path)[str(SERVER_ID)],
                {"enabled": False, "assisted": False, "only_pings": False},
            )
            self.bot.server_settings_path.write_text(
                f'{{"{SERVER_ID}":{{"enabled":true,"assisted":false,"pings":true}}}}',
                encoding="utf-8",
            )
            self.assertEqual(
                load_server_settings(self.bot.server_settings_path)[str(SERVER_ID)],
                {"enabled": True, "assisted": False, "only_pings": False},
            )
            updated = self.bot.toggle_naming_setting(SERVER_ID, "only_pings")
            self.assertTrue(updated["only_pings"])
            self.assertFalse(self.bot.naming_settings_for_guild(SERVER_ID + 1)["only_pings"])
            self.assertTrue(load_server_settings(self.bot.server_settings_path)[str(SERVER_ID)]["only_pings"])

    async def test_naming_settings_button_requires_permission_and_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.server_settings_path = Path(directory) / "settings.json"
            self.bot.server_settings = {}
            view = NamingSettingsView(self.bot, SERVER_ID)
            sections = [
                child
                for child in runtime_attribute(view.children[0], "children")
                if isinstance(child, discord.ui.Section)
            ]
            enabled_button = sections[0].accessory
            interaction = Mock()
            interaction.guild_id = SERVER_ID
            interaction.user.guild_permissions.manage_guild = False
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()

            await enabled_button.callback(interaction)

            interaction.response.send_message.assert_awaited_once()
            interaction.response.edit_message.assert_not_awaited()
            self.assertTrue(
                self.bot.naming_settings_for_guild(SERVER_ID)["enabled"]
            )
            interaction.user.guild_permissions.manage_guild = True

            await enabled_button.callback(interaction)

            self.assertFalse(
                self.bot.naming_settings_for_guild(SERVER_ID)["enabled"]
            )
            interaction.response.edit_message.assert_awaited_once()
            updated_view = awaited_kwargs(interaction.response.edit_message)["view"]
            updated_sections = [
                child
                for child in runtime_attribute(updated_view.children[0], "children")
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(runtime_attribute(runtime_attribute(updated_sections[0], "accessory"), "label"), "Off")

            mode_button = updated_sections[1].accessory
            await mode_button.callback(interaction)
            self.assertFalse(
                self.bot.naming_settings_for_guild(SERVER_ID)["assisted"]
            )
            updated_view = awaited_kwargs(interaction.response.edit_message)["view"]
            updated_sections = [
                child
                for child in runtime_attribute(updated_view.children[0], "children")
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(runtime_attribute(runtime_attribute(updated_sections[1], "accessory"), "label"), "Name only")
            pings_button = updated_sections[2].accessory
            await pings_button.callback(interaction)
            self.assertTrue(self.bot.naming_settings_for_guild(SERVER_ID)["only_pings"])
            updated_view = awaited_kwargs(interaction.response.edit_message)["view"]
            updated_sections = [
                child
                for child in runtime_attribute(updated_view.children[0], "children")
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(updated_sections[2].accessory.label, "On")

    async def test_naming_settings_button_accepts_configured_role(self) -> None:
        role_id = 900
        self.bot.command_permissions = {str(SERVER_ID): role_id}
        view = NamingSettingsView(self.bot, SERVER_ID)
        sections = [
            child
            for child in runtime_attribute(view.children[0], "children")
            if isinstance(child, discord.ui.Section)
        ]
        enabled_button = sections[0].accessory
        interaction = Mock()
        interaction.guild_id = SERVER_ID
        interaction.user.roles = [Mock(id=role_id)]
        interaction.user.guild_permissions.manage_guild = False
        interaction.response.edit_message = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await enabled_button.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()

    async def test_spawn_settings_disable_names_and_name_without_ping_targets(
        self,
    ) -> None:
        self.bot.image_http = Mock(close=AsyncMock())

        def spawn_message(message_id: int) -> Mock:
            message = Mock()
            message.id = message_id
            message.guild.id = SERVER_ID
            message.channel.id = 400 + message_id
            message.attachments = [
                Mock(content_type="image/png", url="https://example.test/spawn.png")
            ]
            message.embeds = []
            message.reply = AsyncMock()
            return message

        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": False,
            "assisted": True,
        }
        disabled_message = spawn_message(701)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Pikachu", 99.0)),
        ) as recognize:
            await self.bot.handle_spawn(disabled_message)
        disabled_message.reply.assert_not_awaited()
        recognize.assert_not_awaited()

        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
            "only_pings": True,
        }
        unpinged_message = spawn_message(702)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Pikachu", 99.0)),
        ) as recognize:
            await self.bot.handle_spawn(unpinged_message)
        unpinged_message.reply.assert_not_awaited()
        recognize.assert_awaited_once()

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bot.collection_path = Path(directory.name) / "collections.json"
        self.bot.collections = {reservation_key(SERVER_ID, "Pikachu"): [123]}
        save_reservations(self.bot.collection_path, self.bot.collections)
        pinged_message = spawn_message(703)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Pikachu", 99.0)),
        ) as recognize:
            await self.bot.handle_spawn(pinged_message)

        recognize.assert_awaited_once()
        pinged_message.reply.assert_awaited_once()
        content = pinged_message.reply.await_args.args[0]
        self.assertIn("<@123>", content)
        self.assertIn("Pikachu", content)
        self.assertNotIn("c pikachu", content)
        self.assertIsNone(awaited_kwargs(pinged_message.reply).get("embed"))

        self.bot.server_settings[str(SERVER_ID)]["only_pings"] = False
        name_only_message = spawn_message(704)
        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Charizard", 99.0)),
        ):
            await self.bot.handle_spawn(name_only_message)
        name_only_message.reply.assert_awaited_once()
        name_only_content = name_only_message.reply.await_args.args[0]
        self.assertIn("Charizard", name_only_content)
        self.assertNotIn("Copy Here", name_only_content)
        self.assertNotIn("c charizard", name_only_content)
        self.assertIsNone(awaited_kwargs(name_only_message.reply).get("embed"))

    async def test_unmatched_spawn_reports_failure_instead_of_silently_skipping(
        self,
    ) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
            "only_pings": True,
        }
        message = Mock()
        message.id = 710
        message.guild.id = SERVER_ID
        message.channel.id = 1210
        message.channel.name = "spawn-channel"
        message.jump_url = "https://discord.com/channels/1/1210/710"
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()
        alert_channel = Mock(spec=discord.TextChannel)
        alert_channel.send = AsyncMock()

        with (
            patch.object(
                self.bot,
                "get_channel",
                return_value=alert_channel,
            ) as get_channel,
            patch(
                "bot.recognize_pokemon",
                new=AsyncMock(
                    side_effect=bot_module.NoMatchError("No reference match")
                ),
            ) as recognize,
        ):
            await self.bot.handle_spawn(message)

        recognize.assert_awaited_once()
        message.reply.assert_not_awaited()
        get_channel.assert_called_once_with(
            bot_module.RECOGNITION_ALERT_CHANNEL_ID
        )
        alert_channel.send.assert_awaited_once()
        alert = alert_channel.send.await_args.args[0]
        self.assertIn(f"<@{bot_module.RECOGNITION_ALERT_USER_ID}>", alert)
        self.assertIn("<#1210>", alert)
        self.assertIn(message.jump_url, alert)
        self.assertNotIn("[#", alert)
        allowed_mentions = awaited_kwargs(alert_channel.send)["allowed_mentions"]
        self.assertEqual(
            [user.id for user in allowed_mentions.users],
            [bot_module.RECOGNITION_ALERT_USER_ID],
        )
        self.assertFalse(allowed_mentions.roles)
        self.assertFalse(allowed_mentions.everyone)
        self.assertEqual(self.bot.failed_recognition_count, 1)

    async def test_only_pings_matches_reserves_hunts_collections_and_types(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True, "assisted": False, "only_pings": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bot.shinyhunt_path = root / "hunts.json"
            self.bot.collection_path = root / "collections.json"
            self.bot.type_ping_path = root / "types.json"
            for index, kind in enumerate(("reserve", "shinyhunt", "collection", "type")):
                with self.subTest(kind=kind):
                    self.bot.reservations = (
                        {reservation_key(SERVER_ID, "Pikachu"): [123]}
                        if kind == "reserve" else {}
                    )
                    hunts = {reservation_key(SERVER_ID, "Pikachu"): [123]} if kind == "shinyhunt" else {}
                    collections = {reservation_key(SERVER_ID, "Pikachu"): [123]} if kind == "collection" else {}
                    types = {f"{SERVER_ID}:123": ["electric"]} if kind == "type" else {}
                    save_reservations(self.bot.shinyhunt_path, hunts)
                    save_reservations(self.bot.collection_path, collections)
                    save_type_pings(self.bot.type_ping_path, types)
                    message = Mock()
                    message.id = 800 + index
                    message.guild.id = SERVER_ID
                    message.channel.id = 1200 + index
                    message.attachments = [
                        Mock(content_type="image/png", url="https://example.test/spawn.png")
                    ]
                    message.embeds = []
                    message.reply = AsyncMock()
                    with patch("bot.recognize_pokemon", new=AsyncMock(return_value=("Pikachu", 99.0))):
                        await self.bot.handle_spawn(message)
                    message.reply.assert_awaited_once()
                    self.assertIn("<@123>", message.reply.await_args.args[0])

    async def test_only_pings_keeps_test_and_missingno_safety_replies(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True, "assisted": False, "only_pings": True,
        }
        for index, (name, test_mode) in enumerate((("Pikachu", True), ("Missingno", False))):
            with self.subTest(name=name):
                message = Mock()
                message.id = 820 + index
                message.guild.id = SERVER_ID
                message.channel.id = 1220 + index
                message.attachments = [
                    Mock(content_type="image/png", url="https://example.test/spawn.png")
                ]
                message.embeds = []
                message.reply = AsyncMock()
                with (
                    patch("bot.recognize_pokemon", new=AsyncMock(return_value=(name, 99.0))),
                    patch.object(self.bot, "set_poketwo_blocked", new=AsyncMock(return_value=True)),
                ):
                    await self.bot.handle_spawn(message, test_mode=test_mode)
                message.reply.assert_awaited_once()
                if not test_mode:
                    self.assertIn("staff", message.reply.await_args.args[0])

    async def test_afk_preferences_filter_shinyhunt_and_collection_pings(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        self.bot.shinyhunters = {reservation_key(SERVER_ID, "Absol"): [123]}
        self.bot.collections = {reservation_key(SERVER_ID, "Absol"): [456]}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bot.shinyhunt_path = Path(directory.name) / "shinyhunts.json"
        self.bot.collection_path = Path(directory.name) / "collections.json"
        save_reservations(self.bot.shinyhunt_path, self.bot.shinyhunters)
        save_reservations(self.bot.collection_path, self.bot.collections)
        self.bot.afk_settings = {
            f"{SERVER_ID}:123": {"shinyhunt": False, "collection": True},
            f"{SERVER_ID}:456": {"shinyhunt": True, "collection": True},
        }
        message = Mock()
        message.id = 705
        message.guild.id = SERVER_ID
        message.channel.id = 1205
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Absol", 99.0)),
        ):
            await self.bot.handle_spawn(message)

        message.reply.assert_awaited_once()
        content = message.reply.await_args.args[0]
        self.assertIn("Collection: <@456>", content)
        self.assertNotIn("Shinyhunt:", content)

        self.bot.server_settings[str(SERVER_ID)]["only_pings"] = True
        self.bot.afk_settings[f"{SERVER_ID}:456"]["collection"] = False
        muted_message = Mock()
        muted_message.id = 706
        muted_message.guild.id = SERVER_ID
        muted_message.channel.id = 1206
        muted_message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        muted_message.embeds = []
        muted_message.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Absol", 99.0)),
        ):
            await self.bot.handle_spawn(muted_message)

        muted_message.reply.assert_not_awaited()

    async def test_spawns_reload_saved_collection_and_shinyhunt_clear_state(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.collections = {reservation_key(SERVER_ID, "Absol"): [123]}
        self.bot.shinyhunters = {reservation_key(SERVER_ID, "Absol"): [456]}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bot.collection_path = Path(directory.name) / "collections.json"
        self.bot.shinyhunt_path = Path(directory.name) / "shinyhunts.json"
        save_reservations(self.bot.collection_path, {})
        save_reservations(self.bot.shinyhunt_path, {})

        message = Mock()
        message.id = 707
        message.guild.id = SERVER_ID
        message.channel.id = 1207
        message.attachments = [
            Mock(content_type="image/png", url="https://example.test/spawn.png")
        ]
        message.embeds = []
        message.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Absol", 99.0)),
        ):
            await self.bot.handle_spawn(message)

        message.reply.assert_awaited_once()
        content = message.reply.await_args.args[0]
        self.assertNotIn("Collection:", content)
        self.assertNotIn("Shinyhunt:", content)
        self.assertEqual(self.bot.collections, {})
        self.assertEqual(self.bot.shinyhunters, {})

    async def test_api_status_reports_response_metrics_and_load(self) -> None:
        self.bot.pokemon_named_count = 12
        now = time.monotonic()
        self.bot.recognition_durations.extend(
            [(now - 2, 0.02, 0.4), (now - 1, 0.03, 1.2)]
        )
        message = Mock()
        message.reply = AsyncMock()

        await self.bot.handle_api_status(message)

        embed = awaited_kwargs(message.reply)["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(len(embed.fields), 15)
        self.assertEqual(
            [field.name for field in embed.fields[:6]],
            [
                "Activity",
                "Active Incense",
                "Store (latest)",
                "Store (avg)",
                "JSON load",
                "CSV load",
            ],
        )
        self.assertTrue(all(field.inline for field in embed.fields))
        self.assertEqual(fields["Pokémons Named"], "12")
        self.assertEqual(fields["Inference Fastest"], "20 ms")
        self.assertEqual(fields["Inference Slowest"], "30 ms")
        self.assertEqual(fields["Inference Avg"], "25 ms")
        self.assertEqual(fields["Inference Latest"], "30 ms")
        self.assertEqual(fields["Response Fastest"], "400 ms")
        self.assertEqual(fields["Response Slowest"], "1200 ms")
        self.assertEqual(fields["Response Avg"], "800 ms")
        self.assertEqual(fields["Response Latest"], "1200 ms")
        self.assertEqual(fields["CSV load"], "Not used")
        self.assertIn("Window: 5 min rolling", embed.footer.text)

    async def test_api_command_is_routed_in_the_configured_server(self) -> None:
        message = Mock()
        message.author.bot = False
        message.channel.guild.id = SERVER_ID
        message.content = "v!api"
        message.embeds = []
        message.attachments = []
        message.guild = Mock()
        self.bot.handle_api_status = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_api_status.assert_awaited_once_with(message)

    async def test_event_command_shows_event_menu(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.content = "v!event"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        self.assertIsInstance(
            awaited_kwargs(message.reply)["view"],
            EventMenuView,
        )

    async def test_chat_event_counts_only_qualifying_messages_for_participants(self) -> None:
        channel = Mock()
        channel.id = 456
        session = ChatEventSession(host_id=123, channel=channel)
        session.participant_ids = {123}
        session.sentence_counts = {123: 0}
        session.collecting = True
        self.bot.chat_events[channel.id] = session

        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.id = channel.id
        message.content = "This message has four words. Too short."

        self.bot.track_chat_event_message(message)

        self.assertEqual(session.sentence_counts[123], 1)

    def test_chat_event_sentence_count_requires_four_words_per_sentence(self) -> None:
        self.assertEqual(
            count_qualifying_sentences(
                "This has four words. Too short. Here are exactly four."
            ),
            2,
        )
        self.assertEqual(count_qualifying_sentences("one two three"), 0)

    def test_chat_event_accepts_custom_minutes_and_hours(self) -> None:
        self.assertEqual(parse_chat_event_duration("7 minutes"), (420, "7 minutes"))
        self.assertEqual(parse_chat_event_duration("2 hours"), (7200, "2 hours"))
        self.assertEqual(parse_chat_event_duration("1.5h"), (5400, "1.5 hours"))
        self.assertEqual(parse_chat_event_duration("3"), (180, "3 minutes"))
        for invalid in ("0 minutes", "-2 hours", "seven minutes", "2 days"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(parse_chat_event_duration(invalid))

    async def test_chat_event_requires_at_least_two_signups(self) -> None:
        channel = Mock()
        channel.id = 456
        channel.send = AsyncMock()
        session = ChatEventSession(host_id=123, channel=channel)
        session.participant_ids = {123}
        session.message = Mock()
        session.message.reactions = []
        session.message.clear_reactions = AsyncMock()
        self.bot.chat_events[channel.id] = session

        with patch("bot.asyncio.sleep", new=AsyncMock()):
            await self.bot.run_chat_event(session)

        channel.send.assert_awaited_once()
        self.assertIn("at least 2 participants", channel.send.await_args.args[0])
        self.assertNotIn(channel.id, self.bot.chat_events)

    async def test_grab_requires_the_configured_role_when_enabled(self) -> None:
        role_id = 900
        self.bot.org_rpc = None
        self.bot.command_permissions = {str(SERVER_ID): role_id}
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.handle_grab_command = AsyncMock()
        self.bot.premium_servers = {str(SERVER_ID): "bronze"}

        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.author.roles = []
        message.channel.id = 456
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!grab"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_grab_command.assert_not_awaited()
        self.assertIn("configured role", message.reply.await_args.args[0])

        message.author.roles = [Mock(id=role_id)]
        message.reply.reset_mock()
        await self.bot.on_message(message)

        self.bot.handle_grab_command.assert_awaited_once_with(
            message, silent_h_mode=False
        )
        message.reply.assert_not_awaited()

    async def test_grab_requires_premium(self) -> None:
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.handle_grab_command = AsyncMock()
        self.bot.premium_servers = {}

        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.author.roles = []
        message.channel.id = 456
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!grab"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        self.bot.handle_grab_command.assert_not_awaited()
        self.assertIn("premium", message.reply.await_args.args[0])

    async def test_droplog_command_routes_to_drop_log_configuration(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.guild.id = SERVER_ID
        message.channel.guild.id = SERVER_ID
        message.content = "v!droplog <#12345>"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()
        self.bot.pokeball_drops.configure_log = AsyncMock()

        await self.bot.on_message(message)

        self.bot.pokeball_drops.configure_log.assert_awaited_once_with(message)
        message.reply.assert_not_awaited()

    async def test_settings_command_sends_server_settings_layout(self) -> None:
        message = Mock()
        message.author.bot = False
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!settings"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        reply_kwargs = awaited_kwargs(message.reply)
        self.assertFalse(reply_kwargs["mention_author"])
        view = reply_kwargs["view"]
        self.assertIsInstance(view, ServerSettingsView)
        self.assertTrue(view.has_components_v2())
        sections = [
            child
            for child in runtime_attribute(view.children[0], "children")
            if isinstance(child, discord.ui.Section)
        ]
        self.assertEqual(len(sections), 4)
        self.assertEqual(
            [runtime_attribute(runtime_attribute(section, "accessory"), "label") for section in sections],
            ["Open"] * 4,
        )
        self.assertEqual(
            [runtime_attribute(runtime_attribute(section, "accessory"), "custom_id") for section in sections],
            [
                "server_settings:open:naming",
                "server_settings:open:roles",
                "server_settings:open:starboard",
                "server_settings:open:appearance",
            ],
        )
        interaction = Mock()
        interaction.guild_id = SERVER_ID
        interaction.response.edit_message = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await sections[0].accessory.callback(interaction)

        naming_view = awaited_kwargs(interaction.response.edit_message)["view"]
        self.assertIsInstance(naming_view, NamingSettingsView)

    async def test_afk_command_sends_personal_toggle_layout(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!afk"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        view = awaited_kwargs(message.reply)["view"]
        self.assertIsInstance(view, AFKSettingsView)
        self.assertTrue(view.has_components_v2())
        sections = [
            child
            for child in runtime_attribute(view.children[0], "children")
            if isinstance(child, discord.ui.Section)
        ]
        self.assertEqual(
            [runtime_attribute(runtime_attribute(section, "accessory"), "label") for section in sections],
            ["On", "On"],
        )
        self.assertEqual(
            [runtime_attribute(runtime_attribute(section, "accessory"), "custom_id") for section in sections],
            ["afk_settings:shinyhunt", "afk_settings:collection"],
        )

    async def test_afk_toggle_persists_for_user_and_requires_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.afk_settings_path = Path(directory) / "afk_settings.json"
            self.bot.afk_settings = {}
            view = AFKSettingsView(self.bot, SERVER_ID, 123)
            sections = [
                child
                for child in runtime_attribute(view.children[0], "children")
                if isinstance(child, discord.ui.Section)
            ]
            collection_button = sections[1].accessory
            interaction = Mock()
            interaction.guild_id = SERVER_ID
            interaction.user.id = 456
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()

            await collection_button.callback(interaction)

            interaction.response.send_message.assert_awaited_once()
            interaction.response.edit_message.assert_not_awaited()
            self.assertTrue(
                self.bot.afk_settings_for_user(SERVER_ID, 123)["collection"]
            )

            interaction.user.id = 123
            await collection_button.callback(interaction)

            self.assertFalse(
                self.bot.afk_settings_for_user(SERVER_ID, 123)["collection"]
            )
            self.assertTrue(
                self.bot.afk_settings_for_user(SERVER_ID, 123)["shinyhunt"]
            )
            self.assertEqual(
                load_afk_settings(self.bot.afk_settings_path),
                {f"{SERVER_ID}:123": {"shinyhunt": True, "collection": False}},
            )
            updated_view = awaited_kwargs(interaction.response.edit_message)["view"]
            updated_sections = [
                child
                for child in runtime_attribute(updated_view.children[0], "children")
                if isinstance(child, discord.ui.Section)
            ]
            self.assertEqual(runtime_attribute(runtime_attribute(updated_sections[1], "accessory"), "label"), "Off")


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())
        self.directory = tempfile.TemporaryDirectory()
        self.bot.profile_data_path = Path(self.directory.name) / "profile_data.json"
        (
            self.bot.profiles,
            self.bot.profile_stats,
            self.bot.profile_records,
            self.bot.profile_seen_catch_ids,
        ) = load_profile_data(self.bot.profile_data_path)
        self.bot.profile_shop_path = Path(self.directory.name) / "profile_shop.json"
        self.bot.profile_shop = {}
        self.bot.profile_inventory_path = (
            Path(self.directory.name) / "profile_inventory.json"
        )
        self.bot.profile_inventory = bot_module.load_profile_inventory(
            self.bot.profile_inventory_path,
            self.bot.profiles,
        )
        self.bot.pokeball_drops = bot_module.PokeballDrops(
            self.bot,
            Path(self.directory.name) / "pokeball_drops.json",
            Path(self.directory.name) / "dyes.json",
            bot_module.save_profile_inventory,
        )

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self.directory.cleanup()

    def bingo_message(self, message_id: int, content: str) -> SimpleNamespace:
        source = SimpleNamespace(
            author=SimpleNamespace(id=123, bot=False),
        )
        message = SimpleNamespace(
            id=message_id,
            content=content,
            embeds=[],
            author=SimpleNamespace(
                id=self.bot.config.poketwo_bot_id,
                bot=True,
            ),
            reference=SimpleNamespace(
                resolved=source,
                message_id=message_id - 1,
            ),
            channel=SimpleNamespace(id=456),
            guild=None,
            reply=AsyncMock(),
        )
        return message

    async def test_bingo_quest_rewards_25_pokedollars_once(self) -> None:
        message = self.bingo_message(
            501,
            "You completed Bingo quest A4 (Release 20 pokémon) "
            "and received a Sunlit Chest!",
        )
        with (
            patch.object(self.bot, "track_profile_catch"),
            patch.object(self.bot, "track_profile_box_shiny", new=AsyncMock()),
            patch.object(self.bot, "handle_catch_starboard", new=AsyncMock()),
            patch.object(self.bot, "is_allowed_channel", return_value=False),
        ):
            await self.bot.on_message(message)
            await self.bot.on_message(message)

        self.assertEqual(
            self.bot.profile_balances_for_user(123)[bot_module.PROFILE_SHOP_CURRENCY],
            25,
        )
        message.reply.assert_awaited_once()
        self.assertEqual(
            message.reply.await_args.args[0],
            "Trainer you completed your bingo and got 25 pokedollars!",
        )
        self.assertFalse(
            message.reply.await_args.kwargs["allowed_mentions"].users
        )
        self.assertEqual(
            bot_module.load_profile_inventory(self.bot.profile_inventory_path, {}),
            self.bot.profile_inventory,
        )

    async def test_bingo_blackout_rewards_200_pokedollars_once(self) -> None:
        message = self.bingo_message(
            502,
            "You got a Bingo! (12/12) You received a reward! "
            "Your card is a Blackout! You received a Level 31 Victini!",
        )
        with (
            patch.object(self.bot, "track_profile_catch"),
            patch.object(self.bot, "track_profile_box_shiny", new=AsyncMock()),
            patch.object(self.bot, "handle_catch_starboard", new=AsyncMock()),
            patch.object(self.bot, "is_allowed_channel", return_value=False),
        ):
            await self.bot.on_message(message)
            await self.bot.on_message(message)

        self.assertEqual(
            self.bot.profile_balances_for_user(123)[bot_module.PROFILE_SHOP_CURRENCY],
            200,
        )
        message.reply.assert_awaited_once()
        self.assertEqual(
            message.reply.await_args.args[0],
            "Trainer you completed your bingo and got 200 pokedollars!",
        )

    async def test_shop_shows_three_categories_and_empty_category(self) -> None:
        view = bot_module.ProfileShopView(self.bot, 123)
        category_buttons = [
            child
            for child in view.children
            if isinstance(child, bot_module.ProfileShopCategoryButton)
        ]
        self.assertEqual(
            [button.label for button in category_buttons],
            ["Frames", "Backgrounds", "Middle backgrounds"],
        )

        interaction = Mock()
        interaction.response.edit_message = AsyncMock()
        await category_buttons[0].callback(interaction)
        self.assertEqual(view.embed.description, "No frames are in the shop yet.")
        self.assertTrue(cast(discord.ui.Button, view.children[-2]).disabled)
        self.assertTrue(cast(discord.ui.Button, view.children[-1]).disabled)

        self.bot.profile_shop = bot_module.load_profile_shop(
            Path(__file__).with_name("data") / "profile_shop.json"
        )
        populated_view = bot_module.ProfileShopView(self.bot, 123)
        frames_button = next(
            child
            for child in populated_view.children
            if isinstance(child, bot_module.ProfileShopCategoryButton)
            and child.setting == "frame"
        )
        await frames_button.callback(interaction)
        self.assertIsNone(populated_view.embed.thumbnail.url)
        self.assertIn("Amethyst", populated_view.embed.description or "")
        self.assertIn("45,000 Pokédollar", populated_view.embed.description or "")
        self.assertIn("60,000 Pokédollar", populated_view.embed.description or "")
        self.assertIn("50,000 Pokédollar", populated_view.embed.description or "")
        self.assertIn("`v!buy frame Ocean`", populated_view.embed.description or "")
        self.assertIn(
            "`v!shop preview frame Ocean`", populated_view.embed.description or ""
        )
        self.assertIn("`v!buy frame Celestial`", populated_view.embed.description or "")
        self.assertIn(
            "`v!shop preview frame Celestial`", populated_view.embed.description or ""
        )
        self.assertIn("`v!buy frame Amethyst`", populated_view.embed.description or "")
        self.assertIn(
            "`v!shop preview frame Amethyst`", populated_view.embed.description or ""
        )
        self.assertNotIn(
            bot_module.profile_asset_codes()["frame:amethyst"],
            populated_view.embed.description or "",
        )
        self.assertNotIn(
            bot_module.profile_asset_codes()["frame:celestial"],
            populated_view.embed.description or "",
        )
        self.assertNotIn(
            bot_module.profile_asset_codes()["frame:ocean"],
            populated_view.embed.description or "",
        )
        icon_files = bot_module.profile_currency_icon_files()
        try:
            self.assertEqual([file.filename for file in icon_files], ["pokedollar.png"])
        finally:
            for file in icon_files:
                file.close()

    async def test_inventory_lists_equipped_assets_with_codes(self) -> None:
        profile: dict[str, int | str] = {
            "text_color": "white",
            "background": "default",
            "middle_background": "white",
            "frame": "mystic",
        }
        self.bot.profiles = {"123": profile}
        self.bot.profile_inventory = bot_module.load_profile_inventory(
            self.bot.profile_inventory_path,
            self.bot.profiles,
        )

        view = bot_module.ProfileInventoryView(self.bot, 123)

        self.assertEqual(view.embed.author.name, "0 Pokédollar")
        self.assertEqual(
            view.embed.author.icon_url,
            "attachment://pokedollar.png",
        )
        self.assertIsNone(view.embed.thumbnail.url)
        expected_code = self.bot.profile_inventory["123"]["assets"][0]["code"]
        self.assertIn(f"{expected_code} - Mystic", view.embed.description or "")

        message = Mock()
        message.author.id = 123
        message.author.display_name = "Trainer"
        message.reply = AsyncMock()
        await self.bot.handle_profile_inventory_command(message)
        inventory_kwargs = awaited_kwargs(message.reply)
        self.assertEqual(inventory_kwargs["content"], "Trainer's Inventory")
        self.assertIsNone(inventory_kwargs["embed"].title)
        self.assertEqual(
            inventory_kwargs["embed"].author.name,
            "0 Pokédollar",
        )
        self.assertEqual(
            inventory_kwargs["embed"].author.icon_url,
            "attachment://pokedollar.png",
        )
        self.assertIsNone(inventory_kwargs["embed"].thumbnail.url)
        self.assertIn(
            self.bot.profile_inventory["123"]["assets"][0]["code"],
            inventory_kwargs["embed"].description,
        )
        self.assertEqual(
            [file.filename for file in inventory_kwargs["files"]],
            ["pokedollar.png"],
        )
        for file in inventory_kwargs["files"]:
            file.close()

    async def test_buy_confirmation_deducts_currency_and_equips_asset(self) -> None:
        asset_id = "frame:mystic"
        self.bot.profile_shop = {
            asset_id: {
                "type": "frame",
                "key": "mystic",
                "price": 80,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            }
        }
        self.bot.profile_inventory = {
            "123": {
                "balances": {bot_module.PROFILE_SHOP_CURRENCY: 200},
                "assets": [],
            }
        }
        self.assertNotIn("mystic", self.bot.profile_choices_for_user(123, "frame"))
        message = Mock()
        message.guild = Mock()
        message.author.id = 123
        message.content = "v!buy mystic"
        message.reply = AsyncMock(return_value=Mock())

        await self.bot.handle_profile_buy_command(message)

        purchase_view = awaited_kwargs(message.reply)["view"]
        self.assertIsInstance(purchase_view, bot_module.ProfilePurchaseView)
        self.assertIn(
            "Are you sure",
            awaited_kwargs(message.reply)["embed"].description,
        )
        self.assertNotIn(
            bot_module.profile_asset_codes()[asset_id],
            awaited_kwargs(message.reply)["embed"].description,
        )
        self.assertIsNone(awaited_kwargs(message.reply)["embed"].thumbnail.url)
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.edit_message = AsyncMock()
        yes_button = next(
            child
            for child in purchase_view.children
            if isinstance(child, discord.ui.Button) and child.label == "Yes"
        )

        await yes_button.callback(interaction)

        self.assertEqual(self.bot.profile_settings_for_user(123)["frame"], "mystic")
        self.assertIn(
            "unique code in `v!inv`",
            awaited_kwargs(interaction.response.edit_message)["content"],
        )
        self.assertEqual(
            self.bot.profile_inventory["123"]["balances"][bot_module.PROFILE_SHOP_CURRENCY],
            120,
        )
        first_code = self.bot.profile_inventory["123"]["assets"][0]["code"]
        self.bot.pokeball_drops.data["users"]["123"] = {
            "xp": 0,
            "dyes": [],
            "applied": {
                first_code: {
                    "code": "1234567", "name": "Pink", "type": "frame",
                    "rarity": "normal", "color": "#FF88CC",
                }
            },
            "selected": {"frame": first_code},
        }

        await self.bot.handle_profile_buy_command(message)
        purchase_view = awaited_kwargs(message.reply)["view"]
        second_interaction = Mock()
        second_interaction.user.id = 123
        second_interaction.response.edit_message = AsyncMock()
        yes_button = next(
            child
            for child in purchase_view.children
            if isinstance(child, discord.ui.Button) and child.label == "Yes"
        )
        await yes_button.callback(second_interaction)

        owned_copies = self.bot.profile_inventory["123"]["assets"]
        self.assertEqual(len(owned_copies), 2)
        self.assertEqual(
            [(asset["type"], asset["key"]) for asset in owned_copies],
            [("frame", "mystic"), ("frame", "mystic")],
        )
        self.assertEqual(len({asset["code"] for asset in owned_copies}), 2)
        self.assertEqual(
            self.bot.pokeball_drops.data["users"]["123"]["selected"]["frame"],
            owned_copies[1]["code"],
        )
        self.assertNotIn(
            "frame",
            self.bot.pokeball_drops.appearance(123, self.bot.profile_settings_for_user(123)),
        )
        self.assertTrue(all(len(asset["code"]) == 7 for asset in owned_copies))
        inventory_view = bot_module.ProfileInventoryView(self.bot, 123)
        inventory_lines = (inventory_view.embed.description or "").splitlines()
        self.assertEqual(
            sum(line.endswith(" - Mystic") for line in inventory_lines),
            2,
        )
        self.assertTrue(
            all(
                f"{asset['code']} - Mystic" in inventory_lines
                for asset in owned_copies
            )
        )
        self.assertEqual(
            self.bot.profile_inventory["123"]["balances"][bot_module.PROFILE_SHOP_CURRENCY],
            40,
        )
        self.assertEqual(
            bot_module.load_profile_inventory(self.bot.profile_inventory_path, {}),
            self.bot.profile_inventory,
        )
        self.bot.profile_inventory["456"] = {
            "balances": {bot_module.PROFILE_SHOP_CURRENCY: 80},
            "assets": [],
        }
        self.bot.buy_profile_asset(456, asset_id)
        other_code = self.bot.profile_inventory["456"]["assets"][0]["code"]
        self.assertNotIn(other_code, {asset["code"] for asset in owned_copies})
        self.assertEqual(
            bot_module.load_profile_inventory(self.bot.profile_inventory_path, {}),
            self.bot.profile_inventory,
        )

    async def test_shop_previews_each_asset_without_changing_user_data(self) -> None:
        self.bot.profile_shop = {
            "frame:amethyst": {
                "type": "frame", "key": "amethyst", "price": 45000,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            },
            "frame:celestial": {
                "type": "frame", "key": "celestial", "price": 60000,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            },
            "frame:ocean": {
                "type": "frame", "key": "ocean", "price": 50000,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            },
            "background:cosmog": {
                "type": "background", "key": "cosmog", "price": 50,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            },
            "middle_background:cosmog": {
                "type": "middle_background", "key": "cosmog", "price": 50,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            },
        }
        self.bot.profile_inventory = {
            "123": {"balances": {bot_module.PROFILE_SHOP_CURRENCY: 0}, "assets": []}
        }
        message = Mock()
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.display_name = "Trainer"
        message.author.display_avatar.read = AsyncMock(return_value=None)
        message.reply = AsyncMock()
        cases = (
            ("v!shop preview Amethyst", "frame", "amethyst"),
            ("v!shop preview Celestial", "frame", "celestial"),
            ("v!shop preview Ocean", "frame", "ocean"),
            ("v!shop preview background Cosmog", "background", "cosmog"),
            ("v!shop preview middlebackground cosmog", "middle_background", "cosmog"),
        )
        with (
            patch.object(self.bot, "load_profile_emoji_assets", new=AsyncMock(return_value={})),
            patch.object(bot_module, "render_profile_image", wraps=render_profile_image) as render,
        ):
            for command, setting, key in cases:
                with self.subTest(command=command):
                    message.content = command
                    await self.bot.handle_profile_shop_command(message)
                    kwargs = awaited_kwargs(message.reply)
                    self.assertIn("not purchased or equipped", kwargs["content"])
                    self.assertEqual(kwargs["file"].filename, "profile-preview.png")
                    with Image.open(kwargs["file"].fp) as preview:
                        self.assertGreater(preview.width, 0)
                    kwargs["file"].close()
                    self.assertEqual(render.call_args.args[0][setting], key)
                    self.assertEqual(self.bot.profiles, {})
                    self.assertEqual(self.bot.profile_inventory["123"]["assets"], [])
                    self.assertEqual(
                        self.bot.profile_inventory["123"]["balances"][bot_module.PROFILE_SHOP_CURRENCY],
                        0,
                    )

    async def test_shop_name_lookup_rejects_codes_and_disambiguates_categories(self) -> None:
        self.bot.profile_shop = {
            f"{setting}:cosmog": {
                "type": setting, "key": "cosmog", "price": 50,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            }
            for setting in ("background", "middle_background")
        }
        self.assertEqual(len(self.bot.profile_shop_items_for_query("Cosmog")), 2)
        self.assertEqual(
            self.bot.profile_shop_items_for_query("middle background Cosmog")[0][0],
            "middle_background:cosmog",
        )
        self.assertEqual(
            self.bot.profile_shop_items_for_query("background cosmog")[0][0],
            "background:cosmog",
        )
        self.assertEqual(
            self.bot.profile_shop_items_for_query(
                bot_module.profile_asset_codes()["background:cosmog"]
            ),
            [],
        )
        message = Mock()
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.reply = AsyncMock()
        for content in (
            "v!shop preview Cosmog",
            "v!buy Cosmog",
            "v!buy " + bot_module.profile_asset_codes()["background:cosmog"],
        ):
            with self.subTest(content=content):
                message.content = content
                if content.startswith("v!buy"):
                    await self.bot.handle_profile_buy_command(message)
                else:
                    await self.bot.handle_profile_shop_command(message)
                self.assertIn("couldn't find one matching", message.reply.await_args.args[0])

    async def test_shop_preview_command_is_routed(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.guild.id = SERVER_ID
        message.channel.guild.id = SERVER_ID
        message.content = "v!shop preview Amethyst"
        message.embeds = []
        message.attachments = []
        with patch.object(
            self.bot, "handle_profile_shop_command", new=AsyncMock()
        ) as handler:
            await self.bot.on_message(message)
        handler.assert_awaited_once_with(message)

    async def test_purchase_with_insufficient_currency_changes_nothing(self) -> None:
        asset_id = "frame:amethyst"
        self.bot.profile_shop = {
            asset_id: {
                "type": "frame",
                "key": "amethyst",
                "price": 45000,
                "currency": bot_module.PROFILE_SHOP_CURRENCY,
            }
        }
        self.bot.profile_inventory = {
            "123": {
                "balances": {bot_module.PROFILE_SHOP_CURRENCY: 44999},
                "assets": [],
            }
        }
        message = Mock()
        message.guild = Mock()
        message.author.id = 123
        message.content = "v!buy amethyst"
        message.reply = AsyncMock(return_value=Mock())
        await self.bot.handle_profile_buy_command(message)
        purchase_view = awaited_kwargs(message.reply)["view"]
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.edit_message = AsyncMock()
        yes_button = next(
            child
            for child in purchase_view.children
            if isinstance(child, discord.ui.Button) and child.label == "Yes"
        )

        await yes_button.callback(interaction)

        self.assertEqual(self.bot.profiles, {})
        self.assertEqual(
            self.bot.profile_inventory["123"]["balances"][bot_module.PROFILE_SHOP_CURRENCY],
            44999,
        )
        self.assertIn(
            "You don't have enough Pokédollar",
            awaited_kwargs(interaction.response.edit_message)["content"],
        )

    async def test_celestial_purchase_requires_60000_and_creates_unique_copies(self) -> None:
        self.bot.profile_shop = bot_module.load_profile_shop(
            Path(__file__).with_name("data") / "profile_shop.json"
        )
        currency = bot_module.PROFILE_SHOP_CURRENCY
        self.bot.profile_inventory = {
            "123": {"balances": {currency: 59999}, "assets": []}
        }
        with self.assertRaisesRegex(ValueError, "don't have enough"):
            self.bot.buy_profile_asset(123, "frame:celestial")
        self.assertEqual(self.bot.profile_inventory["123"]["balances"][currency], 59999)
        self.assertEqual(self.bot.profile_inventory["123"]["assets"], [])
        self.assertEqual(self.bot.profiles, {})

        self.bot.profile_inventory["123"]["balances"][currency] = 120000
        self.bot.buy_profile_asset(123, "frame:celestial")
        self.bot.buy_profile_asset(123, "frame:celestial")
        inventory = self.bot.profile_inventory["123"]
        self.assertEqual(inventory["balances"][currency], 0)
        self.assertEqual(self.bot.profile_settings_for_user(123)["frame"], "celestial")
        self.assertEqual(len(inventory["assets"]), 2)
        self.assertEqual(len({asset["code"] for asset in inventory["assets"]}), 2)
        self.assertEqual(
            bot_module.load_profile_inventory(self.bot.profile_inventory_path, {}),
            self.bot.profile_inventory,
        )

    async def test_ocean_purchase_requires_50000_and_creates_unique_copies(self) -> None:
        self.bot.profile_shop = bot_module.load_profile_shop(
            Path(__file__).with_name("data") / "profile_shop.json"
        )
        currency = bot_module.PROFILE_SHOP_CURRENCY
        self.bot.profile_inventory = {
            "123": {"balances": {currency: 49999}, "assets": []}
        }
        with self.assertRaisesRegex(ValueError, "don't have enough"):
            self.bot.buy_profile_asset(123, "frame:ocean")
        self.assertEqual(self.bot.profile_inventory["123"]["balances"][currency], 49999)
        self.assertEqual(self.bot.profile_inventory["123"]["assets"], [])
        self.assertEqual(self.bot.profiles, {})

        self.bot.profile_inventory["123"]["balances"][currency] = 100000
        self.bot.buy_profile_asset(123, "frame:ocean")
        self.bot.buy_profile_asset(123, "frame:ocean")
        inventory = self.bot.profile_inventory["123"]
        self.assertEqual(inventory["balances"][currency], 0)
        self.assertEqual(self.bot.profile_settings_for_user(123)["frame"], "ocean")
        self.assertEqual(len(inventory["assets"]), 2)
        self.assertEqual(len({asset["code"] for asset in inventory["assets"]}), 2)
        self.assertEqual(
            bot_module.load_profile_inventory(self.bot.profile_inventory_path, {}),
            self.bot.profile_inventory,
        )

    async def test_profile_command_sends_image_and_edit_button(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.author.display_name = "Trainer"
        message.guild.get_member.return_value = message.author
        message.author.display_avatar.read = AsyncMock(return_value=bot_module.PROFILE_SHOP_CURRENCY_ICON.read_bytes())
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.content = "v!profile"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock(return_value=Mock())

        await self.bot.on_message(message)

        message.reply.assert_awaited_once()
        kwargs = awaited_kwargs(message.reply)
        self.assertFalse(kwargs["mention_author"])
        self.assertNotIn("embed", kwargs)
        self.assertEqual(kwargs["file"].filename, "profile.png")
        self.assertIsInstance(kwargs["view"], ProfileView)
        self.assertEqual(kwargs["view"].children[0].label, "Edit")

    async def test_profile_command_can_target_a_mentioned_member(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.guild.get_member.return_value.display_name = "Target"
        message.guild.get_member.return_value.display_avatar.read = AsyncMock(return_value=bot_module.PROFILE_SHOP_CURRENCY_ICON.read_bytes())
        message.content = "v!profile <@!456>"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock(return_value=Mock())
        self.bot.is_application_owner = AsyncMock(return_value=False)
        self.bot.profile_stats[f"{SERVER_ID}:456"] = {
            "total": 25,
            "shiny": 2,
            "low_iv": 3,
            "high_iv": 4,
            "gmax": 5,
            "missingno": 6,
        }

        await self.bot.on_message(message)

        view = awaited_kwargs(message.reply)["view"]
        self.assertEqual(view.user_id, 456)
        self.assertEqual(view.guild_id, SERVER_ID)
        self.assertIsNone(view.preview_settings)

    async def test_owner_can_open_temporary_profile_preview(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.guild.id = SERVER_ID
        message.guild.id = SERVER_ID
        message.guild.get_member.return_value.display_name = "Target"
        message.guild.get_member.return_value.display_avatar.read = AsyncMock(return_value=bot_module.PROFILE_SHOP_CURRENCY_ICON.read_bytes())
        message.content = "v!profile <@!456>"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock(return_value=Mock())
        self.bot.is_application_owner = AsyncMock(return_value=True)

        await self.bot.on_message(message)

        kwargs = awaited_kwargs(message.reply)
        view = kwargs["view"]
        self.assertEqual(view.user_id, 456)
        self.assertEqual(view.preview_owner_id, 123)
        self.assertEqual(view.preview_settings, PROFILE_DEFAULTS)
        self.assertIn("temporary", kwargs["content"])

    async def test_profile_preview_edits_only_temporary_settings(self) -> None:
        self.bot.set_profile_setting(456, "text_color", "blue")
        self.bot.is_application_owner = AsyncMock(return_value=True)
        profile_view = ProfileView(
            self.bot,
            456,
            SERVER_ID,
            preview_owner_id=123,
        )
        select = ProfileEditView(profile_view).children[0]
        set_runtime_attribute(select, "_values", ["pink"])
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.defer = AsyncMock()
        interaction.message.edit = AsyncMock()
        interaction.followup.send = AsyncMock()

        await select.callback(interaction)

        preview_settings = require_not_none(profile_view.preview_settings)
        self.assertEqual(preview_settings["text_color"], "pink")
        self.assertEqual(self.bot.profile_settings_for_user(456)["text_color"], "blue")
        self.assertEqual(
            load_profile_data(self.bot.profile_data_path)[0]["456"]["text_color"],
            "blue",
        )

    async def _pick_music(self, select, interaction) -> None:
        interaction.message.edit = AsyncMock()
        with patch.object(
            ProfileMusicSelect, "values", ["return_to_me"], create=True
        ):
            await select.callback(interaction)

    async def test_music_picker_is_only_for_its_owner_and_plays_privately(
        self,
    ) -> None:
        profile_view = ProfileView(self.bot, 456, SERVER_ID)
        editor = ProfileEditView(profile_view)
        self.assertEqual(len(editor.children), 5)
        select = editor.children[4]
        self.assertEqual(runtime_attribute(select, "placeholder"), "Music")
        self.assertEqual(
            [option.label for option in runtime_attribute(select, "options")], ["Return to me"]
        )
        self.assertTrue(PROFILE_RETURN_TO_ME["return_to_me"][2].exists())
        preview_view = ProfileView(
            self.bot, 456, SERVER_ID, preview_owner_id=123
        )
        self.assertEqual(len(ProfileEditView(preview_view).children), 4)

        interaction = Mock()
        interaction.user.id = 789
        interaction.response.send_message = AsyncMock()
        with patch.object(
            ProfileMusicSelect, "values", ["return_to_me"], create=True
        ):
            await select.callback(interaction)
        self.assertEqual(
            interaction.response.send_message.call_args.kwargs["ephemeral"], True
        )

        interaction.user.id = 456
        interaction.response.launch_activity = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        await self._pick_music(select, interaction)
        interaction.response.launch_activity.assert_awaited_once()

        interaction.response.launch_activity = AsyncMock(
            side_effect=discord.NotFound(Mock(status=404), "Unknown interaction")
        )
        interaction.response.defer = AsyncMock(
            side_effect=discord.NotFound(Mock(status=404), "Unknown interaction")
        )
        interaction.edit_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()
        sent = AsyncMock(return_value=True)
        with patch.object(
            ProfileMusicSelect, "values", ["return_to_me"], create=True
        ), patch("bot.send_profile_music_dm", sent):
            await select.callback(interaction)
        sent.assert_awaited_once_with(interaction)
        interaction.followup.send.assert_not_awaited()

        sent = AsyncMock(return_value=False)
        with patch.object(
            ProfileMusicSelect, "values", ["return_to_me"], create=True
        ), patch("bot.send_profile_music_dm", sent):
            await select.callback(interaction)
        kwargs = interaction.followup.send.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertEqual(kwargs["file"].filename, "return_to_me.mp3")

    async def test_only_preview_owner_can_edit_preview(self) -> None:
        self.bot.is_application_owner = AsyncMock(return_value=True)
        profile_view = ProfileView(
            self.bot,
            456,
            SERVER_ID,
            preview_owner_id=123,
        )
        interaction = Mock()
        interaction.user.id = 789
        interaction.response.send_message = AsyncMock()

        await profile_view.children[0].callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(
            awaited_kwargs(interaction.response.send_message)["ephemeral"]
        )
        self.bot.is_application_owner.assert_not_called()

    async def test_edit_button_opens_five_personalized_dropdowns(self) -> None:
        profile_view = ProfileView(self.bot, 123, SERVER_ID)
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.send_message = AsyncMock()

        await profile_view.children[0].callback(interaction)

        kwargs = awaited_kwargs(interaction.response.send_message)
        self.assertFalse(kwargs["ephemeral"])
        editor = kwargs["view"]
        self.assertIsInstance(editor, ProfileEditView)
        self.assertEqual(
            [runtime_attribute(select, "placeholder") for select in editor.children],
            ["Text color", "Background", "Middle background", "Frame", "Music"],
        )
        self.assertEqual(
            [option.label for option in runtime_attribute(editor.children[1], "options")],
            [
                "Default background",
                "Cosmog",
                "Hisuian Zorua",
                "Eevee",
                "Moon Night",
                "Meadow Night",
            ],
        )
        self.assertEqual(
            [option.label for option in runtime_attribute(editor.children[2], "options")],
            ["Default middle background", "Cosmog", "Hisuian Zorua", "Eevee"],
        )
        self.assertEqual(
            [option.label for option in runtime_attribute(editor.children[3], "options")],
            ["No frame", "Mystic", "Gem", "Nightflower"],
        )
        self.assertEqual(
            runtime_attribute(editor.children[0], "options")[0].label,
            "Default text color",
        )

    def test_only_designated_profile_has_the_new_asset_choices(self) -> None:
        flower_editor = ProfileEditView(
            ProfileView(self.bot, PROFILE_FLOWER_SPRING_USER_ID, SERVER_ID)
        )
        moonlit_editor = ProfileEditView(
            ProfileView(self.bot, PROFILE_MOONLIT_USER_ID, SERVER_ID)
        )
        marshadow_editor = ProfileEditView(
            ProfileView(self.bot, PROFILE_MARSHADOW_USER_ID, SERVER_ID)
        )

        self.assertIn("Buneary", [option.label for option in runtime_attribute(flower_editor.children[1], "options")])
        self.assertIn(
            "Buneary",
            [option.label for option in runtime_attribute(flower_editor.children[2], "options")],
        )
        self.assertIn(
            "Flower Spring",
            [option.label for option in runtime_attribute(flower_editor.children[3], "options")],
        )
        self.assertNotIn(
            "Slakoth",
            [option.label for option in runtime_attribute(flower_editor.children[1], "options")],
        )
        self.assertNotIn(
            "Moonlit",
            [option.label for option in runtime_attribute(flower_editor.children[3], "options")],
        )

        self.assertIn(
            "Slakoth",
            [option.label for option in runtime_attribute(moonlit_editor.children[1], "options")],
        )
        self.assertIn(
            "Slakoth",
            [option.label for option in runtime_attribute(moonlit_editor.children[2], "options")],
        )
        self.assertIn(
            "Moonlit",
            [option.label for option in runtime_attribute(moonlit_editor.children[3], "options")],
        )
        self.assertNotIn(
            "Buneary",
            [option.label for option in runtime_attribute(moonlit_editor.children[1], "options")],
        )
        self.assertNotIn(
            "Flower Spring",
            [option.label for option in runtime_attribute(moonlit_editor.children[3], "options")],
        )
        self.assertIn(
            "Marshadow",
            [option.label for option in runtime_attribute(marshadow_editor.children[1], "options")],
        )
        self.assertIn(
            "Marshadow",
            [option.label for option in runtime_attribute(marshadow_editor.children[2], "options")],
        )
        self.assertNotIn(
            "Buneary",
            [option.label for option in runtime_attribute(marshadow_editor.children[1], "options")],
        )
        self.assertNotIn(
            "Slakoth",
            [option.label for option in runtime_attribute(marshadow_editor.children[1], "options")],
        )
        self.assertNotIn(
            "Flower Spring",
            [option.label for option in runtime_attribute(marshadow_editor.children[3], "options")],
        )
        self.assertNotIn(
            "Moonlit",
            [option.label for option in runtime_attribute(marshadow_editor.children[3], "options")],
        )
        self.assertIn(
            "Moonveil",
            [option.label for option in runtime_attribute(marshadow_editor.children[3], "options")],
        )
        ordinary_editor = ProfileEditView(ProfileView(self.bot, 123, SERVER_ID))
        self.assertNotIn(
            "Moonveil",
            [option.label for option in runtime_attribute(ordinary_editor.children[3], "options")],
        )
        self.assertNotIn(
            "Marshadow",
            [option.label for option in runtime_attribute(ordinary_editor.children[1], "options")],
        )
        self.assertNotIn(
            "Marshadow",
            [option.label for option in runtime_attribute(ordinary_editor.children[2], "options")],
        )

    async def test_dropdown_change_persists_and_refreshes_the_profile(self) -> None:
        profile_view = ProfileView(self.bot, 123, SERVER_ID)
        profile_view.message = Mock()
        profile_view.message.edit = AsyncMock()
        editor = ProfileEditView(profile_view)
        text_color_select = editor.children[0]
        set_runtime_attribute(text_color_select, "_values", ["pink"])
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.defer = AsyncMock()
        interaction.message.edit = AsyncMock()
        interaction.followup.send = AsyncMock()

        await text_color_select.callback(interaction)

        self.assertEqual(self.bot.profile_settings_for_user(123)["text_color"], "pink")
        self.assertEqual(
            load_profile_data(self.bot.profile_data_path)[0]["123"]["text_color"],
            "pink",
        )
        profile_view.message.edit.assert_awaited_once()
        interaction.message.edit.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()

    async def test_caught_pokemon_count_is_persistent_and_deduplicated(self) -> None:
        message = Mock()
        message.id = 987654
        message.guild = Mock()
        message.guild.id = SERVER_ID
        message.content = (
            "Congratulations <@123>! You caught a Level 20 Bagon! (50.54%)!"
        )
        message.embeds = []
        message.author.bot = True
        self.bot.track_profile_catch(message)
        self.bot.track_profile_catch(message)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            1,
        )
        _, profile_stats, profile_records, seen_catch_ids = load_profile_data(
            self.bot.profile_data_path
        )
        self.assertEqual(profile_stats[f"{SERVER_ID}:123"]["total"], 1)
        highest_iv = profile_records[f"{SERVER_ID}:123"]["highest_iv"]
        self.assertEqual((highest_iv.pokemon, highest_iv.iv), ("Bagon", 50.54))
        self.assertEqual(seen_catch_ids, [message.id])

    async def test_profile_backfill_counts_each_catcher_and_is_repeatable(self) -> None:
        backfill_guild_id = next(iter(SERVER_IDS - {SERVER_ID}))
        guild = Mock()
        guild.id = backfill_guild_id
        guild.me = Mock()
        guild.threads = []

        def make_catch(message_id: int, user_id: int) -> Mock:
            catch = Mock()
            catch.id = message_id
            catch.guild = guild
            catch.author.bot = True
            catch.content = (
                f"Congratulations <@{user_id}>! You caught a Level 20 Bagon! "
                "(50.54%)!"
            )
            catch.embeds = []
            catch.attachments = []
            catch.mentions = []
            return catch

        def make_history(user_id: int, count: int, first_message_id: int):
            async def history(*, limit: int | None, oldest_first: bool):
                self.assertIsNone(limit)
                self.assertTrue(oldest_first)
                for index in range(count):
                    yield make_catch(first_message_id + index, user_id)

            return history

        channels = []
        for channel_id, user_id, count, first_message_id in (
            (789, 123, 2000, 100000),
            (790, 456, 5000, 200000),
        ):
            channel = Mock()
            channel.id = channel_id
            channel.name = f"catches-{channel_id}"
            channel.permissions_for.return_value.view_channel = True
            channel.permissions_for.return_value.read_message_history = True
            channel.history = Mock(
                side_effect=make_history(user_id, count, first_message_id)
            )
            channels.append(channel)
        guild.text_channels = channels

        progress = Mock()
        progress.edit = AsyncMock()
        command = Mock()
        command.guild = guild
        command.author.guild_permissions.administrator = True
        command.content = "v!backfill"
        command.reply = AsyncMock(return_value=progress)
        command.channel.send = AsyncMock()

        await self.bot.handle_profile_backfill_command(command)
        await self.bot.handle_profile_backfill_command(command)

        self.assertEqual(
            self.bot.profile_stats_for_user(backfill_guild_id, 123)["total"],
            2000,
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(backfill_guild_id, 456)["total"],
            5000,
        )
        _, profile_stats, _, seen_catch_ids = load_profile_data(
            self.bot.profile_data_path
        )
        self.assertEqual(profile_stats[f"{backfill_guild_id}:123"]["total"], 2000)
        self.assertEqual(profile_stats[f"{backfill_guild_id}:456"]["total"], 5000)
        self.assertEqual(len(seen_catch_ids), 7000)
        self.assertTrue(all(channel.history.call_count == 2 for channel in channels))
        progress_messages = [
            call.kwargs["content"]
            for call in command.channel.send.await_args_list
        ]
        self.assertIn(
            "progress: 2,000 messages scanned, 2,000 catches recorded, "
            "1 channel done.",
            progress_messages[0],
        )
        self.assertEqual(
            progress_messages[1],
            "#catches-789: scanned 2,000 messages (complete).",
        )

    async def test_profile_backfill_scans_only_the_requested_channel(self) -> None:
        guild_id = next(iter(SERVER_IDS - {SERVER_ID}))
        guild = Mock()
        guild.id = guild_id
        guild.me = Mock()
        guild.threads = []

        def make_catch() -> Mock:
            catch = Mock()
            catch.id = 400001
            catch.guild = guild
            catch.author.id = self.bot.config.poketwo_bot_id
            catch.author.bot = True
            catch.content = (
                "Congratulations <@123>! You caught a Level 20 Bagon! "
                "(50.54%)!"
            )
            catch.embeds = []
            catch.attachments = []
            catch.mentions = []
            return catch

        def make_box_shiny() -> Mock:
            box_shiny = Mock()
            box_shiny.id = 400002
            box_shiny.guild = guild
            box_shiny.author.id = self.bot.config.poketwo_bot_id
            box_shiny.author.bot = True
            box_shiny.content = ""
            box_shiny.embeds = [
                discord.Embed(
                    title="You open 1 Eclipse Chest...",
                    description="• ✨ Level 11 Bronzor (84.95%)",
                )
            ]
            box_shiny.reference.resolved.author.id = 123
            box_shiny.reference.resolved.author.bot = False
            return box_shiny

        def make_channel(channel_id: int) -> Mock:
            channel = Mock()
            channel.id = channel_id
            channel.name = f"catches-{channel_id}"
            channel.permissions_for.return_value.view_channel = True
            channel.permissions_for.return_value.read_message_history = True

            async def history(*, limit: int | None, oldest_first: bool):
                self.assertIsNone(limit)
                self.assertTrue(oldest_first)
                yield make_catch()
                yield make_box_shiny()

            channel.history = Mock(side_effect=history)
            return channel

        selected_channel = make_channel(789)
        other_channel = make_channel(790)
        guild.text_channels = [selected_channel, other_channel]
        guild.categories = []
        progress = Mock()
        progress.edit = AsyncMock()
        command = Mock()
        command.guild = guild
        command.author.guild_permissions.administrator = True
        command.content = "v!backfill <#789>"
        command.reply = AsyncMock(return_value=progress)
        command.channel.send = AsyncMock()

        await self.bot.handle_profile_backfill_command(command)
        await self.bot.handle_profile_backfill_command(command)

        self.assertEqual(selected_channel.history.call_count, 2)
        other_channel.history.assert_not_called()
        self.assertEqual(
            self.bot.profile_stats_for_user(guild_id, 123)["total"],
            1,
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(guild_id, 123)["box_shiny"],
            1,
        )

    async def test_profile_backfill_category_only_scans_its_channels(self) -> None:
        guild = Mock()
        guild.id = next(iter(SERVER_IDS - {SERVER_ID}))
        guild.me = Mock()
        guild.threads = []
        category = Mock()
        category.id = 555
        category.name = "catches"
        guild.categories = [category]

        def make_channel(channel_id: int, category_id: int) -> Mock:
            channel = Mock()
            channel.id = channel_id
            channel.name = f"c-{channel_id}"
            channel.category_id = category_id
            channel.permissions_for.return_value.view_channel = True
            channel.permissions_for.return_value.read_message_history = True

            async def history(*, limit: int | None, oldest_first: bool):
                return
                yield

            channel.history = Mock(side_effect=history)
            return channel

        inside = [make_channel(1, 555), make_channel(2, 555)]
        outside = make_channel(3, 999)
        guild.text_channels = [*inside, outside]
        progress = Mock()
        progress.edit = AsyncMock()
        command = Mock()
        command.guild = guild
        command.author.guild_permissions.administrator = True
        command.content = "v!backfill 555"
        command.reply = AsyncMock(return_value=progress)
        command.channel.send = AsyncMock()

        await self.bot.handle_profile_backfill_command(command)

        for channel in inside:
            channel.history.assert_called_once()
        outside.history.assert_not_called()

    async def test_profile_backfill_continue_starts_at_channel_and_goes_down(
        self,
    ) -> None:
        guild = Mock()
        guild.id = next(iter(SERVER_IDS - {SERVER_ID}))
        guild.me = Mock()
        guild.threads = []

        def make_channel(channel_id: int) -> Mock:
            channel = Mock(spec=discord.TextChannel)
            channel.id = channel_id
            channel.name = f"c-{channel_id}"
            channel.permissions_for.return_value.view_channel = True
            channel.permissions_for.return_value.read_message_history = True

            async def history(*, limit: int | None, oldest_first: bool):
                return
                yield

            channel.history = Mock(side_effect=history)
            return channel

        channels = [make_channel(index) for index in range(1, 5)]
        guild.text_channels = channels
        guild.by_category.return_value = [
            (None, channels[:1]),
            (Mock(), channels[1:3]),
            (Mock(), channels[3:]),
        ]
        progress = Mock()
        progress.edit = AsyncMock()
        command = Mock()
        command.guild = guild
        command.author.guild_permissions.administrator = True
        command.content = "v!backfill continue <#2>"
        command.reply = AsyncMock(return_value=progress)
        command.channel.send = AsyncMock()

        await self.bot.handle_profile_backfill_command(command)

        channels[0].history.assert_not_called()
        for channel in channels[1:]:
            channel.history.assert_called_once()

    async def test_profile_backfill_stop_saves_partial_results(self) -> None:
        guild = Mock()
        guild.id = SERVER_ID
        guild.me = Mock()
        guild.threads = []

        def make_catch(message_id: int) -> Mock:
            catch = Mock()
            catch.id = message_id
            catch.guild = guild
            catch.author.bot = True
            catch.content = (
                "Congratulations <@123>! You caught a Level 20 Bagon! "
                "(50.54%)!"
            )
            catch.embeds = []
            catch.attachments = []
            catch.mentions = []
            return catch

        progress = Mock()
        progress.edit = AsyncMock()
        start_command = Mock()
        start_command.guild = guild
        start_command.author.guild_permissions.administrator = True
        start_command.content = "v!backfill"
        start_command.reply = AsyncMock(return_value=progress)
        start_command.channel.send = AsyncMock()
        stop_command = Mock()
        stop_command.guild = guild
        stop_command.author.guild_permissions.administrator = True
        stop_command.content = "v!backfill stop"
        stop_command.reply = AsyncMock()

        channel = Mock()
        channel.name = "catches"
        channel.permissions_for.return_value.view_channel = True
        channel.permissions_for.return_value.read_message_history = True

        async def history(*, limit: int | None, oldest_first: bool):
            self.assertIsNone(limit)
            self.assertTrue(oldest_first)
            yield make_catch(100000)
            await self.bot.handle_profile_backfill_command(stop_command)
            yield make_catch(100001)

        channel.history = Mock(side_effect=history)
        guild.text_channels = [channel]

        await self.bot.handle_profile_backfill_command(start_command)

        stop_command.reply.assert_awaited_once()
        self.assertIn("stop requested", stop_command.reply.await_args.args[0])
        self.assertIn(
            "Backfill stopped: scanned 1 messages",
            awaited_kwargs(progress.edit)["content"],
        )
        progress_messages = [
            call.kwargs["content"]
            for call in start_command.channel.send.await_args_list
        ]
        self.assertIn(
            "progress: 1 messages scanned, 1 catches recorded, "
            "0 channels done.",
            progress_messages[0],
        )
        self.assertEqual(
            progress_messages[1],
            "#catches: scanned 1 messages (stopped).",
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            1,
        )
        _, profile_stats, _, seen_catch_ids = load_profile_data(
            self.bot.profile_data_path
        )
        self.assertEqual(profile_stats[f"{SERVER_ID}:123"]["total"], 1)
        self.assertEqual(seen_catch_ids, [100000])
        self.assertNotIn(SERVER_ID, self.bot.profile_backfills_in_progress)
        self.assertNotIn(SERVER_ID, self.bot.profile_backfill_stop_requests)

    async def test_profile_backfill_acknowledges_before_permission_checks(self) -> None:
        guild = Mock()
        guild.id = SERVER_ID
        guild.me = Mock()
        guild.threads = []
        progress = Mock()
        progress.edit = AsyncMock()
        command = Mock()
        command.guild = guild
        command.author.guild_permissions.administrator = True
        command.content = "v!backfill"
        command.reply = AsyncMock(return_value=progress)
        command.channel.send = AsyncMock()

        channel = Mock()
        channel.name = "catches"

        def permissions_for(member):
            command.reply.assert_awaited_once()
            permissions = Mock()
            permissions.view_channel = True
            permissions.read_message_history = True
            return permissions

        async def history(*, limit: int | None, oldest_first: bool):
            self.assertIsNone(limit)
            self.assertTrue(oldest_first)
            if False:
                yield Mock()

        channel.permissions_for = Mock(side_effect=permissions_for)
        channel.history = Mock(side_effect=history)
        guild.text_channels = [channel]

        await self.bot.handle_profile_backfill_command(command)

        self.assertIn(
            "Preparing profile backfill",
            command.reply.await_args.args[0],
        )
        channel.permissions_for.assert_called_once_with(guild.me)

    async def test_profile_backfill_requires_administrator(self) -> None:
        guild = Mock()
        guild.id = SERVER_ID
        command = Mock()
        command.guild = guild
        command.author.guild_permissions.administrator = False
        command.content = "v!backfill"
        command.reply = AsyncMock()

        await self.bot.handle_profile_backfill_command(command)

        command.reply.assert_awaited_once()
        self.assertIn(
            "Only server administrators",
            command.reply.await_args.args[0],
        )

    async def test_profile_backfill_command_is_dispatched(self) -> None:
        self.bot.org_rpc = None
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.daycare.handle_message = AsyncMock(return_value=False)
        self.bot.handle_profile_backfill_command = AsyncMock()

        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.guild.id = SERVER_ID
        message.channel.id = 789
        message.channel.guild.id = SERVER_ID
        message.content = "v!backfill"
        message.embeds = []
        message.attachments = []
        message.webhook_id = None
        message.application_id = None

        await self.bot.on_message(message)

        self.bot.handle_profile_backfill_command.assert_awaited_once_with(message)
        self.bot.handle_profile_backfill_command.reset_mock()
        message.content = "v!backfill stop"

        await self.bot.on_message(message)

        self.bot.handle_profile_backfill_command.assert_awaited_once_with(message)
        self.bot.handle_profile_backfill_command.reset_mock()
        message.content = "v!backfill <#789>"

        await self.bot.on_message(message)

        self.bot.handle_profile_backfill_command.assert_awaited_once_with(message)

    async def test_each_application_webhook_catch_increments_total(self) -> None:
        self.bot.handle_catch_starboard = AsyncMock()
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.daycare.handle_message = AsyncMock(return_value=False)

        catches = (
            (987655, "Gliscor", "", False),
            (987656, "Unknownmon", "˚", True),
        )
        for message_id, pokemon, suffix, display_name_mention in catches:
            message = Mock()
            message.id = message_id
            message.author.bot = False
            message.author.id = 456
            message.guild.id = SERVER_ID
            message.channel.guild.id = SERVER_ID
            catcher = "@Trainer" if display_name_mention else "<@123>"
            message.content = (
                f"Congratulations {catcher}{suffix}! You caught a Level 36 {pokemon} "
                "♂ (53.23%)!"
            )
            message.mentions = [Mock(id=123)] if display_name_mention else []
            message.embeds = []
            message.webhook_id = 789
            message.application_id = 789
            await self.bot.on_message(message)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            2,
        )
        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            (records["highest_iv"].pokemon, records["highest_iv"].iv),
            ("Gliscor", 53.23),
        )
        self.assertEqual(
            (records["lowest_iv"].pokemon, records["lowest_iv"].iv),
            ("Gliscor", 53.23),
        )

    def test_iv_records_track_extrema_and_enrich_edited_catches(self) -> None:
        message = Mock()
        message.id = 987660
        message.guild.id = SERVER_ID
        message.embeds = []
        message.content = (
            "Congratulations <@123>! You caught a Level 40 Rolycoly!"
        )
        self.bot.track_profile_catch(message)

        message.content = (
            "Congratulations <@123>! You caught a Level 40 "
            "Rolycoly![:male:](70.43%)!"
        )
        self.bot.track_profile_catch(message)
        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            (
                records["highest_iv"].level,
                records["highest_iv"].pokemon,
                records["highest_iv"].gender,
                records["highest_iv"].iv,
            ),
            ("40", "Rolycoly", "Male", 70.43),
        )
        self.assertEqual(
            (
                records["lowest_iv"].level,
                records["lowest_iv"].pokemon,
                records["lowest_iv"].gender,
                records["lowest_iv"].iv,
            ),
            ("40", "Rolycoly", "Male", 70.43),
        )

        catches = (
            (987661, "Bramblin", 56.45, "female"),
            (987662, "Pikachu", 75.0, "male"),
            (987663, "Eevee", 50.0, "female"),
        )
        for message_id, pokemon, iv, gender in catches:
            message = Mock()
            message.id = message_id
            message.guild.id = SERVER_ID
            message.embeds = []
            message.content = (
                f"Congratulations <@123>! You caught a Level 25 "
                f"{pokemon}![:{gender}:]({iv:.2f}%)!"
            )
            self.bot.track_profile_catch(message)

        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            (
                records["highest_iv"].level,
                records["highest_iv"].pokemon,
                records["highest_iv"].gender,
                records["highest_iv"].iv,
            ),
            ("25", "Pikachu", "Male", 75.0),
        )
        self.assertEqual(
            (
                records["lowest_iv"].level,
                records["lowest_iv"].pokemon,
                records["lowest_iv"].gender,
                records["lowest_iv"].iv,
            ),
            ("25", "Eevee", "Female", 50.0),
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            4,
        )

    def test_total_uses_catch_announcement_prefix_not_spawn_or_species_parse(
        self,
    ) -> None:
        catch = Mock()
        catch.id = 987657
        catch.guild.id = SERVER_ID
        catch.author.bot = True
        catch.content = "Congratulations <@123>˚! You caught a Level 7 Unknownmon!"
        catch.embeds = []
        spawn = Mock()
        spawn.id = 987658
        spawn.guild.id = SERVER_ID
        spawn.author.bot = True
        spawn.content = "A wild Treecko has appeared!"
        spawn.embeds = []

        self.bot.track_profile_catch(catch)
        self.bot.track_profile_catch(spawn)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123)["total"],
            1,
        )

    def test_catch_categories_are_counted_separately_in_enabled_servers(self) -> None:
        second_server_id = next(iter(SERVER_IDS - {SERVER_ID}))
        catch_messages = (
            (
                1001,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 20 Bagon! "
                "(95.00%)! These colors seem unusual... ✨\n"
                "Woah! It seems that this Pokémon has the Gigantamax Factor...",
            ),
            (
                1002,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 4 Eevee! (9.99%)!",
            ),
            (
                1003,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 1 Missingno!",
            ),
            (
                1005,
                SERVER_ID,
                "Congratulations <@123>! You caught a Level 10 Pikachu! "
                "(45.00%)! These colors seem unusual... ✨",
            ),
            (
                1004,
                second_server_id,
                "Congratulations <@123>! You caught a Level 20 Bagon! (99.00%)!",
            ),
            (
                1006,
                SERVER_ID + 1,
                "Congratulations <@123>! You caught a Level 20 Bagon! (99.00%)!",
            ),
        )
        for message_id, guild_id, content in catch_messages:
            with self.subTest(message_id=message_id):
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.content = content
                message.embeds = []
                self.bot.track_profile_catch(message)

        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID, 123),
            {
                "total": 4,
                "shiny": 2,
                "box_shiny": 0,
                "low_iv": 1,
                "high_iv": 1,
                "gmax": 1,
                "missingno": 1,
            },
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(second_server_id, 123),
            {
                "total": 1,
                "shiny": 0,
                "box_shiny": 0,
                "low_iv": 0,
                "high_iv": 1,
                "gmax": 0,
                "missingno": 0,
            },
        )
        self.assertEqual(
            self.bot.profile_stats_for_user(SERVER_ID + 1, 123)["total"],
            0,
        )
        records = self.bot.profile_records_for_user(SERVER_ID, 123)
        self.assertEqual(
            {
                name: (record.level, record.pokemon, record.gender, record.iv)
                for name, record in records.items()
            },
            {
                "highest_iv": ("20", "Gigantamax Bagon", None, 95.0),
                "lowest_iv": ("4", "Eevee", None, 9.99),
                "highest_shiny_iv": ("20", "Gigantamax Bagon", None, 95.0),
                "lowest_shiny_iv": ("10", "Pikachu", None, 45.0),
            },
        )
        _, _, profile_records, _ = load_profile_data(self.bot.profile_data_path)
        self.assertEqual(profile_records[f"{SERVER_ID}:123"], records)

    async def test_profile_counts_each_shiny_pokemon_from_a_chest_once(self) -> None:
        message = Mock()
        message.id = 9001
        message.guild.id = SERVER_ID
        message.author.id = self.bot.config.poketwo_bot_id
        message.reference.resolved.author.id = 123
        message.reference.resolved.author.bot = False
        message.content = ""
        message.embeds = [
            discord.Embed(
                title="You open 5 Eclipse Chests...",
                description=(
                    "Eclipse Chest\n"
                    "• ✨ Level 11 Bronzor ♀ (84.95%)\n"
                    "• Level 21 Blooming Sunflora ♀ (34.95%)\n"
                    "• 🌟 Level 18 Gardevoir ♂ (70.00%)"
                ),
            )
        ]

        await self.bot.track_profile_box_shiny(message)
        await self.bot.track_profile_box_shiny(message)

        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        self.assertEqual(stats["box_shiny"], 2)
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["shiny"], 0)
        _, saved_stats, _, seen_message_ids = load_profile_data(
            self.bot.profile_data_path
        )
        self.assertEqual(saved_stats[f"{SERVER_ID}:123"]["box_shiny"], 2)
        self.assertEqual(seen_message_ids, [message.id])

    def test_profile_card_keeps_default_backgrounds(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        image = Image.open(render_profile_image(settings, stats))
        self.assertEqual(image.size, (1400, 825))
        self.assertEqual(image.getpixel((700, 400)), (255, 255, 255))
        self.assertEqual(image.getpixel((100, 800)), (41, 42, 47))
        self.assertEqual(image.getpixel((1300, 800)), (41, 42, 47))
        self.assertNotEqual(image.getpixel((81, 375)), (41, 42, 47))
        self.assertEqual(image.getpixel((380, 375)), (41, 42, 47))

    def test_profile_card_uses_selected_cosmog_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["middle_background"] = "cosmog"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(Path(__file__).with_name("middle background") / "Cosmog.png") as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        expected = Image.blend(
            expected,
            Image.new(
                "RGB",
                expected.size,
                profile_background_tint(
                    Image.new("RGB", (1400, 825), "#292A2F")
                ),
            ),
            0.4,
        )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_middle_background_tint_matches_selected_outer_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "cosmog"
        settings["middle_background"] = "cosmog"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(Path(__file__).with_name("background") / "cosmog.png") as source:
            outer_background = ImageOps.fit(
                source.convert("RGB"),
                (1400, 825),
            ).filter(ImageFilter.GaussianBlur(radius=12))
        tint = profile_background_tint(outer_background)
        with Image.open(
            Path(__file__).with_name("middle background") / "Cosmog.png"
        ) as source:
            expected = Image.blend(
                ImageOps.fit(source.convert("RGB"), (520, 825)),
                Image.new("RGB", (520, 825), tint),
                0.4,
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_uses_selected_hiszorua_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["middle_background"] = "hiszorua"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("middle background") / "hiszorua.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        expected = Image.blend(
            expected,
            Image.new(
                "RGB",
                expected.size,
                profile_background_tint(
                    Image.new("RGB", (1400, 825), "#292A2F")
                ),
            ),
            0.4,
        )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_uses_selected_eevee_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["middle_background"] = "eevee"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("middle background") / "eevee.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        expected = Image.blend(
            expected,
            Image.new(
                "RGB",
                expected.size,
                profile_background_tint(
                    Image.new("RGB", (1400, 825), "#292A2F")
                ),
            ),
            0.4,
        )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_uses_selected_buneary_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["middle_background"] = "buneary"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("middle background") / "Buneary.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        expected = Image.blend(
            expected,
            Image.new(
                "RGB",
                expected.size,
                profile_background_tint(
                    Image.new("RGB", (1400, 825), "#292A2F")
                ),
            ),
            0.4,
        )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_uses_selected_slakoth_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(PROFILE_MOONLIT_USER_ID)
        settings["middle_background"] = "slakoth"
        stats = self.bot.profile_stats_for_user(SERVER_ID, PROFILE_MOONLIT_USER_ID)

        with Image.open(
            Path(__file__).with_name("middle background") / "Slakoth.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        expected = Image.blend(
            expected,
            Image.new(
                "RGB",
                expected.size,
                profile_background_tint(
                    Image.new("RGB", (1400, 825), "#292A2F")
                ),
            ),
            0.4,
        )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_uses_selected_marshadow_middle_background(self) -> None:
        settings = self.bot.profile_settings_for_user(PROFILE_MARSHADOW_USER_ID)
        settings["middle_background"] = "marshadow"
        stats = self.bot.profile_stats_for_user(SERVER_ID, PROFILE_MARSHADOW_USER_ID)

        with Image.open(
            Path(__file__).with_name("middle background") / "Marshadow.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (520, 825))
        expected = Image.blend(
            expected,
            Image.new(
                "RGB",
                expected.size,
                profile_background_tint(
                    Image.new("RGB", (1400, 825), "#292A2F")
                ),
            ),
            0.4,
        )
        with Image.open(render_profile_image(settings, stats)) as image:
            actual = image.crop((430, 0, 950, 825))

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_uses_blurred_background_behind_text(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "cosmog"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(Path(__file__).with_name("background") / "cosmog.png") as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        settings["text_color"] = "white"
        with Image.open(render_profile_image(settings, stats)) as white_text:
            actual_background_pixel = white_text.getpixel((400, 800))
            self.assertEqual(actual_background_pixel, expected.getpixel((400, 800)))
            self.assertEqual(white_text.getpixel((700, 400)), (255, 255, 255))
            white_text_crop = white_text.crop((64, 245, 430, 700)).tobytes()

        settings["text_color"] = "black"
        with Image.open(render_profile_image(settings, stats)) as black_text:
            self.assertNotEqual(
                white_text_crop,
                black_text.crop((64, 245, 430, 700)).tobytes(),
            )

    def test_profile_card_uses_blurred_hiszorua_background_behind_text(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "hiszorua"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("background") / "hiszorua.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(image.getpixel((400, 800)), expected.getpixel((400, 800)))

    def test_profile_card_uses_blurred_moonnight_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "moonnight"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("background") / "moonnight.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(image.getpixel((400, 800)), expected.getpixel((400, 800)))

    def test_profile_card_uses_blurred_meadownight_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "meadownight"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("background") / "meadownight.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(image.getpixel((400, 800)), expected.getpixel((400, 800)))

    def test_profile_card_uses_blurred_rotated_eevee_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "eevee"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("background") / "eevee.png"
        ) as source:
            expected = source.convert("RGB").transpose(
                Image.Transpose.ROTATE_90
            ).resize((1400, 825), Image.Resampling.LANCZOS).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(
                image.crop((300, 700, 430, 825)).tobytes(),
                expected.crop((300, 700, 430, 825)).tobytes(),
            )

    def test_profile_card_uses_blurred_buneary_background(self) -> None:
        settings = self.bot.profile_settings_for_user(123)
        settings["background"] = "buneary"
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(
            Path(__file__).with_name("background") / "buneary.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(
                image.crop((300, 700, 430, 825)).tobytes(),
                expected.crop((300, 700, 430, 825)).tobytes(),
            )

    def test_profile_card_uses_blurred_slakoth_background(self) -> None:
        settings = self.bot.profile_settings_for_user(PROFILE_MOONLIT_USER_ID)
        settings["background"] = "slakoth"
        stats = self.bot.profile_stats_for_user(SERVER_ID, PROFILE_MOONLIT_USER_ID)

        with Image.open(
            Path(__file__).with_name("background") / "slakoth.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(
                image.crop((300, 700, 430, 825)).tobytes(),
                expected.crop((300, 700, 430, 825)).tobytes(),
            )

    def test_profile_card_uses_blurred_marshadow_background(self) -> None:
        settings = self.bot.profile_settings_for_user(PROFILE_MARSHADOW_USER_ID)
        settings["background"] = "marshadow"
        stats = self.bot.profile_stats_for_user(SERVER_ID, PROFILE_MARSHADOW_USER_ID)

        with Image.open(
            Path(__file__).with_name("background") / "marshadow.png"
        ) as source:
            expected = ImageOps.fit(source.convert("RGB"), (1400, 825)).filter(
                ImageFilter.GaussianBlur(radius=12)
            )
        with Image.open(render_profile_image(settings, stats)) as image:
            self.assertEqual(
                image.crop((300, 700, 430, 825)).tobytes(),
                expected.crop((300, 700, 430, 825)).tobytes(),
            )

    def test_profile_card_renders_selected_mystic_frame_over_contents(self) -> None:
        self.bot.set_profile_setting(123, "frame", "mystic")
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        unframed_settings = {**settings, "frame": "none"}

        with Image.open(render_profile_image(unframed_settings, stats)) as unframed:
            base = unframed.convert("RGB")
        with Image.open(Path(__file__).with_name("Frames") / "mystic.png") as source:
            frame = source.convert("RGBA").resize(
                PROFILE_FRAME_CANVAS_SIZE,
                Image.Resampling.LANCZOS,
            )
        frame.putalpha(
            frame.getchannel("A").point(
                profile_frame_alpha
            )
        )
        expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        profile_scale = PROFILE_CARD_SCALES["mystic"]
        base = base.resize(
            (round(1400 * profile_scale), round(825 * profile_scale)),
            Image.Resampling.LANCZOS,
        )
        profile_position = (
            (frame.width - base.width) // 2,
            (frame.height - base.height) // 2,
        )
        self.assertEqual(frame.size, (1467, 868))
        self.assertEqual(base.size, (1400, 825))
        self.assertEqual(profile_position, (33, 21))
        profile_card = base.convert("RGBA")
        card_mask = Image.new("L", profile_card.size, 0)
        ImageDraw.Draw(card_mask).rounded_rectangle(
            (0, 0, profile_card.width - 1, profile_card.height - 1),
            radius=round(PROFILE_FRAME_CORNER_RADIUS * profile_scale),
            fill=255,
        )
        profile_card.putalpha(card_mask)
        self.assertEqual(rgba_pixel(profile_card, (0, 0))[3], 0)
        self.assertEqual(rgba_pixel(profile_card, (0, 412))[3], 255)
        expected.alpha_composite(profile_card, dest=profile_position)
        expected.alpha_composite(frame)
        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(base.size, (1400, 825))
            self.assertEqual(actual.size, frame.size)
            self.assertEqual(actual.mode, "RGBA")
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_renders_selected_gem_frame_over_contents(self) -> None:
        self.bot.set_profile_setting(123, "frame", "gem")
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        unframed_settings = {**settings, "frame": "none"}

        with Image.open(render_profile_image(unframed_settings, stats)) as unframed:
            base = unframed.convert("RGB")
        with Image.open(Path(__file__).with_name("Frames") / "gem.png") as source:
            scale = PROFILE_FRAME_SCALES["gem"]
            scaled_size = (
                round(PROFILE_FRAME_CANVAS_SIZE[0] * scale),
                round(PROFILE_FRAME_CANVAS_SIZE[1] * scale),
            )
            frame = source.convert("RGBA").resize(
                scaled_size,
                Image.Resampling.LANCZOS,
            )
        frame.putalpha(
            frame.getchannel("A").point(
                profile_frame_alpha
            )
        )
        expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        profile_scale = PROFILE_CARD_SCALES["gem"]
        base = base.resize(
            (round(1400 * profile_scale), round(825 * profile_scale)),
            Image.Resampling.LANCZOS,
        )
        profile_position = (
            (frame.width - base.width) // 2,
            (frame.height - base.height) // 2,
        )
        self.assertEqual(frame.size, (1496, 885))
        self.assertEqual(base.size, (1400, 825))
        self.assertEqual(profile_position, (48, 30))
        profile_card = base.convert("RGBA")
        card_mask = Image.new("L", profile_card.size, 0)
        ImageDraw.Draw(card_mask).rounded_rectangle(
            (0, 0, profile_card.width - 1, profile_card.height - 1),
            radius=round(PROFILE_FRAME_CORNER_RADIUS * profile_scale),
            fill=255,
        )
        profile_card.putalpha(card_mask)
        expected.alpha_composite(profile_card, dest=profile_position)
        expected.alpha_composite(frame)
        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(base.size, (1400, 825))
            self.assertEqual(actual.size, frame.size)
            self.assertEqual(actual.mode, "RGBA")
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_renders_selected_nightflower_frame_over_contents(self) -> None:
        self.bot.set_profile_setting(123, "frame", "nightflower")
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)

        with Image.open(render_profile_image({**settings, "frame": "none"}, stats)) as unframed:
            base = unframed.convert("RGB")
        with Image.open(
            Path(__file__).with_name("Frames") / "nightflower.png"
        ) as source:
            left, top, right, bottom = PROFILE_FRAME_OPENINGS["nightflower"]
            scale_x = base.width / (right - left)
            scale_y = base.height / (bottom - top)
            frame = source.convert("RGBA").resize(
                (
                    round(source.width * scale_x),
                    round(source.height * scale_y),
                ),
                Image.Resampling.LANCZOS,
            )
        frame.putalpha(
            frame.getchannel("A").point(
                profile_frame_alpha
            )
        )
        expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        profile_position = (round(left * scale_x), round(top * scale_y))
        self.assertEqual(frame.size, (1539, 1020))
        self.assertEqual(base.size, (1400, 825))
        self.assertEqual(profile_position, (68, 91))
        profile_card = base.convert("RGBA")
        card_mask = Image.new("L", profile_card.size, 0)
        ImageDraw.Draw(card_mask).rounded_rectangle(
            (0, 0, profile_card.width - 1, profile_card.height - 1),
            radius=PROFILE_FRAME_CORNER_RADIUS,
            fill=255,
        )
        profile_card.putalpha(card_mask)
        expected.alpha_composite(profile_card, dest=profile_position)
        expected.alpha_composite(frame)

        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(actual.size, frame.size)
            self.assertEqual(actual.mode, "RGBA")
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_renders_selected_flower_spring_frame(self) -> None:
        self.bot.set_profile_setting(
            PROFILE_FLOWER_SPRING_USER_ID,
            "frame",
            "flowerspring",
        )
        settings = self.bot.profile_settings_for_user(PROFILE_FLOWER_SPRING_USER_ID)
        stats = self.bot.profile_stats_for_user(
            SERVER_ID,
            PROFILE_FLOWER_SPRING_USER_ID,
        )

        with Image.open(
            render_profile_image({**settings, "frame": "none"}, stats)
        ) as unframed:
            base = unframed.convert("RGB")
        with Image.open(
            Path(__file__).with_name("Frames") / "flowerspring.png"
        ) as source:
            left, top, right, bottom = PROFILE_FRAME_OPENINGS["flowerspring"]
            scale_x = base.width / (right - left)
            scale_y = base.height / (bottom - top)
            frame = source.convert("RGBA").resize(
                (
                    round(source.width * scale_x),
                    round(source.height * scale_y),
                ),
                Image.Resampling.LANCZOS,
            )
        frame.putalpha(
            frame.getchannel("A").point(
                profile_frame_alpha
            )
        )
        expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        profile_position = (round(left * scale_x), round(top * scale_y))
        self.assertEqual(frame.size, (1539, 1020))
        self.assertEqual(profile_position, (68, 98))
        profile_card = base.convert("RGBA")
        card_mask = Image.new("L", profile_card.size, 0)
        ImageDraw.Draw(card_mask).rounded_rectangle(
            (0, 0, profile_card.width - 1, profile_card.height - 1),
            radius=PROFILE_FRAME_CORNER_RADIUS,
            fill=255,
        )
        profile_card.putalpha(card_mask)
        expected.alpha_composite(profile_card, dest=profile_position)
        expected.alpha_composite(frame)

        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(actual.size, frame.size)
            self.assertEqual(actual.mode, "RGBA")
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_renders_amethyst_frame_without_warping(self) -> None:
        settings = {**self.bot.profile_settings_for_user(123), "frame": "amethyst"}
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        with Image.open(
            render_profile_image({**settings, "frame": "none"}, stats)
        ) as unframed:
            base = unframed.convert("RGB")
        with Image.open(
            Path(__file__).with_name("Frames") / "amethyst.png"
        ) as source:
            left, top, right, bottom = PROFILE_FRAME_OPENINGS["amethyst"]
            frame_scale = min(
                base.width / (right - left),
                base.height / (bottom - top),
            )
            frame = source.convert("RGBA").resize(
                (
                    round(source.width * frame_scale),
                    round(source.height * frame_scale),
                ),
                Image.Resampling.LANCZOS,
            )
        opening_width = round((right - left) * frame_scale)
        opening_height = round((bottom - top) * frame_scale)
        profile_card = base.convert("RGBA").resize(
            (opening_width, opening_height),
            Image.Resampling.LANCZOS,
        )
        frame.putalpha(
            frame.getchannel("A").point(profile_frame_alpha)
        )
        expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        profile_position = (
            round(left * frame_scale),
            round(top * frame_scale),
        )
        self.assertEqual(profile_card.size, (opening_width, opening_height))
        expected.alpha_composite(profile_card, dest=profile_position)
        expected.alpha_composite(frame)

        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(actual.size, frame.size)
            self.assertAlmostEqual(
                actual.width / actual.height,
                1115 / 768,
                places=3,
            )
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_shop_frames_fit_native_profile_without_warping(self) -> None:
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        frame_sizes: dict[str, tuple[int, int]] = {}
        card_positions: dict[str, tuple[int, int]] = {}
        for frame_key in ("celestial", "ocean"):
            for backgrounds in (
                {},
                {"background": "cosmog", "middle_background": "cosmog"},
            ):
                with self.subTest(frame=frame_key, backgrounds=backgrounds):
                    settings = {
                        **self.bot.profile_settings_for_user(123),
                        **backgrounds,
                        "frame": frame_key,
                    }
                    with Image.open(
                        render_profile_image(
                            {**settings, "frame": "none"}, stats, username="Jade"
                        )
                    ) as unframed:
                        card = unframed.convert("RGBA")
                    self.assertEqual(card.size, (1400, 825))
                    with Image.open(
                        Path(__file__).with_name("Frames") / f"{frame_key}.png"
                    ) as source:
                        left, top, right, bottom = PROFILE_FRAME_OPENINGS[frame_key]
                        scale = card.width / (right - left)
                        self.assertLessEqual(
                            abs((bottom - top) * scale - card.height), 1
                        )
                        frame = source.convert("RGBA").resize(
                            (round(source.width * scale), round(source.height * scale)),
                            Image.Resampling.LANCZOS,
                        )
                        self.assertAlmostEqual(
                            frame.width / source.width,
                            frame.height / source.height,
                            delta=0.001,
                        )
                    x, y = round(left * scale), round(top * scale)
                    frame_sizes[frame_key] = frame.size
                    card_positions[frame_key] = (x, y)
                    expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
                    expected.alpha_composite(card, (x, y))
                    expected.alpha_composite(frame)
                    with Image.open(
                        render_profile_image(settings, stats, username="Jade")
                    ) as actual:
                        self.assertEqual(actual.size, frame.size)
                        self.assertEqual(actual.tobytes(), expected.tobytes())
                        self.assertEqual(
                            actual.getchannel("A").crop(
                                (x, y, x + card.width, y + card.height)
                            ).getextrema(),
                            (255, 255),
                        )
                        for bounds in (
                            (64, 245, 425, 610),
                            (980, 245, 1290, 745),
                            (980, 760, 1260, 790),
                        ):
                            a, b, c, d = bounds
                            self.assertLessEqual(
                                frame.getchannel("A").crop(
                                    (x + a, y + b, x + c, y + d)
                                ).getextrema()[1],
                                2,
                            )
        self.assertEqual(frame_sizes["ocean"], frame_sizes["celestial"])
        self.assertEqual(card_positions["ocean"], card_positions["celestial"])

    def test_shop_frames_use_selected_background_and_dyes(self) -> None:
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        dyes = {
            "background": {"color": "#FF00FF", "rarity": "normal"},
            "frame": {"color": "#FF88CC", "rarity": "normal"},
        }
        for frame_key in ("celestial", "ocean"):
            with self.subTest(frame=frame_key):
                settings = {
                    **self.bot.profile_settings_for_user(123),
                    "background": "cosmog",
                    "middle_background": "cosmog",
                    "frame": frame_key,
                }
                left, top, right, _ = PROFILE_FRAME_OPENINGS[frame_key]
                scale = 1400 / (right - left)
                x, y = round(left * scale), round(top * scale)
                with Image.open(render_profile_image(settings, stats)) as original:
                    normal = original.convert("RGBA")
                with Image.open(render_profile_image(settings, stats, dyes=dyes)) as dyed:
                    self.assertEqual(dyed.size, normal.size)
                    self.assertEqual(
                        dyed.getchannel("A").crop((x, y, x + 1400, y + 825)).getextrema(),
                        (255, 255),
                    )
                    self.assertNotEqual(
                        dyed.getpixel((x + 220, y + 300)),
                        normal.getpixel((x + 220, y + 300)),
                    )
                    self.assertNotEqual(
                        dyed.getpixel((round(left * scale) - 5, y + 300)),
                        normal.getpixel((round(left * scale) - 5, y + 300)),
                    )

    def test_profile_card_renders_selected_moonlit_frame_at_reference_size(self) -> None:
        self.bot.set_profile_setting(PROFILE_MOONLIT_USER_ID, "frame", "moonlit")
        settings = self.bot.profile_settings_for_user(PROFILE_MOONLIT_USER_ID)
        stats = self.bot.profile_stats_for_user(SERVER_ID, PROFILE_MOONLIT_USER_ID)

        with Image.open(
            render_profile_image({**settings, "frame": "none"}, stats)
        ) as unframed:
            base = unframed.convert("RGB")
        with Image.open(Path(__file__).with_name("Frames") / "moonlit.png") as source:
            left, top, right, bottom = PROFILE_FRAME_OPENINGS["moonlit"]
            scale_x = base.width / (right - left)
            scale_y = base.height / (bottom - top)
            frame = source.convert("RGBA").resize(
                (
                    round(source.width * scale_x),
                    round(source.height * scale_y),
                ),
                Image.Resampling.LANCZOS,
            )
        frame.putalpha(
            frame.getchannel("A").point(
                profile_frame_alpha
            )
        )
        expected = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        profile_scale = PROFILE_CARD_SCALES["moonlit"]
        profile_position = (
            round(left * scale_x),
            round(top * scale_y),
        )
        profile_card = base.convert("RGBA").resize(
            (
                round(base.width * profile_scale),
                round(base.height * profile_scale),
            ),
            Image.Resampling.LANCZOS,
        )
        profile_position = (
            profile_position[0] - (profile_card.width - base.width) // 2,
            profile_position[1] - (profile_card.height - base.height) // 2,
        )
        self.assertEqual(frame.size, (1539, 1020))
        self.assertEqual(profile_card.size, (1512, 891))
        self.assertEqual(profile_position, (13, 58))
        card_mask = Image.new("L", profile_card.size, 0)
        ImageDraw.Draw(card_mask).rounded_rectangle(
            (0, 0, profile_card.width - 1, profile_card.height - 1),
            radius=round(PROFILE_FRAME_CORNER_RADIUS * profile_scale),
            fill=255,
        )
        profile_card.putalpha(card_mask)
        expected.alpha_composite(profile_card, dest=profile_position)
        expected.alpha_composite(frame)

        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(actual.size, (1539, 1020))
            self.assertEqual(actual.mode, "RGBA")
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_profile_card_renders_moonveil_frame_for_designated_user(self) -> None:
        self.bot.set_profile_setting(
            PROFILE_MARSHADOW_USER_ID,
            "frame",
            "moonveil",
        )
        settings = self.bot.profile_settings_for_user(PROFILE_MARSHADOW_USER_ID)
        stats = self.bot.profile_stats_for_user(SERVER_ID, PROFILE_MARSHADOW_USER_ID)
        with Image.open(
            render_profile_image({**settings, "frame": "none"}, stats)
        ) as unframed:
            base = unframed.convert("RGB")
        with Image.open(Path(__file__).with_name("Frames") / "moonveil.png") as source:
            left, top, right, bottom = PROFILE_FRAME_OPENINGS["moonveil"]
            scale_x = base.width / (right - left)
            scale_y = base.height / (bottom - top)
            self.assertAlmostEqual(scale_x, scale_y, delta=0.01)
            expected_size = (
                round(source.width * scale_x),
                round(source.height * scale_y),
            )
            card_scale = PROFILE_CARD_SCALES["moonveil"]
            expected_card_size = (
                round(base.width * card_scale),
                round(base.height * card_scale),
            )
            self.assertEqual(rgba_pixel(source, (768, 512))[3], 0)
            self.assertEqual(expected_card_size, (1540, 908))

        with Image.open(render_profile_image(settings, stats)) as actual:
            self.assertEqual(actual.size, expected_size)
            self.assertEqual(actual.mode, "RGBA")

    def test_pink_ninetales_backgrounds_are_restricted_and_rendered(self) -> None:
        owner = bot_module.PROFILE_PINK_NINETALES_USER_ID
        all_access = bot_module.PROFILE_GARDEVOIR_USER_ID
        for setting in ("background", "middle_background"):
            for user_id in (owner, all_access):
                with self.subTest(setting=setting, user_id=user_id):
                    self.assertIn(
                        "pink_ninetales",
                        self.bot.profile_choices_for_user(user_id, setting),
                    )
                    self.bot.set_profile_setting(user_id, setting, "pink_ninetales")
            self.assertNotIn(
                "pink_ninetales", self.bot.profile_choices_for_user(123, setting)
            )
            with self.assertRaises(ValueError):
                self.bot.set_profile_setting(123, setting, "pink_ninetales")

        profiles, _, _, _ = load_profile_data(self.bot.profile_data_path)
        for user_id in (owner, all_access):
            settings = profiles[str(user_id)]
            self.assertEqual(settings["background"], "pink_ninetales")
            self.assertEqual(settings["middle_background"], "pink_ninetales")
            with Image.open(
                render_profile_image(settings, dict(bot_module.PROFILE_STAT_DEFAULTS))
            ) as image:
                self.assertEqual(image.size, (1400, 825))
                self.assertNotEqual(image.getpixel((700, 500)), (255, 255, 255))

    def test_pink_ninetales_frame_access_and_profile_fit(self) -> None:
        owner = bot_module.PROFILE_PINK_NINETALES_USER_ID
        all_access = bot_module.PROFILE_GARDEVOIR_USER_ID
        for user_id in (owner, all_access):
            with self.subTest(user_id=user_id):
                self.assertIn(
                    "pink_ninetales", self.bot.profile_choices_for_user(user_id, "frame")
                )
                self.bot.set_profile_setting(user_id, "frame", "pink_ninetales")
        self.assertNotIn("pink_ninetales", self.bot.profile_choices_for_user(123, "frame"))
        with self.assertRaises(ValueError):
            self.bot.set_profile_setting(123, "frame", "pink_ninetales")

        profiles, _, _, _ = load_profile_data(self.bot.profile_data_path)
        for user_id in (owner, all_access):
            self.assertEqual(profiles[str(user_id)]["frame"], "pink_ninetales")
        settings = profiles[str(owner)]
        stats = dict(bot_module.PROFILE_STAT_DEFAULTS)
        with Image.open(render_profile_image({**settings, "frame": "none"}, stats)) as base:
            with Image.open(render_profile_image(settings, stats)) as framed:
                self.assertEqual(framed.size, (1610, 1001))
                self.assertEqual(framed.mode, "RGBA")
                # The unobstructed center preserves the full-size profile card.
                self.assertEqual(
                    framed.crop((255, 208, 1255, 808)).convert("RGB").tobytes(),
                    base.crop((150, 120, 1150, 720)).tobytes(),
                )
                with patch.dict(bot_module.PROFILE_FRAME_IMAGES, {}, clear=True):
                    with Image.open(render_profile_image(settings, stats)) as unobstructed:
                        self.assertEqual(
                            framed.crop((1085, 821, 1325, 858)).convert("RGB").tobytes(),
                            unobstructed.crop((980, 733, 1220, 770)).tobytes(),
                        )

    def test_restricted_assets_are_removed_from_other_users_on_load(self) -> None:
        flower_settings = {
            "text_color": "white",
            "background": "buneary",
            "middle_background": "buneary",
            "frame": "flowerspring",
        }
        moonlit_settings = {
            "text_color": "white",
            "background": "slakoth",
            "middle_background": "slakoth",
            "frame": "moonlit",
        }
        marshadow_settings = {
            "text_color": "white",
            "background": "marshadow",
            "middle_background": "marshadow",
            "frame": "moonveil",
        }
        save_profile_data(
            self.bot.profile_data_path,
            {
                "123": dict(flower_settings),
                "456": dict(marshadow_settings),
                str(PROFILE_FLOWER_SPRING_USER_ID): dict(flower_settings),
                str(PROFILE_MOONLIT_USER_ID): dict(moonlit_settings),
                str(PROFILE_MARSHADOW_USER_ID): dict(marshadow_settings),
            },
            {},
            {},
            [],
        )

        profiles, _, _, _ = load_profile_data(self.bot.profile_data_path)

        self.assertEqual(profiles["123"]["background"], "default")
        self.assertEqual(profiles["123"]["middle_background"], "white")
        self.assertEqual(profiles["123"]["frame"], "none")
        self.assertEqual(profiles["456"]["background"], "default")
        self.assertEqual(profiles["456"]["middle_background"], "white")
        self.assertEqual(
            profiles[str(PROFILE_FLOWER_SPRING_USER_ID)]["background"],
            "buneary",
        )
        self.assertEqual(
            profiles[str(PROFILE_FLOWER_SPRING_USER_ID)]["middle_background"],
            "buneary",
        )
        self.assertEqual(
            profiles[str(PROFILE_FLOWER_SPRING_USER_ID)]["frame"],
            "flowerspring",
        )
        self.assertEqual(
            profiles[str(PROFILE_MOONLIT_USER_ID)]["background"],
            "slakoth",
        )
        self.assertEqual(
            profiles[str(PROFILE_MOONLIT_USER_ID)]["middle_background"],
            "slakoth",
        )
        self.assertEqual(
            profiles[str(PROFILE_MOONLIT_USER_ID)]["frame"],
            "moonlit",
        )
        self.assertEqual(
            profiles[str(PROFILE_MARSHADOW_USER_ID)]["background"],
            "marshadow",
        )
        self.assertEqual(
            profiles[str(PROFILE_MARSHADOW_USER_ID)]["middle_background"],
            "marshadow",
        )
        self.assertEqual(
            profiles[str(PROFILE_MARSHADOW_USER_ID)]["frame"],
            "moonveil",
        )

    def test_other_users_cannot_save_restricted_assets(self) -> None:
        restricted_selections = (
            (123, "background", "buneary"),
            (123, "middle_background", "buneary"),
            (123, "frame", "flowerspring"),
            (123, "background", "slakoth"),
            (123, "middle_background", "slakoth"),
            (123, "frame", "moonlit"),
            (PROFILE_FLOWER_SPRING_USER_ID, "background", "slakoth"),
            (PROFILE_FLOWER_SPRING_USER_ID, "middle_background", "slakoth"),
            (PROFILE_FLOWER_SPRING_USER_ID, "frame", "moonlit"),
            (PROFILE_MOONLIT_USER_ID, "background", "buneary"),
            (PROFILE_MOONLIT_USER_ID, "middle_background", "buneary"),
            (PROFILE_MOONLIT_USER_ID, "frame", "flowerspring"),
            (123, "background", "marshadow"),
            (123, "middle_background", "marshadow"),
            (PROFILE_FLOWER_SPRING_USER_ID, "background", "marshadow"),
            (PROFILE_FLOWER_SPRING_USER_ID, "middle_background", "marshadow"),
            (PROFILE_MOONLIT_USER_ID, "background", "marshadow"),
            (PROFILE_MOONLIT_USER_ID, "middle_background", "marshadow"),
            (PROFILE_MARSHADOW_USER_ID, "background", "buneary"),
            (PROFILE_MARSHADOW_USER_ID, "middle_background", "buneary"),
            (PROFILE_MARSHADOW_USER_ID, "background", "slakoth"),
            (PROFILE_MARSHADOW_USER_ID, "middle_background", "slakoth"),
            (PROFILE_MARSHADOW_USER_ID, "frame", "flowerspring"),
            (PROFILE_MARSHADOW_USER_ID, "frame", "moonlit"),
            (123, "frame", "moonveil"),
        )
        for user_id, setting, value in restricted_selections:
            with self.subTest(user_id=user_id, setting=setting, value=value):
                with self.assertRaises(ValueError):
                    self.bot.set_profile_setting(user_id, setting, value)

        self.bot.set_profile_setting(
            PROFILE_MARSHADOW_USER_ID,
            "background",
            "marshadow",
        )
        self.bot.set_profile_setting(
            PROFILE_MARSHADOW_USER_ID,
            "middle_background",
            "marshadow",
        )
        settings = self.bot.profile_settings_for_user(PROFILE_MARSHADOW_USER_ID)
        self.assertEqual(settings["background"], "marshadow")
        self.assertEqual(settings["middle_background"], "marshadow")

    def test_profile_settings_hide_assets_reserved_for_other_users(self) -> None:
        profiles = (
            (
                123,
                "buneary",
                "buneary",
                "flowerspring",
                "default",
                "white",
                "none",
            ),
            (
                PROFILE_FLOWER_SPRING_USER_ID,
                "slakoth",
                "slakoth",
                "moonlit",
                "default",
                "white",
                "none",
            ),
            (
                PROFILE_MOONLIT_USER_ID,
                "buneary",
                "buneary",
                "flowerspring",
                "default",
                "white",
                "none",
            ),
            (
                PROFILE_FLOWER_SPRING_USER_ID,
                "buneary",
                "buneary",
                "flowerspring",
                "buneary",
                "buneary",
                "flowerspring",
            ),
            (
                PROFILE_MOONLIT_USER_ID,
                "slakoth",
                "slakoth",
                "moonlit",
                "slakoth",
                "slakoth",
                "moonlit",
            ),
            (
                PROFILE_MARSHADOW_USER_ID,
                "slakoth",
                "slakoth",
                "moonlit",
                "default",
                "white",
                "none",
            ),
            (
                PROFILE_MARSHADOW_USER_ID,
                "marshadow",
                "marshadow",
                "none",
                "marshadow",
                "marshadow",
                "none",
            ),
            (
                456,
                "marshadow",
                "marshadow",
                "none",
                "default",
                "white",
                "none",
            ),
        )
        for (
            user_id,
            background,
            middle,
            frame,
            expected_background,
            expected_middle,
            expected_frame,
        ) in profiles:
            with self.subTest(user_id=user_id, background=background, frame=frame):
                self.bot.profiles[str(user_id)] = {
                    "background": background,
                    "middle_background": middle,
                    "frame": frame,
                }
                settings = self.bot.profile_settings_for_user(user_id)
                self.assertEqual(settings["background"], expected_background)
                self.assertEqual(settings["middle_background"], expected_middle)
                self.assertEqual(settings["frame"], expected_frame)

    def test_profile_card_renders_iv_records_on_the_right(self) -> None:
        self.assertEqual(
            format_profile_iv_record(
                ProfileIvRecord(
                    pokemon="Rolycoly",
                    iv=70.43,
                    level="40",
                    gender="Male",
                )
            ),
            ("Level 40 Rolycoly", "Male | 70.43%"),
        )
        settings = self.bot.profile_settings_for_user(123)
        stats = self.bot.profile_stats_for_user(SERVER_ID, 123)
        blank = Image.open(render_profile_image(settings, stats))
        with_records = Image.open(
            render_profile_image(
                settings,
                stats,
                records={
                    "highest_iv": ProfileIvRecord(
                        pokemon="Gliscor",
                        iv=98.25,
                        level="36",
                        gender="Male",
                    )
                },
            )
        )

        self.assertNotEqual(
            blank.crop((950, 200, 1400, 800)).tobytes(),
            with_records.crop((950, 200, 1400, 800)).tobytes(),
        )

    def test_profile_stat_emojis_use_the_requested_symbols(self) -> None:
        self.assertEqual(
            {
                name: PROFILE_EMOJI_URLS[name].rsplit("/", 1)[-1]
                for name in ("low_iv", "high_iv", "shiny")
            },
            {
                "low_iv": "1f4c9.png",
                "high_iv": "1f4c8.png",
                "shiny": "2728.png",
            },
        )

    def test_removed_background_choices_migrate_to_defaults(self) -> None:
        save_profile_data(
            self.bot.profile_data_path,
            {
                "123": {
                    "text_color": "white",
                    "background": "rose",
                    "middle_background": "soft_pink",
                    "frame": "none",
                }
            },
            {},
            {},
            [],
        )

        profiles, _, _, _ = load_profile_data(self.bot.profile_data_path)

        self.assertEqual(profiles["123"]["background"], "default")
        self.assertEqual(profiles["123"]["middle_background"], "white")


class ShinyhuntCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_clear_removes_and_persists_all_of_the_users_hunts(self) -> None:
        self.bot.shinyhunters = {
            reservation_key(SERVER_ID, "Pikachu"): [123, 456],
            reservation_key(SERVER_ID, "Eevee"): [123],
            reservation_key(999, "Pikachu"): [123],
        }
        message = Mock()
        message.content = "v!sh clear"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.shinyhunt_path = Path(directory) / "shinyhunts.json"

            await self.bot.handle_shinyhunt_command(message)

            self.assertEqual(
                load_reservations(self.bot.shinyhunt_path),
                {
                    reservation_key(SERVER_ID, "Pikachu"): [456],
                    reservation_key(999, "Pikachu"): [123],
                },
            )

        message.reply.assert_awaited_once_with(
            "Your shinyhunt has been cleared.",
            mention_author=False,
        )
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                self.bot.shinyhunters,
                SERVER_ID,
                "Pikachu",
            ),
            [456],
        )
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                self.bot.shinyhunters,
                SERVER_ID,
                "Eevee",
            ),
            [],
        )

    async def test_clear_all_requires_server_administrator(self) -> None:
        self.bot.shinyhunters = {reservation_key(SERVER_ID, "Pikachu"): [123]}
        message = Mock()
        message.content = "v!sh clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = False
        message.reply = AsyncMock()

        await self.bot.handle_shinyhunt_command(message)

        message.reply.assert_awaited_once_with(
            "Only server administrators can clear everyone's shinyhunts.",
            mention_author=False,
        )
        self.assertEqual(
            self.bot.shinyhunters,
            {reservation_key(SERVER_ID, "Pikachu"): [123]},
        )

    async def test_admin_clear_all_confirms_then_clears_only_current_guild(
        self,
    ) -> None:
        self.bot.shinyhunters = {
            reservation_key(SERVER_ID, "Pikachu"): [123, 456],
            reservation_key(SERVER_ID, "Eevee"): [789],
            reservation_key(999, "Pikachu"): [123],
        }
        message = Mock()
        message.content = "v!sh clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = True
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.shinyhunt_path = Path(directory) / "shinyhunts.json"

            await self.bot.handle_shinyhunt_command(message)

            message.reply.assert_awaited_once()
            view = awaited_kwargs(message.reply)["view"]
            interaction = Mock()
            interaction.user.id = 123
            interaction.user.guild_permissions.administrator = True
            interaction.guild_id = SERVER_ID
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()
            confirm_button = next(
                button for button in view.children if button.label == "Yes"
            )
            await confirm_button.callback(interaction)

            expected = {reservation_key(999, "Pikachu"): [123]}
            self.assertEqual(self.bot.shinyhunters, expected)
            self.assertEqual(
                load_reservations(self.bot.shinyhunt_path),
                expected,
            )
            interaction.response.edit_message.assert_awaited_once_with(
                content="Everyone's shinyhunts in this server have been cleared.",
                view=None,
            )


class CollectionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_clear_all_requires_server_administrator(self) -> None:
        self.bot.collections = {reservation_key(SERVER_ID, "Pikachu"): [123]}
        message = Mock()
        message.content = "v!cl clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = False
        message.reply = AsyncMock()

        await self.bot.handle_collection_command(message)

        message.reply.assert_awaited_once_with(
            "Only server administrators can clear everyone's collection.",
            mention_author=False,
        )
        self.assertEqual(
            self.bot.collections,
            {reservation_key(SERVER_ID, "Pikachu"): [123]},
        )

    async def test_admin_clear_all_confirms_then_clears_only_current_guild(self) -> None:
        self.bot.collections = {
            reservation_key(SERVER_ID, "Pikachu"): [123, 456],
            reservation_key(SERVER_ID, "Eevee"): [789],
            reservation_key(999, "Pikachu"): [123],
        }
        message = Mock()
        message.content = "v!cl clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = True
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.collection_path = Path(directory) / "collections.json"

            await self.bot.handle_collection_command(message)

            message.reply.assert_awaited_once()
            self.assertIn("view", awaited_kwargs(message.reply))
            self.assertEqual(
                self.bot.collections,
                {
                    reservation_key(SERVER_ID, "Pikachu"): [123, 456],
                    reservation_key(SERVER_ID, "Eevee"): [789],
                    reservation_key(999, "Pikachu"): [123],
                },
            )

            view = awaited_kwargs(message.reply)["view"]
            interaction = Mock()
            interaction.user.id = 123
            interaction.user.guild_permissions.administrator = True
            interaction.guild_id = SERVER_ID
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()

            confirm_button = next(
                button for button in view.children if button.label == "Yes"
            )
            await confirm_button.callback(interaction)

            self.assertEqual(
                load_reservations(self.bot.collection_path),
                {reservation_key(999, "Pikachu"): [123]},
            )
            self.assertEqual(
                self.bot.collections,
                {reservation_key(999, "Pikachu"): [123]},
            )
            interaction.response.edit_message.assert_awaited_once_with(
                content="Everyone's Pokémon collection in this server has been cleared.",
                view=None,
            )


class TypePingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())
        self.bot.premium_servers = {str(SERVER_ID): "gold"}

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    def test_clear_guild_type_pings_preserves_other_guilds(self) -> None:
        type_pings = {
            f"{SERVER_ID}:123": ["fire"],
            f"{SERVER_ID}:456": ["normal", "water"],
            "999:123": ["grass"],
        }

        updated = clear_guild_type_pings(type_pings, SERVER_ID)

        self.assertEqual(updated, {"999:123": ["grass"]})
        self.assertEqual(type_pings[f"{SERVER_ID}:123"], ["fire"])

    async def test_clear_all_type_pings_requires_server_administrator(self) -> None:
        self.bot.type_pings = {f"{SERVER_ID}:123": ["fire"]}
        message = Mock()
        message.content = "v!tp clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = False
        message.reply = AsyncMock()

        await self.bot.handle_type_ping_command(message)

        message.reply.assert_awaited_once_with(
            "Only server administrators can clear everyone's type pings.",
            mention_author=False,
        )
        self.assertEqual(self.bot.type_pings, {f"{SERVER_ID}:123": ["fire"]})

    async def test_admin_clear_all_type_pings_confirms_and_preserves_other_guilds(
        self,
    ) -> None:
        self.bot.type_pings = {
            f"{SERVER_ID}:123": ["fire"],
            f"{SERVER_ID}:456": ["normal", "water"],
            "999:123": ["grass"],
        }
        message = Mock()
        message.content = "v!typeping clear all"
        message.guild.id = SERVER_ID
        message.author.id = 123
        message.author.guild_permissions.administrator = True
        message.reply = AsyncMock()

        with tempfile.TemporaryDirectory() as directory:
            self.bot.type_ping_path = Path(directory) / "type_pings.json"
            save_type_pings(self.bot.type_ping_path, self.bot.type_pings)

            await self.bot.handle_type_ping_command(message)

            message.reply.assert_awaited_once()
            view = awaited_kwargs(message.reply)["view"]
            self.assertIsInstance(view, ClearTypePingsView)

            interaction = Mock()
            interaction.user.id = 123
            interaction.user.guild_permissions.administrator = True
            interaction.guild_id = SERVER_ID
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()
            confirm_button = next(
                button for button in view.children if button.label == "Yes"
            )
            await confirm_button.callback(interaction)

            expected = {"999:123": ["grass"]}
            self.assertEqual(self.bot.type_pings, expected)
            self.assertEqual(load_type_pings(self.bot.type_ping_path), expected)
            interaction.response.edit_message.assert_awaited_once_with(
                content="Everyone's type pings in this server have been cleared.",
                view=None,
            )

    def test_selected_types_match_either_pokemon_type(self) -> None:
        type_pings = {
            f"{SERVER_ID}:123": ["normal"],
            f"{SERVER_ID}:456": ["fire"],
            f"{SERVER_ID}:789": ["normal", "fire"],
            f"{SERVER_ID + 1}:999": ["normal"],
        }

        self.assertEqual(
            type_ping_user_ids_for_pokemon(
                type_pings,
                SERVER_ID,
                ["fire", "normal"],
            ),
            [123, 456, 789],
        )

    async def test_type_ping_commands_edit_and_persist_multiple_selections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.type_ping_path = Path(directory) / "type_pings.json"
            for content in ("v!tp", "v!typeping"):
                message = Mock()
                message.author.bot = False
                message.author.id = 123
                message.guild.id = SERVER_ID
                message.channel.guild.id = SERVER_ID
                message.content = content
                message.embeds = []
                message.attachments = []
                message.reply = AsyncMock()

                await self.bot.on_message(message)

                message.reply.assert_awaited_once()
                view = awaited_kwargs(message.reply)["view"]
                self.assertIsInstance(view, TypePingView)
                self.assertEqual(
                    awaited_kwargs(message.reply)["embed"].title,
                    "Type Pings",
                )
                type_select = next(
                    child
                    for child in view.children
                    if isinstance(child, discord.ui.Select)
                )
                self.assertEqual(len(runtime_attribute(type_select, "options")), len(TYPE_PING_TYPES))
                self.assertEqual(type_select.max_values, len(TYPE_PING_TYPES))
                self.assertEqual(type_select.min_values, 0)
                self.assertFalse(any(option.default for option in runtime_attribute(type_select, "options")))

            interaction = Mock()
            interaction.guild_id = SERVER_ID
            interaction.user.id = 123
            interaction.response.edit_message = AsyncMock()
            interaction.response.send_message = AsyncMock()
            interaction.followup.send = AsyncMock()
            view = awaited_kwargs(message.reply)["view"]
            type_select = next(
                child
                for child in view.children
                if isinstance(child, discord.ui.Select)
            )
            set_runtime_attribute(type_select, "_values", ["normal", "fire"])

            await type_select.callback(interaction)

            self.assertEqual(
                self.bot.type_pings,
                {f"{SERVER_ID}:123": ["fire", "normal"]},
            )
            self.assertEqual(
                load_type_pings(self.bot.type_ping_path),
                {f"{SERVER_ID}:123": ["fire", "normal"]},
            )
            updated_view = awaited_kwargs(interaction.response.edit_message)["view"]
            updated_select = next(
                child
                for child in updated_view.children
                if isinstance(child, discord.ui.Select)
            )
            self.assertEqual(
                {option.value for option in runtime_attribute(updated_select, "options") if option.default},
                {"normal", "fire"},
            )
            interaction.followup.send.assert_awaited_with(
                "Type pings updated for Fire and Normal.",
                ephemeral=True,
            )

            all_on = next(
                child
                for child in updated_view.children
                if isinstance(child, discord.ui.Button) and child.label == "All On"
            )
            await all_on.callback(interaction)
            self.assertEqual(
                self.bot.type_pings[f"{SERVER_ID}:123"],
                list(TYPE_PING_TYPES),
            )
            all_on_view = awaited_kwargs(interaction.response.edit_message)["view"]
            all_on_select = next(
                child
                for child in all_on_view.children
                if isinstance(child, discord.ui.Select)
            )
            self.assertTrue(all(option.default for option in runtime_attribute(all_on_select, "options")))

            all_off = next(
                child
                for child in all_on_view.children
                if isinstance(child, discord.ui.Button) and child.label == "All Off"
            )
            await all_off.callback(interaction)
            self.assertEqual(self.bot.type_pings, {})
            self.assertEqual(load_type_pings(self.bot.type_ping_path), {})

    async def test_type_pings_wake_and_match_dual_type_spawns_in_pings_mode(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
            "only_pings": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            self.bot.type_ping_path = Path(directory) / "type_pings.json"
            self.bot.type_pings = {
                f"{SERVER_ID}:123": ["normal"],
                f"{SERVER_ID}:456": ["fire"],
            }
            save_type_pings(self.bot.type_ping_path, self.bot.type_pings)
            self.bot.collections = {
                reservation_key(SERVER_ID, "Pyroar"): [123]
            }
            self.bot.collection_path = Path(directory) / "collections.json"
            save_reservations(self.bot.collection_path, self.bot.collections)

            message = Mock()
            message.id = 708
            message.guild.id = SERVER_ID
            message.channel.id = 1208
            message.attachments = [
                Mock(content_type="image/png", url="https://example.test/spawn.png")
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Pyroar", 99.0)),
            ) as recognize:
                await self.bot.handle_spawn(message)

            recognize.assert_awaited_once()
            message.reply.assert_awaited_once()
            content = message.reply.await_args.args[0]
            self.assertIn("Pyroar: 99.00%", content.splitlines()[0])
            self.assertIn("Collection: <@123>", content)
            self.assertIn("Typeping: <@123>, <@456>", content)
            self.assertLess(content.index("Pyroar:"), content.index("Collection:"))
            self.assertEqual(content.count("<@123>"), 2)

    async def test_in_flight_spawn_uses_cleared_type_pings(self) -> None:
        self.bot.image_http = Mock(close=AsyncMock())
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            self.bot.type_ping_path = Path(directory) / "type_pings.json"
            self.bot.type_pings = {f"{SERVER_ID}:123": ["fire"]}
            save_type_pings(self.bot.type_ping_path, self.bot.type_pings)

            message = Mock()
            message.id = 709
            message.guild.id = SERVER_ID
            message.channel.id = 1209
            message.attachments = [
                Mock(content_type="image/png", url="https://example.test/spawn.png")
            ]
            message.embeds = []
            message.reply = AsyncMock()

            async def recognize_after_clear(*args, **kwargs):
                save_type_pings(self.bot.type_ping_path, {})
                return "Pyroar", 99.0

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(side_effect=recognize_after_clear),
            ):
                await self.bot.handle_spawn(message)

            self.assertNotIn("Typeping:", message.reply.await_args.args[0])


class CatchStarboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = NamingBot(ConfigTests().load_config())
        self.bot.premium_servers = {str(SERVER_ID): "gold"}

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    def test_reported_form_thumbnails(self) -> None:
        cases = (
            ("Drive Mode Miraidon", False, False, "normal_pokemon",
             "attachment://drivemodemiraidon.png"),
            ("Statue Simipour", True, False, "shiny",
             "attachment://statuesimipour.png"),
            ("Gigantamax Vanilla Cream Berry Sweet Alcremie", False, True, "gigantamax",
             "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
             "sprites/pokemon/other/home/10223.png"),
            ("Smearguru", False, False, "high_iv", "attachment://smearguru.png"),
            ("Elixir Reuniclus", False, False, "high_iv",
             "attachment://elixirreuniclus.png"),
            ("Elixir Reuniclus", True, False, "shiny",
             "attachment://elixirreuniclus.png"),
            ("Terapagos", True, False, "shiny",
             "attachment://terapagos.png"),
            ("Gigantamax Low Key Toxtricity", False, True, "gigantamax",
             "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
             "sprites/pokemon/other/home/10228.png"),
            ("Pa'u Oricorio", True, False, "shiny",
             "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
             "sprites/pokemon/other/home/shiny/10124.png"),
            ("Roaming Gimmighoul", True, False, "shiny",
             "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
             "sprites/pokemon/other/home/shiny/10263.png"),
        )
        import bot

        for name, shiny, gigantamax, category, expected in cases:
            with self.subTest(name=name, shiny=shiny):
                details = bot.CatchDetails(
                    user_id=123, pokemon=name, level="22", iv="90.86%",
                    iv_value=90.86, gender=None, shiny=shiny, chain=None,
                    gigantamax=gigantamax, missingno=False,
                )
                embed = format_starboard_embed(details, category, discord.utils.utcnow())
                self.assertEqual(embed.thumbnail.url, expected)
                path = bot.custom_starboard_thumbnail_path(details, category)
                if expected.startswith("attachment://"):
                    self.assertIsNotNone(path)
                    self.assertTrue(require_not_none(path).is_file())
                    self.assertEqual(path.parent.name, "shiny" if shiny else "thumbnails")

    def test_reported_shiny_form_animations_use_correct_forms(self) -> None:
        import bot

        for name, slug in (("Pa'u Oricorio", "oricorio-pau"),
                           ("Roaming Gimmighoul", "gimmighoul-roaming")):
            with self.subTest(name=name):
                details = bot.CatchDetails(
                    user_id=123, pokemon=name, level="22", iv="50%",
                    iv_value=50, gender=None, shiny=True, chain=None,
                    gigantamax=False, missingno=False,
                )
                self.assertEqual(
                    starboard_art_url(details, use_3d_shiny_model=True),
                    f"https://play.pokemonshowdown.com/sprites/ani-shiny/{slug}.gif",
                )

    def test_plain_catch_strips_custom_emoji_and_parses_decimal_comma_iv(self) -> None:
        details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 14 "
            "Sewaddle<:female:1207734084210532483>! (43,55%)!"
        ))

        self.assertEqual(details.pokemon, "Sewaddle")
        self.assertEqual(details.gender, "Female")
        self.assertEqual(details.iv, "43.55%")
        self.assertEqual(details.iv_value, 43.55)

    def test_catch_detection_strips_custom_emoji_and_parses_decimal_comma_iv(
        self,
    ) -> None:
        import bot

        embed = discord.Embed(title="Rare Catch Detected!")
        embed.add_field(name="Trainer:", value="<@123>", inline=True)
        embed.add_field(
            name="Pokemon:",
            value="Sewaddle<:female:1207734084210532483>",
            inline=True,
        )
        embed.add_field(name="Level:", value="14", inline=True)
        embed.add_field(name="IVs:", value="43,55%", inline=True)
        embed.set_footer(text="Catch Detection System")
        message = Mock(embeds=[embed])

        details = require_not_none(bot.parse_catch_detection_details(message))

        self.assertEqual(details.pokemon, "Sewaddle")
        self.assertEqual(details.iv, "43.55%")
        self.assertEqual(details.iv_value, 43.55)

    def test_parses_shiny_catch_details_and_only_shows_explicit_chain(self) -> None:
        details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Bagon ♀! "
            "(50.54%)! These colors seem unusual... ✨ Shiny streak reset. (554)"
        ))

        self.assertEqual(details.user_id, 123)
        self.assertEqual(details.pokemon, "Bagon")
        self.assertEqual(details.level, "20")
        self.assertEqual(details.iv, "50.54%")
        self.assertEqual(details.gender, "Female")
        self.assertTrue(details.shiny)
        self.assertEqual(details.chain, 554)
        self.assertEqual(starboard_category(details), "shiny")
        shiny_embed = format_starboard_embed(
            details,
            "shiny",
            discord.utils.utcnow(),
        )
        self.assertEqual(
            shiny_embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/shiny/371.png",
        )
        self.assertIsNone(shiny_embed.image.url)
        self.assertEqual(shiny_embed.fields, [])
        self.assertIn("**Caught by:** <@123>", embed_description(shiny_embed))
        self.assertIn("**Pokémon:** Bagon", embed_description(shiny_embed))
        self.assertIn("**Level:** 20", embed_description(shiny_embed))
        self.assertIn("**IV:** 50.54%", embed_description(shiny_embed))
        self.assertIn("**Gender:** Female", embed_description(shiny_embed))
        self.assertIn("**Shiny chain:** 554", embed_description(shiny_embed))

        no_chain = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Bagon! "
            "(50.54%)! These colors seem unusual... ✨"
        ))
        self.assertIsNone(no_chain.chain)
        no_chain_embed = format_starboard_embed(
            no_chain,
            "shiny",
            discord.utils.utcnow(),
        )
        self.assertNotIn("**Shiny chain:**", embed_description(no_chain_embed))

    def test_normal_starboard_matches_requested_forms_and_all_form_families(
        self,
    ) -> None:
        for pokemon_name in (
            "Alolan Ninetales",
            "Galarian Zen Darmanitan",
            "Perrserker",
            "Hisuian Zorua",
            "Combat Breed Tauros",
            "Blaze Breed Tauros",
            "Aqua Breed Tauros",
            "Fighting Arceus",
            "Douse Drive Genesect",
            "Wellspring-Mask Ogerpon",
            "Rapid Strike Urshifu",
            "Zenith Marshadow",
            "Partner Pikachu",
            "Partner Eevee",
            "Zygarde Cell",
            "Gigantamax Urshifu",
        ):
            with self.subTest(pokemon_name=pokemon_name):
                self.assertTrue(is_normal_starboard_pokemon(pokemon_name))
        self.assertFalse(is_normal_starboard_pokemon("Pikachu"))

    def test_normal_starboard_uses_naming_thumbnails_for_forms(self) -> None:
        examples = (("Flying Silvally", "773"),)
        for pokemon, sprite_id in examples:
            with self.subTest(pokemon=pokemon):
                details = require_not_none(parse_catch_details(
                    f"Congratulations <@123>! You caught a Level 22 {pokemon}! "
                    "(51.08%)!"
                ))

                self.assertEqual(
                    starboard_art_url(details),
                    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                    f"sprites/pokemon/other/home/{sprite_id}.png",
                )
                embed = format_starboard_embed(
                    details,
                    "normal_pokemon",
                    discord.utils.utcnow(),
                )
                self.assertEqual(
                    embed.thumbnail.url,
                    "attachment://flyingsilvally.png",
                )

        zygarde_details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 22 Zygarde Cell! "
            "(51.08%)!"
        ))
        self.assertEqual(
            starboard_art_url(zygarde_details),
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/10118.png",
        )
        zygarde_embed = format_starboard_embed(
            zygarde_details,
            "normal_pokemon",
            discord.utils.utcnow(),
        )
        self.assertEqual(
            zygarde_embed.thumbnail.url,
            "attachment://zygardecell.png",
        )

    def test_categorizes_high_iv_low_iv_missingno_and_gigantamax(self) -> None:
        examples = (
            (
                "Congratulations <@123>! You caught a Level 37 Pichu! (95.16%)!",
                "high_iv",
                "Pichu",
            ),
            (
                "Congratulations <@123>! You caught a Level 18 Archer! (8.60%)!",
                "low_iv",
                "Archer",
            ),
            (
                "Congratulations <@123>! You caught a Level ??? ???! (???)!",
                "missingno",
                "Missingno",
            ),
            (
                "Congratulations <@123>! You caught a ???! (???)!",
                "missingno",
                "Missingno",
            ),
            (
                "Congratulations <@123>! You caught a Level 30 Charizard ♀! "
                "(50.54%)! Gigantamax Factor",
                "gigantamax",
                "Gigantamax Charizard",
            ),
        )
        for text, expected_category, expected_name in examples:
            with self.subTest(expected_category=expected_category):
                details = require_not_none(parse_catch_details(text))
                self.assertEqual(details.pokemon, expected_name)
                self.assertEqual(starboard_category(details), expected_category)
                if expected_category == "missingno":
                    missingno_embed = format_starboard_embed(
                        details,
                        expected_category,
                        discord.utils.utcnow(),
                    )
                    self.assertEqual(missingno_embed.fields, [])
                    self.assertIn("**Level:** ???", embed_description(missingno_embed))
                    self.assertIn("**IV:** ???", embed_description(missingno_embed))
                if expected_category == "gigantamax":
                    gigantamax_embed = format_starboard_embed(
                        details,
                        expected_category,
                        discord.utils.utcnow(),
                    )
                    self.assertEqual(
                        gigantamax_embed.title,
                        None,
                    )
                    self.assertTrue(
                        embed_description(gigantamax_embed).startswith(
                            "<:gigantamax_icon_by_jormxdos_dffv:1570591025322528828> "
                            "**Gigantamax Capture** "
                            "<:gigantamax_icon_by_jormxdos_dffv:1570591025322528828>\n"
                        )
                    )
                    self.assertEqual(gigantamax_embed.fields, [])
                    self.assertIn(
                        f"**Pokémon:** {expected_name}",
                        embed_description(gigantamax_embed),
                    )
                    self.assertIn("**Level:** 30", embed_description(gigantamax_embed))
                    preview = format_starboard_embed(
                        details,
                        expected_category,
                        discord.utils.utcnow(),
                        test_preview=True,
                    )
                    self.assertIsNone(preview.title)
                    self.assertTrue(
                        embed_description(preview).startswith(
                            "🧪 **TEST —** "
                            "<:gigantamax_icon_by_jormxdos_dffv:1570591025322528828> "
                            "**Gigantamax Capture** "
                            "<:gigantamax_icon_by_jormxdos_dffv:1570591025322528828>\n"
                        )
                    )
                    self.assertIn("Test preview", preview.footer.text or "")

    def test_starboard_embed_has_requested_fields_timestamp_and_artwork(self) -> None:
        details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 37 Pincurchin! (95.16%)!"
        ))
        caught_at = discord.utils.utcnow()
        embed = format_starboard_embed(
            details,
            "high_iv",
            caught_at,
        )

        self.assertEqual(embed.fields, [])
        self.assertIn("**Caught by:** <@123>", embed_description(embed))
        self.assertIn("**Pokémon:** Pincurchin", embed_description(embed))
        self.assertIn("**IV:** 95.16%", embed_description(embed))
        self.assertIn("**Level:** 37", embed_description(embed))
        self.assertEqual(embed.timestamp, caught_at)
        self.assertEqual(
            embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/871.png",
        )
        self.assertIsNone(embed.image.url)
        self.assertEqual(embed.footer.text, "Caught at")
        shiny_details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Grookey! "
            "(50.54%)! These colors seem unusual... ✨"
        ))
        self.assertEqual(
            starboard_art_url(shiny_details),
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/home/shiny/810.png",
        )
        self.assertEqual(
            starboard_art_url(shiny_details, use_3d_shiny_model=True),
            "https://projectpokemon.org/images/sprites-models/"
            "swsh-shiny-sprites/grookey.gif",
        )
        articuno_details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 50 Articuno! "
            "These colors seem unusual... ✨"
        ))
        self.assertEqual(
            starboard_art_url(articuno_details, use_3d_shiny_model=True),
            "https://projectpokemon.org/images/shiny-sprite/articuno.gif",
        )
        wiglett_details = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 20 Wiglett! "
            "These colors seem unusual... ✨"
        ))
        self.assertEqual(
            starboard_art_url(wiglett_details, use_3d_shiny_model=True),
            "https://play.pokemonshowdown.com/sprites/ani-shiny/wiglett.gif",
        )
        shiny_model_embed = format_starboard_embed(
            shiny_details,
            "shiny",
            caught_at,
            use_3d_shiny_model=True,
            test_preview=True,
        )
        self.assertEqual(
            shiny_model_embed.thumbnail.url,
            "https://projectpokemon.org/images/sprites-models/"
            "swsh-shiny-sprites/grookey.gif",
        )
        self.assertIsNone(shiny_model_embed.image.url)
        self.assertIn("PKParaiso", require_not_none(shiny_model_embed.footer.text))

        actual_shiny_embed = format_starboard_embed(
            shiny_details,
            "shiny",
            caught_at,
            use_3d_shiny_model=True,
        )
        self.assertEqual(require_not_none(actual_shiny_embed.footer.text), "Caught at")

        wiglett_embed = format_starboard_embed(
            wiglett_details,
            "shiny",
            caught_at,
            use_3d_shiny_model=True,
        )
        self.assertEqual(
            wiglett_embed.thumbnail.url,
            "https://play.pokemonshowdown.com/sprites/ani-shiny/wiglett.gif",
        )
        self.assertEqual(require_not_none(wiglett_embed.footer.text), "Caught at")

        galarian_articuno = require_not_none(parse_catch_details(
            "Congratulations <@123>! You caught a Level 50 Galarian Articuno! "
            "These colors seem unusual... ✨"
        ))
        self.assertEqual(
            starboard_art_url(
                galarian_articuno,
                use_3d_shiny_model=True,
            ),
            "https://projectpokemon.org/images/sprites-models/"
            "swsh-shiny-sprites/articuno-galar.gif",
        )

    async def test_starboard_channels_save_per_server_and_render_settings_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}

            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)

            self.assertEqual(
                load_starboard_settings(self.bot.starboard_settings_path)[
                    str(SERVER_ID)
                ],
                {
                    "normal_channel": 101,
                    "shiny_channel": 202,
                    "normal_pokemon_channel": 303,
                    "shiny_base_name": None,
                    "shiny_count": 0,
                },
            )
            view = StarboardSettingsView(self.bot, SERVER_ID)
            self.assertTrue(view.has_components_v2())
            component_ids = {
                runtime_attribute(item, "custom_id")
                for item in view.walk_children()
                if getattr(item, "custom_id", None)
            }
            self.assertIn("server_settings:starboard:select:normal", component_ids)
            self.assertIn("server_settings:starboard:select:shiny", component_ids)
            self.assertIn(
                "server_settings:starboard:select:normal_pokemon",
                component_ids,
            )

    async def test_shiny_catch_posts_to_both_boards_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            main_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            channels = {101: main_channel, 202: shiny_channel}
            self.bot.get_channel = Mock(side_effect=channels.get)
            message = Mock()
            message.id = 456
            message.guild.id = SERVER_ID
            message.channel.id = 303
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 20 Bagon ♀! "
                "(50.54%)! These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.on_message(message)
            await self.bot.on_message(message)

            main_channel.send.assert_awaited_once()
            shiny_channel.send.assert_awaited_once()
            self.assertEqual(
                awaited_kwargs(main_channel.send)["embed"].title,
                "✨ Shiny Capture ✨",
            )
            self.assertFalse(
                awaited_kwargs(shiny_channel.send)["allowed_mentions"].users
            )

    async def test_normal_starboard_posts_listed_catch_with_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 461
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 22 Obstagoon! "
                "(42.12%)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            embed = awaited_kwargs(normal_channel.send)["embed"]
            self.assertEqual(embed.title, "⭐ Pokémon Spotlight")
            self.assertEqual(embed.fields, [])
            self.assertIn("**Caught by:** <@123>", embed_description(embed))
            self.assertIn("**Pokémon:** Obstagoon", embed_description(embed))
            self.assertIn("**Level:** 22", embed_description(embed))
            self.assertIn("**IV:** 42.12%", embed_description(embed))
            self.assertEqual(
                embed.thumbnail.url,
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                "sprites/pokemon/other/official-artwork/862.png",
            )
            self.assertIsNone(embed.image.url)
            self.assertEqual(embed.timestamp, message.created_at)
            button = awaited_kwargs(normal_channel.send)["view"].children[0]
            self.assertEqual(button.label, "Jump to message")
            self.assertEqual(button.style, discord.ButtonStyle.link)
            self.assertEqual(
                button.url,
                f"https://discord.com/channels/{SERVER_ID}/304/{message.id}",
            )

    async def test_normal_starboard_attaches_custom_form_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 462
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 22 Zygarde Cell! "
                "(51.08%)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            send_kwargs = awaited_kwargs(normal_channel.send)
            self.assertEqual(
                send_kwargs["embed"].thumbnail.url,
                "attachment://zygardecell.png",
            )
            self.assertEqual(
                send_kwargs["file"].filename,
                "zygardecell.png",
            )
            send_kwargs["file"].close()

    async def test_normal_starboard_accepts_catch_text_from_other_bot_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 472
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id + 1
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 12 Xurkitree ♀ "
                "(54.84%)! Added to Pokédex."
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            embed = awaited_kwargs(normal_channel.send)["embed"]
            self.assertEqual(embed.title, "⭐ Pokémon Spotlight")
            self.assertIn("**Pokémon:** Xurkitree", embed_description(embed))

    async def test_normal_starboard_posts_catch_with_curly_apostrophe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 462
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 10 "
                "Galarian Farfetch’d ♀! (62.90%)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            embed = awaited_kwargs(normal_channel.send)["embed"]
            self.assertEqual(embed.title, "⭐ Pokémon Spotlight")
            self.assertIn("**Pokémon:** Galarian Farfetch'd", embed_description(embed))
            self.assertIn("**Level:** 10", embed_description(embed))

    async def test_normal_starboard_posts_in_unlisted_guild_for_new_and_edited_catches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)

            for message_id, use_edit in ((463, False), (464, True)):
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.channel.id = 304
                message.channel.guild.id = guild_id
                message.author.bot = True
                message.author.id = self.bot.config.poketwo_bot_id
                message.created_at = discord.utils.utcnow()
                message.content = (
                    "Congratulations <@123>! You caught a Level 22 Perrserker! "
                    "(62.90%)!"
                )
                message.embeds = []

                if use_edit:
                    await self.bot.on_message_edit(Mock(), message)
                else:
                    await self.bot.on_message(message)

            self.assertEqual(normal_channel.send.await_count, 2)

    async def test_vtest_posts_labeled_preview_for_listed_pokemon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            self.bot.image_http = Mock(close=AsyncMock())
            message = Mock()
            message.id = 474
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.id = 123
            message.created_at = discord.utils.utcnow()
            message.attachments = [
                Mock(
                    content_type="image/png",
                    url="https://example.test/xurkitree.png",
                )
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Xurkitree", 100.0)),
            ):
                await self.bot.handle_spawn(message, test_mode=True)

            normal_channel.send.assert_awaited_once()
            embed = awaited_kwargs(normal_channel.send)["embed"]
            self.assertEqual(embed.title, "🧪 TEST — ⭐ Pokémon Spotlight")
            self.assertIn("**Caught by:** <@123>", embed_description(embed))
            self.assertIn("**Pokémon:** Xurkitree", embed_description(embed))
            self.assertIn("**Level:** Unknown", embed_description(embed))
            self.assertIn("**IV:** Unknown", embed_description(embed))
            self.assertEqual(embed.footer.text, "Test preview — not an actual catch")
            self.assertEqual(
                embed_description(embed),
                "\n".join(
                    (
                        "**Caught by:** <@123>",
                        "**Pokémon:** Xurkitree",
                        "**Level:** Unknown",
                        "**IV:** Unknown",
                    )
                ),
            )
            button = awaited_kwargs(normal_channel.send)["view"].children[0]
            self.assertEqual(
                button.url,
                f"https://discord.com/channels/{SERVER_ID}/304/474",
            )
            message.reply.assert_awaited_once()

    async def test_vtest_uses_custom_form_name_and_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            self.bot.image_http = Mock(close=AsyncMock())
            message = Mock()
            message.id = 475
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.id = 123
            message.created_at = discord.utils.utcnow()
            message.attachments = [
                Mock(
                    content_type="image/png",
                    url="https://example.test/partner-pikachu.png",
                )
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Partner Pikachu", 100.0)),
            ):
                await self.bot.handle_spawn(message, test_mode=True)

            normal_channel.send.assert_awaited_once()
            send_kwargs = awaited_kwargs(normal_channel.send)
            self.assertIn(
                "**Pokémon:** Partner Pikachu",
                send_kwargs["embed"].description,
            )
            self.assertEqual(
                send_kwargs["embed"].thumbnail.url,
                "attachment://partnerpikachu.png",
            )
            self.assertEqual(send_kwargs["file"].filename, "partnerpikachu.png")
            send_kwargs["file"].close()

    async def test_vtest_shiny_posts_preview_to_shinyboard_and_vivillon_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202, "shiny-board")
            self.bot.set_starboard_channel(SERVER_ID, "normal_pokemon", 303)
            shiny_channel = Mock(send=AsyncMock())
            vivillon_channel = Mock(send=AsyncMock())
            normal_pokemon_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(
                side_effect={
                    101: vivillon_channel,
                    202: shiny_channel,
                    303: normal_pokemon_channel,
                }.get
            )
            self.bot.image_http = Mock(close=AsyncMock())
            message = Mock()
            message.id = 475
            message.content = "v!test shiny"
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.channel.guild.id = SERVER_ID
            message.author.id = 123
            message.author.bot = False
            message.created_at = discord.utils.utcnow()
            message.attachments = [
                Mock(
                    content_type="image/png",
                    url="https://example.test/pikachu.png",
                )
            ]
            message.embeds = []
            message.reply = AsyncMock()

            with patch(
                "bot.recognize_pokemon",
                new=AsyncMock(return_value=("Galarian Articuno", 100.0)),
            ):
                await self.bot.on_message(message)

            shiny_channel.send.assert_awaited_once()
            vivillon_channel.send.assert_awaited_once()
            normal_pokemon_channel.send.assert_not_awaited()
            for channel in (shiny_channel, vivillon_channel):
                embed = awaited_kwargs(channel.send)["embed"]
                self.assertEqual(embed.title, "🧪 TEST — ✨ Shiny Capture ✨")
                self.assertEqual(embed.fields, [])
                self.assertIn("**Caught by:** <@123>", embed_description(embed))
                self.assertIn("**Pokémon:** Galarian Articuno", embed_description(embed))
                self.assertIn("**Level:** Unknown", embed_description(embed))
                self.assertIn("**IV:** Unknown", embed_description(embed))
                self.assertTrue(
                    embed.footer.text.startswith(
                        "Test preview — not an actual catch"
                    )
                )
                self.assertIsNone(embed.image.url)
                self.assertEqual(
                    awaited_kwargs(channel.send)["view"].children[0].url,
                    f"https://discord.com/channels/{SERVER_ID}/304/475",
                )
            shiny_embed = awaited_kwargs(shiny_channel.send)["embed"]
            self.assertEqual(
                shiny_embed.thumbnail.url,
                "https://projectpokemon.org/images/sprites-models/"
                "swsh-shiny-sprites/articuno-galar.gif",
            )
            self.assertIn("PKParaiso", require_not_none(shiny_embed.footer.text))
            vivillon_embed = awaited_kwargs(vivillon_channel.send)["embed"]
            self.assertEqual(
                vivillon_embed.thumbnail.url,
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                "sprites/pokemon/other/home/shiny/10169.png",
            )
            self.assertNotIn("PKParaiso", require_not_none(vivillon_embed.footer.text))

    async def test_real_shiny_featured_catch_skips_normal_starboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal", 101)
            self.bot.set_starboard_channel(guild_id, "shiny", 202, "shiny-board")
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            vivillon_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            shiny_channel.name = "shiny-board"
            shiny_channel.edit = AsyncMock()
            normal_pokemon_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(
                side_effect={
                    101: vivillon_channel,
                    202: shiny_channel,
                    303: normal_pokemon_channel,
                }.get
            )
            message = Mock()
            message.id = 476
            message.guild.id = guild_id
            message.channel.id = 304
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 50 Cauldron Reuniclus! "
                "These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.handle_catch_starboard(message)

            vivillon_channel.send.assert_awaited_once()
            shiny_channel.send.assert_awaited_once()
            normal_pokemon_channel.send.assert_not_awaited()
            for channel in (vivillon_channel, shiny_channel):
                send_kwargs = awaited_kwargs(channel.send)
                self.assertEqual(
                    send_kwargs["embed"].thumbnail.url,
                    "attachment://cauldronreuniclus.png",
                )
                self.assertEqual(
                    send_kwargs["file"].filename,
                    "cauldronreuniclus.png",
                )
                send_kwargs["file"].close()

    async def test_shiny_terapagos_thumbnail_is_attached_to_both_boards_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            main_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(side_effect={101: main_channel, 202: shiny_channel}.get)
            message = Mock()
            message.id = 478
            message.guild.id = SERVER_ID
            message.channel.id = 304
            message.author.id = 123
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 36 Terapagos! "
                "(33.33%)! These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.handle_catch_starboard(message)
            await self.bot.post_test_starboard(message, "Terapagos", category="shiny")

            for channel in (main_channel, shiny_channel):
                self.assertEqual(channel.send.await_count, 2)
                for call in channel.send.await_args_list:
                    self.assertEqual(call.kwargs["embed"].thumbnail.url, "attachment://terapagos.png")
                    self.assertEqual(call.kwargs["file"].filename, "terapagos.png")
                    call.kwargs["file"].close()

    async def test_normal_starboard_posts_catch_detection_embeds_from_other_bots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)

            for message_id, title, pokemon, trainer in (
                (465, "🌎 Regional Catch Detected!", "Hisuian Qwilfish", "<@123> 🌟"),
                (466, "⭐ Rare Catch Detected!", "Ogerpon", "<@123> 🌟"),
                (467, "🌎 Regional Catch Detected!", "Obstagoon", "@KillerX"),
                (468, "⭐ Rare Catch Detected!", "Azelf", "@KillerX"),
                (469, "⭐ Rare Catch Detected!", "Dialga", "@A"),
                (470, "🌎 Regional Catch Detected!", "Galarian Slowbro", "@Slyng Organizer"),
                (471, "⭐ Rare Catch Detected!", "Zapdos", None),
            ):
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.channel.id = 304
                message.channel.guild.id = guild_id
                message.author.bot = True
                message.author.id = 987654321
                message.created_at = discord.utils.utcnow()
                embed = discord.Embed(title=title)
                if trainer is not None:
                    embed.add_field(name="Trainer :", value=trainer, inline=True)
                embed.add_field(name="Pokemon :", value=pokemon, inline=True)
                embed.add_field(name="Level :", value="15", inline=True)
                embed.add_field(name="IVs :", value="54.30%", inline=True)
                embed.set_footer(text="Catch Detection System")
                message.embeds = [embed]
                message.content = ""

                await self.bot.on_message(message)

            self.assertEqual(normal_channel.send.await_count, 7)
            sent_embeds = [
                call.kwargs["embed"]
                for call in normal_channel.send.await_args_list
            ]
            self.assertEqual(
                [
                    next(
                        line
                        for line in embed_description(embed).splitlines()
                        if line.startswith("**Pokémon:** ")
                    ).removeprefix("**Pokémon:** ")
                    for embed in sent_embeds
                ],
                [
                    "Hisuian Qwilfish",
                    "Ogerpon",
                    "Obstagoon",
                    "Azelf",
                    "Dialga",
                    "Galarian Slowbro",
                    "Zapdos",
                ],
            )
            self.assertEqual(
                [
                    call.kwargs["view"].children[0].url
                    for call in normal_channel.send.await_args_list
                ],
                [
                    f"https://discord.com/channels/{guild_id}/304/{message_id}"
                    for message_id in (465, 466, 467, 468, 469, 470, 471)
                ],
            )
            self.assertIn("**Caught by:** @KillerX", sent_embeds[2].description)
            self.assertIn("**Caught by:** @A", sent_embeds[4].description)
            self.assertIn("**Caught by:** Unknown", sent_embeds[6].description)

    async def test_catch_detection_description_rows_post_pokemon_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal_pokemon", 303)
            normal_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=normal_channel)
            message = Mock()
            message.id = 467
            message.guild.id = guild_id
            message.channel.id = 304
            message.channel.guild.id = guild_id
            message.author.bot = True
            message.author.id = 987654321
            message.created_at = discord.utils.utcnow()
            embed = discord.Embed(
                title="⭐ Rare Catch Detected!",
                description=(
                    "Trainer : <@123>\n"
                    "Pokemon : Tapu Fini\n"
                    "Level : 34\n"
                    "IVs : 40.32%"
                ),
            )
            embed.set_footer(text="Catch Detection System")
            message.embeds = [embed]
            message.content = ""

            await self.bot.on_message(message)

            normal_channel.send.assert_awaited_once()
            sent_embed = awaited_kwargs(normal_channel.send)["embed"]
            self.assertIn("**Pokémon:** Tapu Fini", embed_description(sent_embed))

    async def test_catch_detection_special_categories_use_vivillon_and_shinyboards(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            guild_id = SERVER_ID + 100
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(guild_id, "normal", 101)
            self.bot.set_starboard_channel(guild_id, "shiny", 202, "shiny-board")
            vivillon_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock(), edit=AsyncMock())
            shiny_channel.name = "shiny-board"
            self.bot.get_channel = Mock(
                side_effect={101: vivillon_channel, 202: shiny_channel}.get
            )

            catches = (
                (467, "High-IV Catch Detected!", "Regieleki", "95.16%", "38"),
                (468, "Low-IV Catch Detected!", "Galarian Linoone", "8.60%", "1"),
                (469, "Shiny Catch Detected!", "Bagon", "54.30%", "15"),
                (
                    470,
                    "Gigantamax Catch Detected!",
                    "Rillaboom",
                    "54.30%",
                    "15",
                ),
                (471, "MissingNo. Catch Detected!", "MissingNo.", "???", "???"),
            )
            for message_id, title, pokemon, ivs, level in catches:
                message = Mock()
                message.id = message_id
                message.guild.id = guild_id
                message.channel.id = 304
                message.channel.guild.id = guild_id
                message.author.bot = True
                message.author.id = 987654321
                message.created_at = discord.utils.utcnow()
                embed = discord.Embed(title=title)
                embed.add_field(name="Trainer", value="<@123>", inline=True)
                embed.add_field(name="Pokemon", value=pokemon, inline=True)
                embed.add_field(name="Level", value=level, inline=True)
                embed.add_field(name="IVs", value=ivs, inline=True)
                embed.set_footer(text="Catch Detection System")
                message.embeds = [embed]
                message.content = ""

                await self.bot.on_message(message)

            self.assertEqual(vivillon_channel.send.await_count, 5)
            self.assertEqual(
                [
                    call.kwargs["embed"].title
                    for call in vivillon_channel.send.await_args_list
                ],
                [
                    "📈 High-IV Capture",
                    "📉 Low-IV Capture",
                    "✨ Shiny Capture ✨",
                    None,
                    "❔ MissingNo. Capture",
                ],
            )
            gigantamax_embed = vivillon_channel.send.await_args_list[3].kwargs["embed"]
            self.assertTrue(
                embed_description(gigantamax_embed).startswith(
                    f"{bot_module.GIGANTAMAX_EMOJI} **Gigantamax Capture** "
                    f"{bot_module.GIGANTAMAX_EMOJI}\n"
                )
            )
            shiny_channel.send.assert_awaited_once()

    async def test_missingno_catch_posts_to_the_main_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            main_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(return_value=main_channel)
            message = Mock()
            message.id = 457
            message.guild.id = SERVER_ID
            message.channel.id = 303
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level ??? ???! (???)!"
            )
            message.embeds = []

            await self.bot.on_message(message)

            main_channel.send.assert_awaited_once()
            embed = awaited_kwargs(main_channel.send)["embed"]
            self.assertEqual(embed.title, "❔ MissingNo. Capture")
            self.assertEqual(embed.fields, [])
            self.assertIn("**Caught by:** <@123>", embed_description(embed))
            self.assertIn("**Pokémon:** Missingno", embed_description(embed))
            self.assertIn("**Level:** ???", embed_description(embed))
            self.assertIn("**IV:** ???", embed_description(embed))

    async def test_shiny_catches_increment_and_persist_the_channel_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(
                SERVER_ID,
                "shiny",
                202,
                "shiny-board",
            )
            shiny_channel = Mock(send=AsyncMock(), edit=AsyncMock())
            shiny_channel.name = "shiny-board"
            self.bot.get_channel = Mock(return_value=shiny_channel)

            for message_id in (459, 460):
                message = Mock()
                message.id = message_id
                message.guild.id = SERVER_ID
                message.channel.id = 303
                message.channel.guild.id = SERVER_ID
                message.author.bot = True
                message.author.id = self.bot.config.poketwo_bot_id
                message.created_at = discord.utils.utcnow()
                message.content = (
                    "Congratulations <@123>! You caught a Level 20 Bagon! "
                    "(50.54%)! These colors seem unusual... ✨"
                )
                message.embeds = []

                await self.bot.on_message(message)

            self.assertEqual(shiny_channel.send.await_count, 2)
            self.assertEqual(
                shiny_channel.edit.await_args_list,
                [
                    call(
                        name="shiny-board-1",
                        reason="Update shiny catch count",
                    ),
                    call(
                        name="shiny-board-2",
                        reason="Update shiny catch count",
                    ),
                ],
            )
            self.assertEqual(
                load_starboard_settings(self.bot.starboard_settings_path)[
                    str(SERVER_ID)
                ]["shiny_count"],
                2,
            )

    def test_shinyboard_count_resumes_from_a_manually_increased_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(
                SERVER_ID,
                "shiny",
                202,
                "shiny-board-99",
            )

            updated_settings = self.bot.set_starboard_channel(
                SERVER_ID,
                "shiny",
                202,
                "shiny-board-110",
            )
            next_channel_name = self.bot.increment_shinyboard_count(
                SERVER_ID,
                "shiny-board-110",
            )

            self.assertEqual(updated_settings["shiny_count"], 110)
            self.assertEqual(next_channel_name, "shiny-board-111")
            self.assertEqual(
                load_starboard_settings(self.bot.starboard_settings_path)[
                    str(SERVER_ID)
                ]["shiny_count"],
                111,
            )

    async def test_shiny_gigantamax_uses_the_matching_embed_on_each_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.bot.starboard_settings_path = Path(directory) / "starboards.json"
            self.bot.starboard_settings = {}
            self.bot.set_starboard_channel(SERVER_ID, "normal", 101)
            self.bot.set_starboard_channel(SERVER_ID, "shiny", 202)
            main_channel = Mock(send=AsyncMock())
            shiny_channel = Mock(send=AsyncMock())
            self.bot.get_channel = Mock(
                side_effect={101: main_channel, 202: shiny_channel}.get
            )
            message = Mock()
            message.id = 458
            message.guild.id = SERVER_ID
            message.channel.id = 303
            message.channel.guild.id = SERVER_ID
            message.author.bot = True
            message.author.id = self.bot.config.poketwo_bot_id
            message.created_at = discord.utils.utcnow()
            message.content = (
                "Congratulations <@123>! You caught a Level 30 Corviknight ♀! "
                "(95.16%)! Gigantamax Factor. These colors seem unusual... ✨"
            )
            message.embeds = []

            await self.bot.on_message(message)

            main_embed = awaited_kwargs(main_channel.send)["embed"]
            self.assertIsNone(main_embed.title)
            self.assertTrue(
                embed_description(main_embed).startswith(
                    f"{bot_module.GIGANTAMAX_EMOJI} **Gigantamax Capture** "
                    f"{bot_module.GIGANTAMAX_EMOJI}\n"
                )
            )
            self.assertEqual(
                awaited_kwargs(shiny_channel.send)["embed"].title,
                "✨ Shiny Capture ✨",
            )
            self.assertIn(
                "**Gender:** Female",
                awaited_kwargs(shiny_channel.send)["embed"].description,
            )


class ImageTestCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ConfigTests().load_config()
        self.bot = NamingBot(self.config)
        self.bot.handle_spawn = AsyncMock()

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_test_command_with_image_runs_spawn_handler_in_test_mode(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 99
        message.channel = mock.Mock()
        message.channel.guild.id = SERVER_ID
        message.content = "v!test"
        message.embeds = []
        message.attachments = [
            mock.Mock(content_type="image/png", url="https://example.test/missingno.png")
        ]
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        cast(AsyncMock, self.bot.handle_spawn).assert_awaited_once_with(
            message,
            test_mode=True,
            shiny_test_mode=False,
        )
        message.reply.assert_not_awaited()

    async def test_test_command_without_image_explains_usage(self) -> None:
        message = Mock()
        message.author.bot = False
        message.author.id = 99
        message.channel = mock.Mock()
        message.channel.guild.id = SERVER_ID
        message.content = "v!test"
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()

        await self.bot.on_message(message)

        cast(AsyncMock, self.bot.handle_spawn).assert_not_awaited()
        message.reply.assert_awaited_once_with(
            "Attach an image to `v!test` or `v!test shiny` "
            "to test spawn recognition.",
            mention_author=False,
        )

    def test_only_exact_test_command_matches(self) -> None:
        self.assertTrue(is_image_test_command("v!test"))
        self.assertTrue(is_image_test_command("v!test shiny"))
        self.assertTrue(is_image_test_command("V!TEST SHINY  "))
        self.assertTrue(is_image_test_command("V!TEST  "))
        self.assertFalse(is_image_test_command("v!test now"))
        self.assertFalse(is_image_test_command("v!test shiny now"))
        self.assertFalse(is_image_test_command("test"))

    async def test_real_missingno_blocks_poketwo_until_vq_command(self) -> None:
        self.bot.handle_spawn = NamingBot.handle_spawn.__get__(self.bot, NamingBot)
        self.bot.premium_servers[str(SERVER_ID)] = "gold"
        self.bot.server_settings[str(SERVER_ID)] = {
            "enabled": True,
            "assisted": False,
        }
        self.bot.image_http = Mock(close=AsyncMock())
        spawn = Mock()
        spawn.id = 123
        spawn.channel.id = 456
        spawn.channel.guild.id = SERVER_ID
        spawn.guild = spawn.channel.guild
        spawn.channel.set_permissions = AsyncMock()
        spawn.attachments = [
            Mock(content_type="image/png", url="https://example.test/missingno.png")
        ]
        spawn.embeds = []
        spawn.reply = AsyncMock()

        with patch(
            "bot.recognize_pokemon",
            new=AsyncMock(return_value=("Missingno", 100.0)),
        ):
            await self.bot.handle_spawn(spawn)

        self.assertIn(456, self.bot.muted_poketwo_channels)
        self.assertEqual(self.bot.pokemon_named_count, 1)
        self.assertEqual(len(self.bot.recognition_durations), 1)
        spawn.channel.set_permissions.assert_awaited_once()
        self.assertIs(awaited_kwargs(spawn.channel.set_permissions)["send_messages"], False)

        poketwo_message = Mock()
        poketwo_message.author.bot = True
        poketwo_message.author.id = self.config.poketwo_bot_id
        poketwo_message.channel.id = 456
        poketwo_message.channel.guild.id = SERVER_ID
        poketwo_message.content = "A wild Pokémon has appeared!"
        poketwo_message.embeds = []
        poketwo_message.attachments = [
            Mock(content_type="image/png", url="https://example.test/another.png")
        ]
        self.bot.handle_spawn = AsyncMock()
        await self.bot.on_message(poketwo_message)
        cast(AsyncMock, self.bot.handle_spawn).assert_awaited_once_with(poketwo_message)

        resume_command = Mock()
        resume_command.author.bot = False
        resume_command.author.id = 789
        resume_command.author.roles = []
        resume_command.guild.id = SERVER_ID
        resume_command.channel.id = 456
        resume_command.channel.guild.id = SERVER_ID
        resume_command.channel.set_permissions = AsyncMock()
        resume_command.reply = AsyncMock()
        resume_command.content = "v!r"
        resume_command.embeds = []
        resume_command.attachments = []
        self.bot.handle_reserve_command = AsyncMock()
        self.bot.command_permissions = {}
        self.bot.is_allowed_channel = Mock(return_value=True)
        self.bot.track_chat_event_message = Mock()
        await self.bot.on_message(resume_command)

        self.assertNotIn(456, self.bot.muted_poketwo_channels)
        resume_command.channel.set_permissions.assert_awaited_once()
        resume_command.reply.assert_awaited_once_with(
            "Incense resumed.", mention_author=False
        )
        self.bot.handle_reserve_command.assert_not_awaited()

    async def test_channel_filter_allows_any_server_but_not_direct_messages(self) -> None:
        allowed_channel = Mock()
        allowed_channel.guild.id = SERVER_ID
        allowed_channel.id = 456
        another_allowed_channel = Mock()
        another_allowed_channel.guild.id = 1543384606630481920
        another_allowed_channel.id = 789
        other_server_channel = Mock()
        other_server_channel.guild.id = SERVER_ID + 1
        direct_message_channel = Mock()
        direct_message_channel.guild = None

        self.assertTrue(self.bot.is_allowed_channel(allowed_channel))
        self.assertTrue(self.bot.is_allowed_channel(another_allowed_channel))
        self.assertTrue(self.bot.is_allowed_channel(other_server_channel))
        self.assertFalse(self.bot.is_allowed_channel(direct_message_channel))

    async def test_routes_reserve_category_commands(self) -> None:
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()
        self.bot.handle_reserve_category_command = AsyncMock()
        message = Mock()
        message.author.bot = False
        message.author.id = 123
        message.channel.id = 456
        message.channel.guild.id = SERVER_ID
        message.content = "v!addcategory rare"
        message.attachments = []
        message.embeds = []

        await self.bot.on_message(message)

        self.bot.handle_reserve_category_command.assert_awaited_once_with(message)


class FireSpawnFormattingTests(unittest.TestCase):
    def test_marks_pure_fire_pokemon_but_not_dual_type_pokemon(self) -> None:
        self.assertTrue(is_single_type_fire_pokemon("Vulpix"))
        self.assertTrue(is_single_type_fire_pokemon("Growlithe"))
        self.assertFalse(is_single_type_fire_pokemon("Charizard"))
        self.assertFalse(is_single_type_fire_pokemon("Rotom Heat"))

    def test_type_spawn_embed_shows_icon_and_catch_command(self) -> None:
        embed = format_type_spawn_embed("Glaceon", 87.5, 789, "ice_type.png")

        self.assertNotIn("author", embed.to_dict())
        self.assertEqual(embed.thumbnail.url, "attachment://ice_type.png")
        self.assertEqual(embed_description(embed), "`@Pokétwo#8236 c glaceon`")

    def test_pc_catch_embed_shows_copy_label_and_spawned_pokemon_name(self) -> None:
        embed = format_pc_catch_embed("Pikachu")

        self.assertEqual(
            embed.title,
            "Catch Pikachu",
        )
        self.assertEqual(
            embed_description(embed),
            "Copy Below\n```\n@Pokétwo#8236 c pikachu\n```",
        )

    def test_meowstic_spawn_uses_species_name_without_gender_prefix(self) -> None:
        embed = format_pc_catch_embed("Male Meowstic")

        self.assertEqual(format_guess("Male Meowstic", 100), "Meowstic: 100.00%")
        self.assertEqual(
            format_catch_command(789, "Male Meowstic"),
            "@Pokétwo#8236 c meowstic",
        )
        self.assertEqual(embed.title, "Catch Meowstic")
        self.assertEqual(
            embed_description(embed),
            "Copy Below\n```\n@Pokétwo#8236 c meowstic\n```",
        )

    def test_zygarde_catch_embed_uses_ten_percent_form_sprite(self) -> None:
        embed = format_pc_catch_embed("Zygarde")

        self.assertEqual(embed.title, "Catch Zygarde")
        self.assertEqual(
            embed_description(embed),
            "Copy Below\n```\n@Pokétwo#8236 c zygarde\n```",
        )
        self.assertEqual(
            embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/official-artwork/10118.png",
        )

    def test_custom_pokemon_catch_card_uses_bundled_thumbnail(self) -> None:
        for name in ("Koraidon", "Mosslax", "Peakychu"):
            with self.subTest(name=name):
                filename = f"{name.lower()}.png"
                embed = format_pc_catch_embed(name)
                files = catch_card_files(name)

                self.assertEqual(embed.thumbnail.url, f"attachment://{filename}")
                self.assertEqual([file.filename for file in files], [filename])
        self.assertEqual(catch_card_files("Pikachu"), [])

    def test_custom_form_catch_cards_show_form_but_copy_species_name(self) -> None:
        forms = (
            ("Partner Pikachu", "Pikachu"),
            ("Partner Eevee", "Eevee"),
            ("Gliding Build Koraidon", "Koraidon"),
            ("Zenith Marshadow", "Marshadow"),
            ("Galarian Zen Darmanitan", "Darmanitan"),
            ("Zygarde Cell", "Zygarde"),
            ("Combat Breed Tauros", "Tauros"),
            ("Blaze Breed Tauros", "Tauros"),
            ("Aqua Breed Tauros", "Tauros"),
        )
        for form, species in forms:
            with self.subTest(form=form):
                embed = format_pc_catch_embed(species, form)
                files = catch_card_files(species, form)
                reply = format_spawn_reply(
                    species,
                    100,
                    POKETWO_COMMAND_BOT_ID,
                    guess_name=form,
                )
                filename = "".join(
                    character for character in form.casefold()
                    if character.isalnum()
                ) + ".png"

                self.assertEqual(embed.title, f"Catch {form}")
                self.assertEqual(
                    embed_description(embed),
                    f"Copy Below\n```\n@Pokétwo#8236 c {species.casefold()}\n```",
                )
                self.assertEqual(embed.thumbnail.url, f"attachment://{filename}")
                self.assertEqual([file.filename for file in files], [filename])
                self.assertTrue(reply.startswith(f"{form}: 100.00%"))
                self.assertIn(f"c {species.casefold()}", reply)
                for file in files:
                    file.close()

    def test_zygarde_core_displays_form_and_catches_base_species(self) -> None:
        form = "Zygarde Core"
        species = image_match.species_display_name(form)
        self.assertEqual(species, "Zygarde")
        self.assertEqual(shown_form_name(species, form), form)
        embed = format_pc_catch_embed(species, form)
        self.assertEqual(embed.title, "Catch Zygarde Core")
        self.assertEqual(
            embed_description(embed),
            "Copy Below\n```\n@Pokétwo#8236 c zygarde\n```",
        )
        self.assertTrue(
            format_spawn_reply(species, 100, POKETWO_COMMAND_BOT_ID, guess_name=form)
            .startswith("Zygarde Core: 100.00%")
        )

    def test_custom_form_uses_its_artwork_on_normal_starboard(self) -> None:
        forms = (
            "Partner Pikachu",
            "Partner Eevee",
            "Gliding Build Koraidon",
            "Zenith Marshadow",
            "Galarian Zen Darmanitan",
            "Zygarde Cell",
            "Combat Breed Tauros",
            "Blaze Breed Tauros",
            "Aqua Breed Tauros",
        )
        for form in forms:
            with self.subTest(form=form):
                details = require_not_none(parse_catch_details(
                    f"Congratulations <@123>! You caught a Level 22 {form}! "
                    "(51.08%)!"
                ))
                embed = format_starboard_embed(
                    details,
                    "normal_pokemon",
                    discord.utils.utcnow(),
                )
                filename = "".join(
                    character for character in form.casefold()
                    if character.isalnum()
                ) + ".png"

                self.assertEqual(
                    embed.thumbnail.url,
                    f"attachment://{filename}",
                )
                self.assertTrue(
                    (Path(__file__).with_name("assets") / "thumbnails" / filename)
                    .is_file()
                )

    def test_unown_variant_thumbnail_is_chosen_by_variant(self) -> None:
        self.assertEqual(image_match.base_pokemon_name("Unown Variant 3"), "Unown")
        self.assertEqual(image_match.base_pokemon_name("Tauros"), "Tauros")
        embed = format_pc_catch_embed("Unown", "Unown Variant 3")
        files = catch_card_files("Unown", "Unown Variant 3")

        self.assertEqual(
            format_guess("Unown", 100, shown_form_name("Unown", "Unown Variant 3")),
            "C Unown: 100.00%",
        )
        self.assertEqual(shown_form_name("Unown", "Q Unown"), "Q Unown")
        self.assertEqual(embed.title, "Catch C Unown")
        self.assertEqual(embed.thumbnail.url, "attachment://unownvariant3.png")
        self.assertEqual([file.filename for file in files], ["unownvariant3.png"])
        self.assertEqual(catch_card_files("Unown"), [])

        for number, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 1):
            with self.subTest(letter=letter):
                self.assertEqual(
                    format_guess(
                        "Unown",
                        100,
                        shown_form_name("Unown", f"Unown Variant {number}"),
                    ),
                    f"{letter} Unown: 100.00%",
                )
                self.assertEqual(
                    format_catch_command(POKETWO_COMMAND_BOT_ID, f"{letter} Unown"),
                    "@Pokétwo#8236 c unown",
                )
        for symbol in ("!", "?"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    format_guess("Unown", 100, f"{symbol} Unown"),
                    f"{symbol} Unown: 100.00%",
                )
                self.assertEqual(
                    format_catch_command(POKETWO_COMMAND_BOT_ID, f"{symbol} Unown"),
                    "@Pokétwo#8236 c unown",
                )
        for file in files:
            file.close()

    def test_q_unown_uses_supplied_thumbnail_and_base_species_copy_text(self) -> None:
        image_path = (
            Path(__file__).with_name("assets")
            / "thumbnails"
            / "qunown.png"
        )
        self.assertTrue(image_path.is_file())
        embed = format_pc_catch_embed("Unown", "Q Unown")
        files = catch_card_files("Unown", "Q Unown")
        reply = format_spawn_reply(
            "Unown",
            100,
            POKETWO_COMMAND_BOT_ID,
            guess_name="Q Unown",
        )

        self.assertEqual(embed.title, "Catch Q Unown")
        self.assertEqual(embed.thumbnail.url, "attachment://qunown.png")
        self.assertEqual([file.filename for file in files], ["qunown.png"])
        self.assertIn("Q Unown: 100.00%", reply)
        self.assertIn("c unown", reply)
        self.assertNotIn("c q unown", reply)
        self.assertEqual(
            reply,
            "Q Unown: 100.00%\n**Copy Here >** `@Pokétwo#8236 c unown`",
        )
        for file in files:
            file.close()

    def test_male_indeedee_uses_species_name_and_catch_command(self) -> None:
        species_name = image_match.species_display_name("Male Indeedee")

        self.assertEqual(species_name, "Indeedee")
        self.assertEqual(
            format_spawn_reply(species_name, 100, POKETWO_COMMAND_BOT_ID),
            "Indeedee: 100.00%\n"
            "**Copy Here >** `@Pokétwo#8236 c indeedee`",
        )
        self.assertEqual(
            format_pc_catch_embed(species_name, "Male Indeedee").title,
            "Catch Indeedee",
        )

    def test_alola_geodude_uses_alolan_name_and_catch_command(self) -> None:
        species_name = image_match.species_display_name("Alola Geodude")

        self.assertEqual(species_name, "Alolan Geodude")
        self.assertEqual(
            format_spawn_reply(species_name, 100, POKETWO_COMMAND_BOT_ID),
            "Alolan Geodude: 100.00%\n"
            "**Copy Here >** `@Pokétwo#8236 c alolan geodude`",
        )
        self.assertEqual(
            format_pc_catch_embed(species_name, "Alola Geodude").title,
            "Catch Alolan Geodude",
        )

    def test_hisui_sneasel_uses_full_form_name_and_base_catch_command(self) -> None:
        for alias in ("Hisui Sneasel", "Hisuian Sneasel"):
            with self.subTest(alias=alias):
                name = image_match.species_display_name(alias)
                self.assertEqual(name, "Hisuian Sneasel")
                self.assertEqual(image_match.family_name(alias), "Hisuian Sneasel")
                self.assertEqual(
                    format_spawn_reply(name, 100, POKETWO_COMMAND_BOT_ID),
                    "Hisuian Sneasel: 100.00%\n"
                    "**Copy Here >** `@Pokétwo#8236 c sneasel`",
                )
                embed = format_pc_catch_embed(name, alias)
                self.assertEqual(embed.title, "Catch Hisuian Sneasel")
                self.assertIn("@Pokétwo#8236 c sneasel", embed_description(embed))

    def test_hangry_morpeko_uses_own_thumbnail_but_is_named_morpeko(self) -> None:
        self.assertEqual(image_match.species_display_name("Hangry Morpeko"), "Morpeko")
        embed = format_pc_catch_embed("Morpeko", "Hangry Morpeko")
        files = catch_card_files("Morpeko", "Hangry Morpeko")

        self.assertEqual(embed.title, "Catch Morpeko")
        self.assertEqual(embed.thumbnail.url, "attachment://hangrymorpeko.png")
        self.assertEqual([file.filename for file in files], ["hangrymorpeko.png"])
        self.assertEqual(catch_card_files("Morpeko"), [])

    def test_minior_forms_use_species_name_in_spawn_suggestions(self) -> None:
        for form_name in (
            "Blue-Meteor Minior",
            "Blue Minior",
            "Green-Meteor Minior",
            "Green Minior",
            "Indigo-Meteor Minior",
            "Indigo Minior",
            "Orange-Meteor Minior",
            "Orange Minior",
            "Red-Meteor Minior",
            "Red Minior",
            "Violet-Meteor Minior",
            "Violet Minior",
            "Yellow-Meteor Minior",
            "Yellow Minior",
        ):
            with self.subTest(form_name=form_name):
                species_name = image_match.species_display_name(form_name)
                self.assertEqual(
                    format_spawn_reply(species_name, 100, POKETWO_COMMAND_BOT_ID),
                    "Minior: 100.00%\n"
                    "**Copy Here >** `@Pokétwo#8236 c minior`",
                )

    def test_shellos_and_gastrodon_sea_forms_use_base_catch_names(self) -> None:
        for form_name, species_name in (
            ("East Shellos", "Shellos"),
            ("East Sea Shellos", "Shellos"),
            ("West Shellos", "Shellos"),
            ("West Sea Shellos", "Shellos"),
            ("East Gastrodon", "Gastrodon"),
            ("East Sea Gastrodon", "Gastrodon"),
            ("West Gastrodon", "Gastrodon"),
            ("West Sea Gastrodon", "Gastrodon"),
        ):
            with self.subTest(form_name=form_name):
                canonical_name = image_match.species_display_name(form_name)
                self.assertEqual(canonical_name, species_name)
                self.assertEqual(
                    format_spawn_reply(
                        canonical_name,
                        100,
                        POKETWO_COMMAND_BOT_ID,
                    ),
                    f"{species_name}: 100.00%\n"
                    f"**Copy Here >** `@Pokétwo#8236 c "
                    f"{species_name.casefold()}`",
                )

    def test_east_shellos_catch_card_uses_user_reference_thumbnail(self) -> None:
        embed = format_pc_catch_embed("Shellos", "East Shellos")
        files = catch_card_files("Shellos", "East Shellos")

        self.assertEqual(embed.title, "Catch Shellos")
        self.assertEqual(embed.thumbnail.url, "attachment://eastshellos.png")
        self.assertEqual([file.filename for file in files], ["eastshellos.png"])
        for file in files:
            file.close()

    def test_collection_all_pokemon_lists_every_form_and_matches_spawns(self) -> None:
        collections = add_collection_pokemon({}, 1, ["all deerling", "pikachu"], 5)

        self.assertEqual(
            collection_pokemon_for_user(collections, 1, 5),
            [
                "autumn deerling",
                "pikachu",
                "spring deerling",
                "summer deerling",
                "winter deerling",
            ],
        )
        self.assertEqual(
            collection_user_ids_for_pokemon(collections, 1, "Summer Deerling"), [5]
        )
        self.assertEqual(
            split_collection_add_names(collections, 1, ["all deerling"], 5),
            ([], ["all deerling"]),
        )
        self.assertEqual(
            format_collection_add_confirmation(["all deerling"], []),
            "Added All forms of deerling to your collection.",
        )
        updated, removed, missing = remove_collection_pokemon(
            collections, 1, ["all deerling"], 5
        )
        self.assertEqual(removed, ["all deerling"])
        self.assertEqual(collection_pokemon_for_user(updated, 1, 5), ["pikachu"])

    def test_legacy_all_collection_keys_are_migrated(self) -> None:
        migrated = migrate_legacy_all_keys({"1:all deerling": [5], "1:eevee": [5]})

        self.assertEqual(migrated, {"1:*:deerling": [5], "1:eevee": [5]})

    def test_fire_spawns_use_inline_custom_emoji_without_embed(self) -> None:
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Vulpix", 87.5, 789, [123], include_fire=True
            ),
            "<:fire:1560301436074729532> Vulpix: 87.50%\n"
            "Reserved: <@123>\n"
            "**Copy Here >** `@Pokétwo#8236 c vulpix`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Vulpix",
                87.5,
                789,
                collection_user_ids=[456],
                include_fire=True,
                type_ping_user_ids=[123],
            ),
            "<:fire:1560301436074729532> Vulpix: 87.50%\n"
            "Collection: <@456>\n"
            "Typeping: <@123>\n"
            "**Copy Here >** `@Pokétwo#8236 c vulpix`",
        )
        self.assertTrue(is_fire_icon_pokemon("Vulpix"))
        self.assertTrue(is_fire_icon_pokemon("Litleo"))
        self.assertFalse(is_fire_icon_pokemon("Charizard"))
        self.assertIsNone(fire_companion_icon_filename_for_pokemon("Vulpix"))
        self.assertTrue(is_water_icon_pokemon("Magikarp"))
        self.assertTrue(is_water_icon_pokemon("Dewgong"))
        self.assertFalse(is_water_icon_pokemon("Gyarados"))
        self.assertTrue(is_normal_icon_pokemon("Eevee"))
        self.assertTrue(is_normal_icon_pokemon("Bibarel"))
        self.assertFalse(is_normal_icon_pokemon("Pidgeot"))
        self.assertTrue(is_electric_icon_pokemon("Pikachu"))
        self.assertTrue(is_electric_icon_pokemon("Heliolisk"))
        self.assertFalse(is_electric_icon_pokemon("Magnemite"))
        self.assertTrue(is_grass_icon_pokemon("Treecko"))
        self.assertTrue(is_grass_icon_pokemon("Scovillain"))
        self.assertFalse(is_grass_icon_pokemon("Bulbasaur"))
        self.assertTrue(is_single_type_ice_pokemon("Glaceon"))
        self.assertTrue(is_ice_icon_pokemon("Glaceon"))
        self.assertTrue(is_ice_icon_pokemon("Darmanitan-Galar-Zen"))
        self.assertTrue(is_ice_icon_pokemon("Lapras"))
        self.assertTrue(is_ice_icon_pokemon("Arctozolt"))
        self.assertFalse(is_ice_icon_pokemon("Charizard"))
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Eevee", 87.5, 789, include_normal=True
            ),
            "<:Normal:1560305235279482930> Eevee: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c eevee`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Volcanion", 87.5, 789, include_fire=True, include_water=True
            ),
            "<:water:1560303864094130357> "
            "<:fire:1560301436074729532> Volcanion: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c volcanion`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Litleo", 87.5, 789, include_fire=True, include_normal=True
            ),
            "<:fire:1560301436074729532> "
            "<:Normal:1560305235279482930> Litleo: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c litleo`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Bibarel", 87.5, 789, include_water=True, include_normal=True
            ),
            "<:Normal:1560305235279482930> "
            "<:water:1560303864094130357> Bibarel: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c bibarel`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Heliolisk", 87.5, 789, include_electric=True, include_normal=True
            ),
            "<:Electric:1560306053164572732> "
            "<:Normal:1560305235279482930> Heliolisk: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c heliolisk`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Rotom Heat", 87.5, 789, include_fire=True, include_electric=True
            ),
            "<:fire:1560301436074729532> "
            "<:Electric:1560306053164572732> Rotom Heat: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c rotom heat`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Scovillain", 87.5, 789, include_grass=True, include_fire=True
            ),
            "<:grass:1560307079896502282> "
            "<:fire:1560301436074729532> Scovillain: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c scovillain`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Lotad", 87.5, 789, include_grass=True, include_water=True
            ),
            "<:grass:1560307079896502282> "
            "<:water:1560303864094130357> Lotad: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c lotad`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Smoliv", 87.5, 789, include_grass=True, include_normal=True
            ),
            "<:grass:1560307079896502282> "
            "<:Normal:1560305235279482930> Smoliv: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c smoliv`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Rotom Mow", 87.5, 789, include_grass=True, include_electric=True
            ),
            "<:grass:1560307079896502282> "
            "<:Electric:1560306053164572732> Rotom Mow: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c rotom mow`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Glaceon", 87.5, 789, include_ice=True
            ),
            "<:Ice:1560307867200782386> Glaceon: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c glaceon`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Darmanitan-Galar-Zen",
                87.5,
                789,
                include_fire=True,
                include_ice=True,
            ),
            "<:Ice:1560307867200782386> "
            "<:fire:1560301436074729532> Darmanitan-Galar-Zen: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c darmanitan-galar-zen`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Lapras", 87.5, 789, include_water=True, include_ice=True
            ),
            "<:Ice:1560307867200782386> "
            "<:water:1560303864094130357> Lapras: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c lapras`",
        )
        self.assertEqual(
            format_custom_type_spawn_reply(
                "Arctozolt", 87.5, 789, include_electric=True, include_ice=True
            ),
            "<:Ice:1560307867200782386> "
            "<:Electric:1560306053164572732> Arctozolt: 87.50%\n"
            "**Copy Here >** `@Pokétwo#8236 c arctozolt`",
        )
        with patch("bot.NORMAL_AND_ICE_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertTrue(is_ice_icon_pokemon("Test Pokemon"))
            self.assertEqual(
                format_custom_type_spawn_reply(
                    "Test Pokemon",
                    87.5,
                    789,
                    include_normal=True,
                    include_ice=True,
                ),
                "<:Normal:1560305235279482930> "
                "<:Ice:1560307867200782386> Test Pokemon: 87.50%\n"
                "**Copy Here >** `@Pokétwo#8236 c test pokemon`",
            )
        self.assertIsNone(fire_companion_icon_filename_for_pokemon("Volcanion"))
        self.assertIsNone(water_companion_icon_filename_for_pokemon("Volcanion"))
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Litleo"),
            None,
        )
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Rotom Heat"),
            None,
        )
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Scovillain"),
            None,
        )
        self.assertEqual(
            fire_companion_icon_filename_for_pokemon("Darmanitan-Galar-Zen"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Bibarel"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Lanturn"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Ogerpon Wellspring Mask"),
            None,
        )
        self.assertEqual(
            water_companion_icon_filename_for_pokemon("Lapras"),
            None,
        )
        self.assertIsNone(normal_companion_icon_filename_for_pokemon("Bibarel"))
        with patch("bot.NORMAL_AND_ICE_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertTrue(is_normal_icon_pokemon("Test Pokemon"))
            self.assertEqual(
                normal_companion_icon_filename_for_pokemon("Test Pokemon"),
                None,
            )
        self.assertEqual(
            electric_companion_icon_filename_for_pokemon("Voltorb-Hisui"),
            None,
        )
        self.assertEqual(
            electric_companion_icon_filename_for_pokemon("Arctozolt"),
            None,
        )

    def test_marks_only_single_type_normal_pokemon(self) -> None:
        self.assertTrue(is_single_type_normal_pokemon("Eevee"))
        self.assertFalse(is_single_type_normal_pokemon("Pidgeot"))
        self.assertFalse(is_single_type_normal_pokemon("Girafarig"))

    def test_uses_both_icons_only_for_fire_and_normal_dual_type(self) -> None:
        self.assertIsNone(type_icon_filename_for_pokemon("Eevee"))
        self.assertEqual(type_icon_filename_for_pokemon("Squirtle"), "water_type.png")
        self.assertIsNone(type_icon_filename_for_pokemon("Bibarel"))
        for name in ("Heliolisk", "Helioptile"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        for name in ("Lanturn", "Chinchou", "Rotom Wash"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        self.assertIsNone(type_icon_filename_for_pokemon("Pikachu"))
        self.assertIsNone(type_icon_filename_for_pokemon("Decidueye"))
        for name in ("Lotad", "Lombre", "Ludicolo", "Ogerpon Wellspring Mask"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        self.assertIsNone(type_icon_filename_for_pokemon("Bulbasaur"))
        for name in ("Smoliv", "Dolliv", "Arboliva", "Deerling", "Sawsbuck"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        for name in ("Voltorb-Hisui", "Electrode-Hisui", "Rotom Mow"):
            self.assertIsNone(type_icon_filename_for_pokemon(name))
        self.assertIsNone(type_icon_filename_for_pokemon("Snivy"))
        self.assertIsNone(type_icon_filename_for_pokemon("Treecko"))
        self.assertEqual(type_icon_filename_for_pokemon("Glaceon"), "ice_type.png")
        self.assertEqual(type_icon_filename_for_pokemon("Cetitan"), "ice_type.png")
        for name in ("Dewgong", "Cloyster", "Lapras", "Arctovish"):
            self.assertEqual(
                type_icon_filename_for_pokemon(name),
                "ice_water_type_icons.png",
            )
        self.assertIsNone(type_icon_filename_for_pokemon("Darmanitan-Galar-Zen"))
        with patch("bot.NORMAL_AND_ICE_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertIsNone(type_icon_filename_for_pokemon("Test Pokemon"))
        with patch("bot.ICE_AND_ELECTRIC_TYPE_ALIASES", frozenset({"test pokemon"})):
            self.assertIsNone(type_icon_filename_for_pokemon("Test Pokemon"))
        self.assertIsNone(type_icon_filename_for_pokemon("Venusaur"))
        self.assertTrue(is_single_type_electric_pokemon("Jolteon"))
        self.assertFalse(is_single_type_electric_pokemon("Raichu-alola"))
        self.assertFalse(is_single_type_electric_pokemon("Magnemite"))
        self.assertTrue(is_single_type_water_pokemon("Magikarp"))
        self.assertFalse(is_single_type_water_pokemon("Gyarados"))
        self.assertFalse(is_single_type_water_pokemon("Lapras"))
        self.assertIsNone(type_icon_filename_for_pokemon("Charizard"))
        with patch(
            "bot.FIRE_AND_NORMAL_TYPE_ALIASES",
            frozenset({"test pokemon"}),
        ):
            self.assertTrue(is_fire_icon_pokemon("Test Pokemon"))
            self.assertEqual(
                fire_companion_icon_filename_for_pokemon("Test Pokemon"),
                None,
            )
            self.assertIsNone(type_icon_filename_for_pokemon("Test Pokemon"))


class GuessFormatTests(unittest.TestCase):
    def test_basculin_stripe_forms_use_species_name_and_catch_command(self) -> None:
        for form in (
            "Blue-Striped Basculin",
            "Red-Striped Basculin",
            "White-Striped Basculin",
        ):
            with self.subTest(form=form):
                name = image_match.species_display_name(form)
                guess_name = shown_form_name(name, form)
                self.assertEqual(name, "Basculin")
                self.assertEqual(
                    format_guess(name, 100, guess_name),
                    "Basculin: 100.00%",
                )
                self.assertEqual(
                    format_catch_command(POKETWO_COMMAND_BOT_ID, name),
                    "@Pokétwo#8236 c basculin",
                )

    def test_alola_graveler_alias_uses_alolan_name(self) -> None:
        from image_match import family_name, species_display_name

        for alias in ("Alola Graveler", "alola-graveler", "alola_graveler"):
            with self.subTest(alias=alias):
                name = species_display_name(alias)
                self.assertEqual(name, "Alolan Graveler")
                self.assertEqual(family_name(alias), "Alolan Graveler")
                self.assertEqual(format_guess(name, 100), "Alolan Graveler: 100.00%")
                self.assertEqual(
                    format_catch_command(POKETWO_COMMAND_BOT_ID, name),
                    "@Pokétwo#8236 c alolan graveler",
                )

    def test_aegislash_forms_use_base_name_in_catch_commands(self) -> None:
        for form in ("Shield Aegislash", "Blade Aegislash"):
            with self.subTest(form=form):
                reply = format_spawn_reply(
                    form,
                    100,
                    POKETWO_COMMAND_BOT_ID,
                    guess_name=form,
                )
                self.assertIn(f"{form}: 100.00%", reply)
                self.assertIn(
                    "@Pokétwo#8236 c aegislash",
                    reply,
                )
                self.assertNotIn(
                    f"c {form.casefold()}",
                    reply,
                )

                embed = format_pc_catch_embed(form, form)
                self.assertEqual(embed.title, f"Catch {form}")
                self.assertIn("@Pokétwo#8236 c aegislash", embed_description(embed))

    def test_average_gourgeist_uses_species_name_in_spawn_output(self) -> None:
        name = image_match.species_display_name("Average Gourgeist")

        self.assertEqual(name, "Gourgeist")
        self.assertEqual(format_guess(name, 100), "Gourgeist: 100.00%")
        self.assertEqual(
            format_catch_command(POKETWO_COMMAND_BOT_ID, name),
            "@Pokétwo#8236 c gourgeist",
        )
        self.assertEqual(
            format_pc_catch_embed(name, "Average Gourgeist").title,
            "Catch Gourgeist",
        )

    def test_eiscue_face_names_use_species_name_and_catch_command(self) -> None:
        from image_match import family_name, species_display_name

        for alias in ("Ice Eiscue", "Noice Eiscue"):
            with self.subTest(alias=alias):
                name = species_display_name(alias)
                self.assertEqual(name, "Eiscue")
                self.assertEqual(family_name(alias), "Eiscue")
                self.assertEqual(format_guess(name, 100), "Eiscue: 100.00%")
                self.assertEqual(
                    format_catch_command(POKETWO_COMMAND_BOT_ID, name),
                    "@Pokétwo#8236 c eiscue",
                )
                self.assertEqual(
                    format_pc_catch_embed(name, alias).title,
                    "Catch Eiscue",
                )

    def test_maushold_family_variants_use_species_name_and_catch_command(self) -> None:
        from image_match import family_name, species_display_name

        for form in (
            "Family-Of-Three Maushold",
            "Family of Three Maushold",
            "Family-Of-Four Maushold",
            "family of four maushold",
        ):
            with self.subTest(form=form):
                name = species_display_name(form)
                self.assertEqual(name, "Maushold")
                self.assertEqual(family_name(form.title()), "Maushold")
                self.assertEqual(format_guess(name, 99.81), "Maushold: 99.81%")
                self.assertEqual(
                    format_catch_command(POKETWO_COMMAND_BOT_ID, name),
                    "@Pokétwo#8236 c maushold",
                )

    def test_recognizes_missingno_aliases(self) -> None:
        for name in ("Missingno.", "missingno", "???"):
            with self.subTest(name=name):
                self.assertTrue(is_missingno_name(name))
        self.assertFalse(is_missingno_name("Pikachu"))

    def test_formats_one_guess_without_a_label(self) -> None:
        self.assertEqual(format_guess("Pikachu", 85), "Pikachu: 85.00%")
        self.assertEqual(format_guess("Absol", 56.86), "Absol: 56.86%")

    def test_formats_plain_poketwo_catch_command(self) -> None:
        self.assertEqual(
            format_catch_command(POKETWO_COMMAND_BOT_ID, "Pikachu"),
            "@Pokétwo#8236 c pikachu",
        )

    def test_formats_guess_and_command_on_separate_lines(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 85, 716390085896962058),
            "Pikachu: 85.00%\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_squawkabilly_color_forms_use_the_species_name(self) -> None:
        for form_name in (
            "Blue-Plumage Squawkabilly",
            "Green-Plumage Squawkabilly",
            "White-Plumage Squawkabilly",
            "Yellow-Plumage Squawkabilly",
        ):
            with self.subTest(form_name=form_name):
                species_name = image_match.species_display_name(form_name)
                self.assertEqual(
                    format_spawn_reply(species_name, 100, POKETWO_COMMAND_BOT_ID),
                    "Squawkabilly: 100.00%\n"
                    "**Copy Here >** `@Pokétwo#8236 c squawkabilly`",
                )

    def test_formats_only_the_reserved_members_as_mentions(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 716390085896962058, [123, 456]),
            "Pikachu: 95.00%\n"
            "Reserved: <@123>, <@456>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_formats_shinyhunters_without_empty_collection_line(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [], [123, 456]),
            "Absol: 95.00%\n"
            "Shinyhunt: <@123>, <@456>\n"
            "**Copy Here >** `@Pokétwo#8236 c absol`",
        )

    def test_reservations_override_shinyhunters_in_spawn_reply(self) -> None:
        self.assertEqual(
            format_spawn_reply("Absol", 95, 789, [999], [123, 456]),
            "Absol: 95.00%\n"
            "Reserved: <@999>\n"
            "**Copy Here >** `@Pokétwo#8236 c absol`",
        )

    def test_collection_ping_is_included_without_empty_shinyhunt_line(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [], [], [123]),
            "Pikachu: 95.00%\n"
            "Collection: <@123>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_collection_and_shinyhunt_ping_multiple_members(self) -> None:
        self.assertEqual(
            format_spawn_reply("Pikachu", 95, 789, [], [123], [456, 789]),
            "Pikachu: 95.00%\n"
            "Shinyhunt: <@123>\n"
            "Collection: <@456>, <@789>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_typeping_has_its_own_line_after_collection(self) -> None:
        self.assertEqual(
            format_spawn_reply(
                "Pikachu",
                95,
                789,
                [],
                [123],
                [456],
                [789, 101],
            ),
            "Pikachu: 95.00%\n"
            "Shinyhunt: <@123>\n"
            "Collection: <@456>\n"
            "Typeping: <@789>, <@101>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )

    def test_reservation_overrides_all_other_ping_categories(self) -> None:
        self.assertEqual(
            format_spawn_reply(
                "Pikachu",
                95,
                789,
                [111],
                [123],
                [456],
                [789],
            ),
            "Pikachu: 95.00%\n"
            "Reserved: <@111>\n"
            "**Copy Here >** `@Pokétwo#8236 c pikachu`",
        )


class AllFormsMatchingTests(unittest.TestCase):
    def test_all_marshadow_matches_other_forms_of_marshadow(self) -> None:
        for name in ("Marshadow", "Zenith Marshadow", "Marshadow (Zenith)", "Mega Marshadow"):
            with self.subTest(name=name):
                self.assertTrue(pokemon_matches_all_forms_reservation(name, "marshadow"))

    def test_all_forms_does_not_match_other_species(self) -> None:
        self.assertFalse(pokemon_matches_all_forms_reservation("Mewtwo", "mew"))
        self.assertFalse(pokemon_matches_all_forms_reservation("Mega Mewtwo X", "mew"))


class ReservationExchangeTests(unittest.TestCase):
    def test_parses_member_lines_with_multiple_pokemon(self) -> None:
        text = "<@1> - pikachu, Eevee\n<@2> - all arceus\nnoise\n<@3> – sylveon"

        self.assertEqual(
            parse_exchange_list(text),
            [(1, ["pikachu", "Eevee"]), (2, ["all arceus"]), (3, ["sylveon"])],
        )

    def test_exchange_list_works_without_dash(self) -> None:
        self.assertEqual(
            parse_exchange_list("<@1> pikachu, Eevee\n<@2>all arceus"),
            [(1, ["pikachu", "Eevee"]), (2, ["all arceus"])],
        )

    def test_list_texts_include_forwarded_snapshots(self) -> None:
        from bot import message_list_texts

        snapshot = SimpleNamespace(
            content="<@1> pikachu", embeds=[SimpleNamespace(description="emb")]
        )
        message: discord.Message = cast(
            discord.Message,
            SimpleNamespace(content="", embeds=[], message_snapshots=[snapshot]),
        )
        self.assertEqual(message_list_texts(message), ["<@1> pikachu", "emb"])

    def test_moves_only_reservations_held_by_the_source(self) -> None:
        reservations = {
            "10:pikachu": [100, 5],
            "10:eevee": [5],
            "10:*:arceus": [100],
        }
        updated, moved, skipped = exchange_reservations(
            reservations,
            10,
            100,
            [(1, ["pikachu", "eevee"]), (2, ["all arceus"])],
        )

        self.assertEqual(updated["10:pikachu"], [5, 1])
        self.assertEqual(updated["10:eevee"], [5])
        self.assertEqual(updated["10:*:arceus"], [2])
        self.assertEqual(moved, [(1, "pikachu"), (2, "all arceus")])
        self.assertEqual(skipped, [(1, "eevee")])
        self.assertEqual(reservations["10:pikachu"], [100, 5])


class AllFormsExchangeTests(unittest.TestCase):
    def test_all_marshadow_moves_every_marshadow_form(self) -> None:
        reservations = {
            "10:*:marshadow": [100],
            "10:marshadow": [100],
            "10:zenith marshadow": [100, 7],
            "10:mew": [100],
        }
        updated, moved, skipped = exchange_reservations(
            reservations, 10, 100, [(1, ["all marshadow"])]
        )

        self.assertEqual(updated["10:*:marshadow"], [1])
        self.assertEqual(updated["10:marshadow"], [1])
        self.assertEqual(updated["10:zenith marshadow"], [7, 1])
        self.assertEqual(updated["10:mew"], [100])
        self.assertEqual(moved, [(1, "all marshadow")])
        self.assertEqual(skipped, [])


class RegionalExchangeTests(unittest.TestCase):
    def test_all_articuno_exchange_includes_regional_forms(self) -> None:
        reservations = {
            "10:*:articuno": [100],
            "10:articuno": [100],
            "10:galarian articuno": [100],
            "10:articuno (galar)": [100],
            "10:zapdos": [100],
        }
        updated, moved, _ = exchange_reservations(
            reservations, 10, 100, [(1, ["all articuno"])]
        )

        for key in (
            "10:*:articuno",
            "10:articuno",
            "10:galarian articuno",
            "10:articuno (galar)",
        ):
            self.assertEqual(updated[key], [1])
        self.assertEqual(updated["10:zapdos"], [100])
        self.assertEqual(moved, [(1, "all articuno")])


class GrabListTests(unittest.TestCase):
    def test_parses_search_lines_and_mentions(self) -> None:
        entries = parse_grab_entries(
            ["pikachu <@1>\n- eevee\nall forms of arceus <@2> <@3>"]
        )

        self.assertEqual(
            entries,
            [("pikachu", [1]), ("eevee", []), ("all arceus", [2])],
        )

    def test_parses_labelled_org_reserve_list(self) -> None:
        text = (
            "📜 **Org Reserve List**\n\n"
            "**Regional** — <@1> - Zorua\n"
            "**Eevos** — <@2> - Absol\n"
            "**Booster** — <@3> - Cutiefly\n"
            "**Booster 2** — <@2> - Missingno"
        )

        self.assertEqual(
            parse_grab_entries([text]),
            [("Zorua", [1]), ("Absol", [2]), ("Cutiefly", [3]), ("Missingno", [2])],
        )

    def test_parses_plain_and_comma_lists(self) -> None:
        self.assertEqual(
            parse_grab_entries(["Mewtwo\n1. Mr. Mime, Galarian Articuno <@4>\nhello"]),
            [("Mewtwo", []), ("Mr. Mime", [4]), ("Galarian Articuno", [4])],
        )

    def test_pipe_separated_groups_keep_pokemon_with_their_mentioned_user(self) -> None:
        self.assertEqual(
            parse_grab_entries(
                ["Regional — <@1> - Sneasel | <@2> Amaura | <@3> Zorua"]
            ),
            [("Sneasel", [1]), ("Amaura", [2]), ("Zorua", [3])],
        )

    def test_two_mentions_give_pokemon_only_to_nearest_user(self) -> None:
        self.assertEqual(
            parse_grab_entries(
                [
                    "Rare — <@1> - <@2> Zorua | <@3> - Archaludon\n"
                    "Res 3 — <@4> - Aerodactyl | Honedge"
                ]
            ),
            [
                ("Zorua", [2]),
                ("Archaludon", [3]),
                ("Aerodactyl", [4]),
                ("Honedge", [4]),
            ],
        )

    def test_order_all_forms_and_emoji_cycle(self) -> None:
        entries = [
            ("sylveon", [1]),
            ("trapinch", []),
            ("urshifu", []),
            ("all arceus", [2]),
            ("ditto", []),
        ]

        self.assertEqual(
            build_grab_lines(entries, ordered=True, all_forms=True, emojis=["🔥", "💧"]),
            ["🔥 All arceus", "💧 Ditto", "🔥 Sylveon", "💧 Trapinch", "🔥 Urshifu"],
        )
        self.assertEqual(
            build_grab_lines(entries, ordered=False, all_forms=False, emojis=[]),
            ["Sylveon", "Trapinch", "Urshifu", "Arceus", "Ditto"],
        )

    def test_all_forms_only_applies_to_entries_marked_in_source(self) -> None:
        entries = [("urshifu", [1]), ("all arceus", [2])]

        self.assertEqual(
            grab_reserve_pairs(entries, True),
            [("urshifu", 1), ("all arceus", 2)],
        )
        self.assertEqual(
            grab_reserve_pairs(entries, False),
            [("urshifu", 1), ("arceus", 2)],
        )

    def test_grab_display_names(self) -> None:
        self.assertEqual(grab_display_name("pikachu"), "Pikachu")
        self.assertEqual(grab_display_name("all urshifu"), "All forms of urshifu")

    def test_bulk_add_gives_each_pokemon_to_its_user(self) -> None:
        pairs = grab_reserve_pairs(
            [("pikachu", [1]), ("alcremie", [2]), ("eevee", [])], False
        )
        updated = add_reservations_bulk({"5:pikachu": [9]}, 5, pairs)

        self.assertEqual(updated["5:pikachu"], [9, 1])
        self.assertEqual(updated["5:alcremie"], [2])
        self.assertNotIn("5:eevee", updated)


class ReservationPersistenceTests(unittest.TestCase):
    def test_parses_and_deduplicates_multiple_collection_pokemon(self) -> None:
        self.assertEqual(
            parse_collection_add_command("v!cl add Pikachu, eevee, pikachu"),
            ["Pikachu", "eevee"],
        )
        self.assertIsNone(parse_collection_add_command("v!cl add pikachu,,eevee"))
        self.assertIsNone(parse_collection_add_command("v!cl add pikachu!"))

    def test_collection_add_keeps_multiple_members_and_guilds_separate(self) -> None:
        collections = add_collection_pokemon({}, 1, ["Pikachu", "Eevee"], 123)
        collections = add_collection_pokemon(collections, 1, ["Pikachu"], 456)
        collections = add_collection_pokemon(collections, 2, ["Pikachu"], 789)

        self.assertEqual(
            collections[reservation_key(1, "pikachu")],
            [123, 456],
        )
        self.assertEqual(
            collection_user_ids_for_pokemon(collections, 1, "Pikachu"),
            [123, 456],
        )
        self.assertEqual(
            collection_user_ids_for_pokemon(collections, 2, "Pikachu"),
            [789],
        )
        self.assertEqual(
            collection_pokemon_for_user(collections, 1, 123),
            ["eevee", "pikachu"],
        )

    def test_collection_add_detects_existing_names_for_the_same_user(self) -> None:
        collections = add_collection_pokemon({}, 1, ["Pikachu"], 123)

        new_names, already_added = split_collection_add_names(
            collections,
            1,
            ["pikachu", "Eevee"],
            123,
        )

        self.assertEqual(new_names, ["Eevee"])
        self.assertEqual(already_added, ["pikachu"])
        self.assertEqual(
            format_collection_add_confirmation(new_names, already_added),
            "Added Eevee to your collection. Pikachu already added to your collection.",
        )

    def test_collection_add_duplicate_response_for_single_pokemon(self) -> None:
        self.assertEqual(
            format_collection_add_confirmation([], ["pikachu"]),
            "Pikachu already added to your collection.",
        )

    def test_collection_remove_only_removes_requesting_user(self) -> None:
        collections = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated, removed, missing = remove_collection_pokemon(
            collections,
            1,
            ["pikachu", "eevee"],
            123,
        )

        self.assertEqual(removed, ["pikachu", "eevee"])
        self.assertEqual(missing, [])
        self.assertEqual(updated, {
            reservation_key(1, "Pikachu"): [456],
            reservation_key(2, "Pikachu"): [123],
        })
        self.assertEqual(collections[reservation_key(1, "Pikachu")], [123, 456])

    def test_collection_remove_reports_names_not_in_users_collection(self) -> None:
        updated, removed, missing = remove_collection_pokemon(
            {reservation_key(1, "Pikachu"): [456]},
            1,
            ["Pikachu", "Eevee"],
            123,
        )

        self.assertEqual(updated, {reservation_key(1, "Pikachu"): [456]})
        self.assertEqual(removed, [])
        self.assertEqual(missing, ["Pikachu", "Eevee"])

    def test_clear_user_collection_preserves_other_users_and_guilds(self) -> None:
        collections = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated = clear_user_collection(collections, 1, 123)

        self.assertEqual(
            updated,
            {
                reservation_key(1, "Pikachu"): [456],
                reservation_key(2, "Pikachu"): [123],
            },
        )

    def test_clear_guild_collection_preserves_other_guilds(self) -> None:
        collections = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [789],
            reservation_key(2, "Pikachu"): [123],
        }

        updated = clear_guild_collection(collections, 1)

        self.assertEqual(updated, {reservation_key(2, "Pikachu"): [123]})
        self.assertEqual(collections[reservation_key(1, "Pikachu")], [123, 456])

    def test_formats_collection_embed_and_paginates_at_twenty(self) -> None:
        embeds = format_collection_embeds(["eevee", "pikachu"])
        self.assertEqual(embeds[0].title, "Your Pokémon Collection")
        self.assertEqual(embeds[0].description, "eevee\npikachu")

        paged_embeds = format_collection_embeds(
            [f"pokemon{i}" for i in range(45)]
        )
        self.assertEqual(
            [len(embed_description(embed).splitlines()) for embed in paged_embeds],
            [20, 20, 5],
        )
        self.assertEqual(
            [embed.footer.text for embed in paged_embeds],
            ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"],
        )

    def test_formats_removal_confirmations(self) -> None:
        self.assertEqual(format_remove_confirmation("pikachu", None), "Pikachu removed")
        self.assertEqual(
            format_remove_confirmation("pikachu", "@Jade0319"),
            "Pikachu removed from @Jade0319 Reserves",
        )
        self.assertEqual(
            format_remove_confirmation("pikachu, eevee", "@Jade0319"),
            "Pikachu, Eevee removed from @Jade0319 Reserves",
        )
        self.assertEqual(
            format_remove_confirmation("all arceus", "@Jade0319"),
            "All forms of arceus removed from @Jade0319 Reserves",
        )

    def test_reservation_keys_are_case_insensitive(self) -> None:
        self.assertEqual(reservation_key(1, "Pikachu"), reservation_key(1, "PIKACHU"))
        self.assertNotEqual(reservation_key(1, "Pikachu"), reservation_key(2, "Pikachu"))
        self.assertEqual(reservation_key(1, "Raichu-Alola"), "1:raichu-alola")

    def test_all_forms_reservations_match_base_and_named_forms(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        for name in ("Arceus", "Arceus (Fire)", "Arceus-Fire", "Arceus Fire"):
            with self.subTest(name=name):
                self.assertEqual(
                    reserved_user_ids_for_pokemon(reservations, 1, name),
                    [123],
                )
        self.assertEqual(
            reserved_user_ids_for_pokemon(reservations, 2, "Arceus-Fire"),
            [],
        )
        self.assertEqual(
            reserved_user_ids_for_pokemon(reservations, 1, "Arceusian"),
            [],
        )
        self.assertTrue(
            pokemon_matches_all_forms_reservation("Raichu-Alola", "Raichu")
        )
        self.assertTrue(
            pokemon_matches_all_forms_reservation("Alolan Raichu", "Raichu")
        )
        self.assertTrue(
            pokemon_matches_all_forms_reservation(
                "Pikachu-Alola-Cap",
                "Pikachu",
            )
        )

    def test_custom_form_reservation_matches_only_that_form_and_base_reserves(self) -> None:
        reservations = {
            reservation_key(1, "Enchanted Applin"): [123],
            reservation_key(1, "Applin"): [456],
            reservation_key(1, "Rotten Applin"): [789],
        }

        self.assertEqual(
            reserved_user_ids_for_pokemon(
                reservations,
                1,
                "Applin",
                additional_names=("Enchanted Applin",),
            ),
            [123, 456],
        )
        self.assertEqual(
            reserved_user_ids_for_pokemon(reservations, 1, "Applin"),
            [456],
        )

    def test_all_forms_command_uses_a_separate_reservation_key(self) -> None:
        self.assertEqual(
            reservation_key_for_command(1, "all Arceus"),
            all_forms_reservation_key(1, "Arceus"),
        )
        self.assertEqual(
            reservation_key_for_command(1, "Arceus"),
            reservation_key(1, "Arceus"),
        )

    def test_all_forms_commands_cover_examples_and_remove_registration(self) -> None:
        self.assertTrue(is_known_pokemon_name("all Riffex"))
        self.assertEqual(
            reservation_key_for_command(1, "all Riffex"),
            all_forms_reservation_key(1, "Toxtricity"),
        )
        self.assertTrue(is_known_pokemon_name("all misipour"))
        self.assertEqual(
            reservation_key_for_command(1, "all misipour"),
            all_forms_reservation_key(1, "Simipour"),
        )

        collections = add_collection_pokemon({}, 1, ["all alcremie"], 123)
        self.assertEqual(
            collection_user_ids_for_pokemon(
                collections,
                1,
                "Ruby Cream Strawberry Sweet Alcremie",
            ),
            [123],
        )
        collections, removed, missing = remove_collection_pokemon(
            collections,
            1,
            ["all alcremie"],
            123,
        )
        self.assertEqual((removed, missing), (["all alcremie"], []))
        self.assertEqual(collections, {})

        shinyhunters = add_shinyhunter({}, 1, "all vivillon", 456)
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                shinyhunters,
                1,
                "Icy Snow Vivillon",
            ),
            [456],
        )
        shinyhunters, removed = remove_shinyhunter(
            shinyhunters,
            1,
            "all vivillon",
            456,
        )
        self.assertTrue(removed)
        self.assertEqual(shinyhunters, {})

        reservations = {
            reservation_key_for_command(1, "all Riffex"): [789]
        }
        self.assertEqual(
            reserved_user_ids_for_pokemon(
                reservations,
                1,
                "Low-Key Toxtricity",
            ),
            [789],
        )
        reservations, removed = remove_reservation(
            reservations,
            1,
            "all Riffex",
            789,
        )
        self.assertTrue(removed)
        self.assertEqual(reservations, {})

    def test_parses_one_valid_shinyhunt_name(self) -> None:
        self.assertEqual(parse_shinyhunt_command("v!sh Absol"), "Absol")

    def test_rejects_multiple_or_invalid_shinyhunt_names(self) -> None:
        self.assertIsNone(parse_shinyhunt_command("v!sh absol, eevee"))
        self.assertIsNone(parse_shinyhunt_command("v!sh absol!"))

    def test_parses_shinyhunt_removal_name(self) -> None:
        self.assertEqual(
            parse_shinyhunt_remove_command("v!sh remove Pikachu"),
            "Pikachu",
        )
        self.assertEqual(
            parse_shinyhunt_remove_command("v!sh remove all Arceus"),
            "all Arceus",
        )
        self.assertIsNone(parse_shinyhunt_remove_command("v!sh remove"))
        self.assertIsNone(
            parse_shinyhunt_remove_command("v!sh remove pikachu, eevee")
        )

    def test_shinyhunt_registration_replaces_only_that_users_previous_choice(
        self,
    ) -> None:
        shinyhunters = add_shinyhunter({}, 1, "Absol", 123)
        shinyhunters = add_shinyhunter(shinyhunters, 1, "Absol", 456)
        shinyhunters = add_shinyhunter(shinyhunters, 1, "Pikachu", 123)
        shinyhunters = add_shinyhunter(shinyhunters, 2, "Absol", 789)

        self.assertEqual(shinyhunters[reservation_key(1, "Absol")], [456])
        self.assertEqual(shinyhunters[reservation_key(1, "Pikachu")], [123])
        self.assertEqual(shinyhunters[reservation_key(2, "Absol")], [789])

    def test_shinyhunt_removal_only_removes_requesting_user(self) -> None:
        shinyhunters = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated, removed = remove_shinyhunter(shinyhunters, 1, "pikachu", 123)

        self.assertTrue(removed)
        self.assertEqual(
            updated,
            {
                reservation_key(1, "Pikachu"): [456],
                reservation_key(1, "Eevee"): [123],
                reservation_key(2, "Pikachu"): [123],
            },
        )
        self.assertEqual(shinyhunters[reservation_key(1, "Pikachu")], [123, 456])

    def test_shinyhunt_removal_reports_missing_selection(self) -> None:
        updated, removed = remove_shinyhunter(
            {reservation_key(1, "Pikachu"): [456]},
            1,
            "Pikachu",
            123,
        )

        self.assertFalse(removed)
        self.assertEqual(updated, {reservation_key(1, "Pikachu"): [456]})

    def test_clears_only_the_requesting_users_hunts_in_one_guild(self) -> None:
        shinyhunters = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [123],
            reservation_key(2, "Pikachu"): [123],
        }

        updated, cleared = clear_shinyhunter(shinyhunters, 1, 123)

        self.assertTrue(cleared)
        self.assertEqual(
            updated,
            {
                reservation_key(1, "Pikachu"): [456],
                reservation_key(2, "Pikachu"): [123],
            },
        )
        self.assertEqual(shinyhunters[reservation_key(1, "Pikachu")], [123, 456])

    def test_shinyhunt_clear_reports_when_no_hunt_was_found(self) -> None:
        shinyhunters = {reservation_key(1, "Pikachu"): [456]}

        updated, cleared = clear_shinyhunter(shinyhunters, 1, 123)

        self.assertFalse(cleared)
        self.assertEqual(updated, shinyhunters)

    def test_clear_guild_shinyhunts_preserves_other_guilds(self) -> None:
        shinyhunters = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [789],
            reservation_key(2, "Pikachu"): [123],
        }

        updated = clear_guild_shinyhunts(shinyhunters, 1)

        self.assertEqual(updated, {reservation_key(2, "Pikachu"): [123]})
        self.assertEqual(
            shinyhunters[reservation_key(1, "Pikachu")],
            [123, 456],
        )

    def test_shinyhunt_removal_supports_all_forms(self) -> None:
        shinyhunters = {
            all_forms_reservation_key(1, "Arceus"): [123, 456],
        }

        updated, removed = remove_shinyhunter(
            shinyhunters,
            1,
            "all arceus",
            123,
        )

        self.assertTrue(removed)
        self.assertEqual(
            updated,
            {all_forms_reservation_key(1, "Arceus"): [456]},
        )

    def test_all_forms_shinyhunt_matches_every_form_of_a_pokemon(self) -> None:
        shinyhunters = add_shinyhunter({}, 1, "all arceus", 123)

        self.assertEqual(
            shinyhunters,
            {all_forms_reservation_key(1, "Arceus"): [123]},
        )
        for form_name in ("Arceus", "Arceus-Fire", "Fairy Arceus"):
            with self.subTest(form_name=form_name):
                self.assertEqual(
                    shinyhunter_user_ids_for_pokemon(
                        shinyhunters,
                        1,
                        form_name,
                    ),
                    [123],
                )
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(shinyhunters, 2, "Arceus-Fire"),
            [],
        )

    def test_all_forms_shinyhunt_matches_catalogued_pichu_form(self) -> None:
        shinyhunters = add_shinyhunter({}, 1, "all pichu", 123)

        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                shinyhunters,
                1,
                "Spiky-eared Pichu",
            ),
            [123],
        )

    def test_formats_shinyhunt_status_in_lowercase(self) -> None:
        self.assertEqual(
            format_shinyhunt_status("Absol"),
            "You are currently shinyhunting absol",
        )
        self.assertEqual(
            format_shinyhunt_confirmation("Pikachu"),
            "You are now shinyhunting pikachu",
        )
        self.assertEqual(
            format_shinyhunt_confirmation("all arceus"),
            "You are now shinyhunting all forms of arceus",
        )
        self.assertEqual(
            format_shinyhunt_status("all arceus"),
            "You are currently shinyhunting all forms of arceus",
        )

    def test_lists_the_single_shinyhunt_pokemon_for_one_user_and_guild(self) -> None:
        shinyhunters = {
            reservation_key(1, "Absol"): [123, 456],
            reservation_key(1, "Eevee"): [456],
            reservation_key(1, "Pikachu"): [789],
            reservation_key(2, "Bulbasaur"): [123],
        }

        self.assertEqual(
            shinyhunt_pokemon_for_user(shinyhunters, 1, 123),
            ["absol"],
        )
        self.assertEqual(shinyhunt_pokemon_for_user(shinyhunters, 1, 999), [])
        all_forms = add_shinyhunter({}, 1, "all arceus", 123)
        self.assertEqual(
            shinyhunt_pokemon_for_user(all_forms, 1, 123),
            ["all arceus"],
        )

    def test_persists_shinyhunt_registrations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shinyhunts.json"
            shinyhunters = add_shinyhunter({}, 1, "Absol", 123)

            save_reservations(path, shinyhunters)

            self.assertEqual(load_reservations(path), shinyhunters)

    def test_saves_multiple_members_and_loads_them_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reserves.json"
            data = {reservation_key(1, "Pikachu"): [123, 456]}

            save_reservations(path, data)

            self.assertEqual(load_reservations(path), data)

    def test_parses_multiple_pokemon_names_and_member_mention(self) -> None:
        self.assertEqual(
            parse_reserve_add_command("v!r add pikachu, eevee <@319>"),
            (["pikachu", "eevee"], 319),
        )
        self.assertEqual(
            parse_reserve_add_command("v!r add all arceus <@319>"),
            (["all arceus"], 319),
        )

    def test_rejects_invalid_or_empty_names_in_multi_add(self) -> None:
        self.assertIsNone(parse_reserve_add_command("v!r add pikachu,,eevee <@319>"))
        self.assertIsNone(parse_reserve_add_command("v!r add pikachu! <@319>"))

    def test_parses_multiple_pokemon_names_for_removal(self) -> None:
        self.assertEqual(
            parse_reserve_remove_command("v!r remove pikachu, eevee <@319>"),
            (["pikachu", "eevee"], 319),
        )
        self.assertEqual(
            parse_reserve_remove_command("v!r remove pikachu, eevee, <@319>"),
            (["pikachu", "eevee"], 319),
        )
        self.assertEqual(
            parse_reserve_remove_command("v!r remove pikachu, eevee"),
            (["pikachu", "eevee"], None),
        )

    def test_rejects_invalid_or_empty_names_in_multi_remove(self) -> None:
        self.assertIsNone(parse_reserve_remove_command("v!r remove pikachu,,eevee"))
        self.assertIsNone(parse_reserve_remove_command("v!r remove pikachu!"))

    def test_search_lists_only_reservations_for_user_and_guild(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123],
            reservation_key(1, "Eevee"): [456],
            reservation_key(2, "Bulbasaur"): [123],
        }
        self.assertEqual(
            reserved_pokemon_for_user(reservations, 1, 123),
            ["pikachu"],
        )

    def test_member_reserve_list_labels_all_forms(self) -> None:
        reservations = {
            all_forms_reservation_key(1, "Marshadow"): [123],
            all_forms_reservation_key(1, "Urshifu"): [123],
        }

        self.assertEqual(
            reserved_pokemon_for_user(reservations, 1, 123),
            [
                "marshadow",
                "rapid strike gmax urshifu",
                "rapid strike urshifu",
                "single strike gmax urshifu",
                "single-strike urshifu",
                "zenith marshadow",
            ],
        )

    def test_removes_pokemon_reservation_for_one_user(self) -> None:
        reservations = {reservation_key(1, "Pikachu"): [123, 456]}

        updated, removed = remove_reservation(reservations, 1, "pikachu", 123)

        self.assertTrue(removed)
        self.assertEqual(updated, {reservation_key(1, "Pikachu"): [456]})
        self.assertEqual(reservations[reservation_key(1, "Pikachu")], [123, 456])

    def test_removes_pokemon_reservation_for_everyone(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(2, "Pikachu"): [789],
        }

        updated, removed = remove_reservation(reservations, 1, "Pikachu")

        self.assertTrue(removed)
        self.assertNotIn(reservation_key(1, "Pikachu"), updated)
        self.assertEqual(updated[reservation_key(2, "Pikachu")], [789])

    def test_removes_all_forms_reservation(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        updated, removed = remove_reservation(reservations, 1, "all arceus", 123)

        self.assertTrue(removed)
        self.assertEqual(updated, {})

    def test_removes_individually_reserved_forms_with_all_command(self) -> None:
        reservations = {
            reservation_key(1, "Simipour"): [123, 456],
            reservation_key(1, "Medusa Simipour"): [123],
            reservation_key(1, "Statue Simipour"): [456],
            all_forms_reservation_key(1, "Simipour"): [123],
            reservation_key(1, "Simisage"): [123],
            reservation_key(2, "Medusa Simipour"): [123],
        }

        updated, removed = remove_reservation(
            reservations, 1, "all simipour", 123
        )

        self.assertTrue(removed)
        self.assertEqual(
            updated,
            {
                reservation_key(1, "Simipour"): [456],
                reservation_key(1, "Statue Simipour"): [456],
                reservation_key(1, "Simisage"): [123],
                reservation_key(2, "Medusa Simipour"): [123],
            },
        )

    def test_removes_every_individual_form_reservation_with_all_command(self) -> None:
        reservations = {
            reservation_key(1, "Simipour"): [123],
            reservation_key(1, "Medusa Simipour"): [456],
            reservation_key(1, "Statue Simipour"): [789],
            reservation_key(1, "Simisage"): [123],
        }

        updated, removed = remove_reservation(reservations, 1, "all simipour")

        self.assertTrue(removed)
        self.assertEqual(updated, {reservation_key(1, "Simisage"): [123]})

    def test_clears_all_reservations_for_one_guild_only(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123, 456],
            reservation_key(1, "Eevee"): [789],
            reservation_key(2, "Bulbasaur"): [123],
        }

        updated = clear_guild_reservations(reservations, 1)

        self.assertEqual(updated, {reservation_key(2, "Bulbasaur"): [123]})
        self.assertEqual(len(reservations), 3)

    def test_does_not_report_removal_when_user_is_not_reserved(self) -> None:
        reservations = {reservation_key(1, "Pikachu"): [123]}

        updated, removed = remove_reservation(reservations, 1, "Pikachu", 456)

        self.assertFalse(removed)
        self.assertEqual(updated, reservations)

    def test_removes_multiple_pokemon_and_reports_missing_names(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123],
            reservation_key(1, "Eevee"): [123, 456],
            reservation_key(2, "Bulbasaur"): [123],
        }

        updated, removed, missing = remove_reservations(
            reservations,
            1,
            ["pikachu", "eevee", "bulbasaur"],
        )

        self.assertEqual(removed, ["pikachu", "eevee"])
        self.assertEqual(missing, ["bulbasaur"])
        self.assertEqual(updated, {reservation_key(2, "Bulbasaur"): [123]})
        self.assertIn(reservation_key(1, "Eevee"), reservations)

    def test_formats_reservation_embed_and_paginates_at_twenty_pokemon(self) -> None:
        embeds = format_reservation_embeds("Jade", ["eevee", "pikachu"])
        self.assertEqual(embeds[0].title, "Pokémon reserved by Jade")
        self.assertEqual(embeds[0].description, "Eevee\nPikachu")

        paged_embeds = format_reservation_embeds(
            "Jade",
            [f"pokemon{i}" for i in range(45)],
        )
        self.assertEqual(
            [len(embed_description(embed).splitlines()) for embed in paged_embeds],
            [20, 20, 5],
        )
        self.assertEqual(
            [embed.footer.text for embed in paged_embeds],
            ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"],
        )

    def test_formats_all_server_reserves_one_pokemon_user_per_line(self) -> None:
        reservations = {
            reservation_key(1, "Pikachu"): [123, 456, 123],
            reservation_key(1, "Scatterbug"): [789],
            reservation_key(2, "Eevee"): [123],
        }

        embeds = format_server_reservation_embeds(reservations, 1)

        self.assertEqual(len(embeds), 1)
        self.assertEqual(
            embeds[0].description,
            "pikachu <@123>\npikachu <@456>\nscatterbug <@789>",
        )

    def test_server_list_labels_all_forms_reservations(self) -> None:
        embeds = format_server_reservation_embeds(
            {
                all_forms_reservation_key(1, "Marshadow"): [123],
                all_forms_reservation_key(1, "Zacian"): [456],
            },
            1,
        )

        self.assertEqual(
            embeds[0].description,
            "crowned zacian <@456>\n"
            "marshadow <@123>\n"
            "zacian <@456>\n"
            "zenith marshadow <@123>",
        )

    def test_formats_empty_server_reserve_list(self) -> None:
        embeds = format_server_reservation_embeds(
            {reservation_key(2, "Eevee"): [123]},
            1,
        )

        self.assertEqual(
            embeds[0].description,
            "There are no Pokémon reservations in this server.",
        )

    def test_formats_reserve_search_with_all_users_for_pokemon(self) -> None:
        reservations = {
            reservation_key(1, "Scatterbug"): [456, 123, 456],
            reservation_key(2, "Scatterbug"): [789],
        }

        embeds = format_pokemon_reserver_embeds(reservations, 1, "scatterbug")

        self.assertEqual(embeds[0].title, "Reserve search: scatterbug")
        self.assertEqual(
            embeds[0].description,
            "scatterbug <@123>\nscatterbug <@456>",
        )

    def test_search_includes_reservations_for_all_forms(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [123]}

        embeds = format_pokemon_reserver_embeds(
            reservations,
            1,
            "Arceus (Fire)",
        )

        self.assertEqual(
            embeds[0].description,
            "Arceus (Fire) <@123>",
        )

    def test_all_forms_search_lists_each_reserved_form_and_reservers(self) -> None:
        reservations = {
            reservation_key(1, "Arceus"): [456],
            reservation_key(1, "Arceus (Fire)"): [789],
            reservation_key(1, "Arceus-Water"): [987],
            all_forms_reservation_key(1, "Arceus"): [123],
            reservation_key(1, "Pikachu"): [321],
            reservation_key(2, "Arceus (Grass)"): [654],
        }

        embeds = format_all_forms_reservation_embeds(
            reservations,
            1,
            "Arceus",
        )

        rows = set("\n".join(embed_description(embed) for embed in embeds).splitlines())
        self.assertEqual(
            rows,
            {
                "normal arceus <@123>",
                "normal arceus <@456>",
                "fire arceus <@123>",
                "fire arceus <@789>",
                "water arceus <@123>",
                "water arceus <@987>",
                "electric arceus <@123>",
                "grass arceus <@123>",
                "ice arceus <@123>",
                "fighting arceus <@123>",
                "poison arceus <@123>",
                "ground arceus <@123>",
                "flying arceus <@123>",
                "psychic arceus <@123>",
                "bug arceus <@123>",
                "rock arceus <@123>",
                "ghost arceus <@123>",
                "dragon arceus <@123>",
                "dark arceus <@123>",
                "steel arceus <@123>",
                "fairy arceus <@123>",
            },
        )

    def test_all_forms_search_lists_each_arceus_type_for_all_forms_reserver(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {all_forms_reservation_key(1, "Arceus"): [123]},
            1,
            "Arceus",
        )

        lines = "\n".join(embed_description(embed) for embed in embeds).splitlines()
        self.assertEqual(len(lines), 18)
        self.assertEqual(lines[0], "normal arceus <@123>")
        self.assertEqual(lines[-1], "fairy arceus <@123>")

    def test_all_forms_search_lists_only_exactly_reserved_types_without_wildcard(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {
                reservation_key(1, "Arceus (Ghost)"): [123],
                reservation_key(1, "Arceus-Fairy"): [456],
            },
            1,
            "Arceus",
        )

        rows = "\n".join(embed_description(embed) for embed in embeds).splitlines()
        self.assertEqual(len(rows), 18)
        self.assertIn("ghost arceus <@123>", rows)
        self.assertIn("fairy arceus <@456>", rows)
        self.assertIn("normal arceus", rows)

    def test_all_forms_search_includes_custom_forms_and_base_species(self) -> None:
        for species, event_forms in (
            ("Applin", ("Enchanted Applin", "Rotten Applin")),
            ("Simipour", ("Medusa Simipour", "Statue Simipour")),
        ):
            with self.subTest(species=species):
                embeds = format_all_forms_reservation_embeds(
                    {all_forms_reservation_key(1, species): [123]},
                    1,
                    species,
                )

                rows = (
                    "\n".join(embed_description(embed) for embed in embeds)
                    .casefold()
                    .splitlines()
                )
                self.assertIn(f"{species.casefold()} <@123>", rows)
                for event_form in event_forms:
                    self.assertIn(f"{event_form.casefold()} <@123>", rows)

    def test_all_forms_search_lists_pichu_forms_and_reserver(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {all_forms_reservation_key(1, "Pichu"): [123]},
            1,
            "Pichu",
        )

        self.assertEqual(
            embeds[0].description,
            "pichu <@123>\nspiky-eared pichu <@123>",
        )

    def test_all_forms_search_includes_regional_forms(self) -> None:
        embeds = format_all_forms_reservation_embeds(
            {
                all_forms_reservation_key(1, "Raichu"): [123],
                reservation_key(1, "Raichu-Alola"): [456],
            },
            1,
            "Raichu",
        )

        description = "\n".join(embed_description(embed) for embed in embeds)
        self.assertIn("raichu <@123>", description)
        self.assertIn("mega-x raichu <@123>", description)
        regional_rows = [
            row for row in description.splitlines() if "alola" in row
        ]
        self.assertTrue(regional_rows)
        self.assertTrue(any("<@123>" in row for row in regional_rows))
        self.assertTrue(any("<@456>" in row for row in regional_rows))


    def test_all_forms_search_paginates_form_entries_at_twenty(self) -> None:
        reservations = {all_forms_reservation_key(1, "Arceus"): [1, 2]}

        embeds = format_all_forms_reservation_embeds(
            reservations,
            1,
            "Arceus",
        )

        self.assertEqual(
            [len(embed_description(embed).splitlines()) for embed in embeds],
            [20, 16],
        )
        self.assertEqual(
            [embed.footer.text for embed in embeds],
            ["Page 1 of 2", "Page 2 of 2"],
        )

    def test_loads_non_regional_form_catalog(self) -> None:
        forms = load_pokemon_forms(Path(__file__).with_name("pokemon_forms.json"))

        self.assertEqual(forms["pichu"][1]["display_name"], "spiky-eared pichu")
        self.assertEqual(forms["raichu"][1]["display_name"], "Alolan Raichu")
        self.assertEqual(forms["meowth"][3]["display_name"], "Galarian Meowth")
        self.assertEqual(forms["raichu"][1]["identifier"], "raichu-alola")
        self.assertEqual(forms["arceus"][0]["identifier"], "arceus-normal")
        self.assertEqual(forms["arceus"][0]["display_name"], "normal arceus")
        self.assertFalse(
            any(form["identifier"] == "arceus-unknown" for form in forms["arceus"])
        )

    def test_regional_name_variants_use_demonyms(self) -> None:
        from image_match import canonicalize_regional_name

        for alias, expected in (
            ("Alola Sandslash", "Alolan Sandslash"),
            ("Raichu-Alola", "Alolan Raichu"),
            ("Galar Slowbro", "Galarian Slowbro"),
            ("Darmanitan-Galar-Zen", "Galarian Zen Darmanitan"),
            ("Hisui Sneasel", "Hisuian Sneasel"),
        ):
            with self.subTest(alias=alias):
                self.assertEqual(canonicalize_regional_name(alias), expected)
                self.assertEqual(bot_module.display_pokemon_name(alias), expected)

    def test_formats_reserve_search_when_pokemon_is_not_reserved(self) -> None:
        embeds = format_pokemon_reserver_embeds({}, 1, "scatterbug")

        self.assertEqual(
            embeds[0].description,
            "No one has scatterbug reserved.",
        )

    def test_paginates_reserve_search_at_twenty_users(self) -> None:
        reservations = {
            reservation_key(1, "scatterbug"): list(range(45))
        }

        embeds = format_pokemon_reserver_embeds(
            reservations,
            1,
            "scatterbug",
        )

        self.assertEqual(
            [len(embed_description(embed).splitlines()) for embed in embeds],
            [20, 20, 5],
        )

    def test_paginates_server_reserve_list_at_twenty_entries(self) -> None:
        reservations = {
            reservation_key(1, f"pokemon{i}"): [i]
            for i in range(45)
        }

        embeds = format_server_reservation_embeds(reservations, 1)

        self.assertEqual(
            [len(embed_description(embed).splitlines()) for embed in embeds],
            [20, 20, 5],
        )
        self.assertEqual(
            [embed.footer.text for embed in embeds],
            ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"],
        )

    def test_reserve_page_view_enables_arrows_for_available_pages(self) -> None:
        embeds = [
            discord.Embed(description="Page 1"),
            discord.Embed(description="Page 2"),
        ]
        view = ReservationPagesView(embeds, guild_id=1)

        buttons = {runtime_attribute(button, "custom_id"): button for button in view.children}
        self.assertTrue(runtime_attribute(buttons["reserve_pages:previous"], "disabled"))
        self.assertFalse(runtime_attribute(buttons["reserve_pages:next"], "disabled"))

        view.current_page = 1
        view.update_buttons()
        self.assertFalse(runtime_attribute(buttons["reserve_pages:previous"], "disabled"))
        self.assertTrue(runtime_attribute(buttons["reserve_pages:next"], "disabled"))


class ReserveCategoryTests(unittest.TestCase):
    def test_parses_category_commands(self) -> None:
        self.assertEqual(
            parse_add_reserve_category_command("v!addcategory Rare"),
            "Rare",
        )
        self.assertEqual(
            parse_create_reserve_category_command(
                "v!categorycreate rare pikachu, eevee, Riffex"
            ),
            ("rare", ["pikachu", "eevee", "toxtricity"]),
        )
        self.assertEqual(
            parse_delete_reserve_category_command("v!cd rare"),
            "rare",
        )
        self.assertEqual(
            parse_delete_reserve_category_command("v!categorydelete rare"),
            "rare",
        )
        self.assertIsNone(
            parse_create_reserve_category_command(
                "v!categorycreate rare pikachu,,eevee"
            )
        )

    def test_categories_append_deduplicate_and_expand_per_server(self) -> None:
        categories, created = add_reserve_category({}, 1, "Rare")
        self.assertTrue(created)
        categories, added, exists = append_reserve_category_pokemon(
            categories,
            1,
            "rare",
            ["Pikachu", "Eevee", "Riffex"],
        )
        self.assertTrue(exists)
        self.assertEqual(added, ["Pikachu", "Eevee", "toxtricity"])

        categories, added, exists = append_reserve_category_pokemon(
            categories,
            1,
            "rare",
            ["pikachu"],
        )
        self.assertTrue(exists)
        self.assertEqual(added, [])
        self.assertEqual(
            expand_reserve_category_names(categories, 1, ["rare", "pikachu"]),
            (["Pikachu", "Eevee", "toxtricity"], ["rare"]),
        )
        self.assertEqual(
            expand_reserve_category_names(categories, 2, ["rare"]),
            (["rare"], []),
        )

    def test_category_listing_and_persistence(self) -> None:
        categories = {
            "1": {"rare": ["pikachu", "eevee"], "shiny": ["all arceus"]}
        }
        embeds = format_reserve_category_embeds(categories, 1)
        self.assertEqual(
            embeds[0].description,
            "rare\n2 Pokémon\n\nshiny\n1 Pokémon",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reserve_categories.json"
            save_reserve_categories(path, categories)
            self.assertEqual(load_reserve_categories(path), categories)

    def test_deleting_a_category_is_server_scoped(self) -> None:
        categories = {
            "1": {"rare": ["pikachu"]},
            "2": {"rare": ["eevee"]},
        }

        updated, deleted = delete_reserve_category(categories, 1, "RARE")

        self.assertTrue(deleted)
        self.assertEqual(updated, {"2": {"rare": ["eevee"]}})


class ReserveCategoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_remove_all_species_forms_without_an_all_forms_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bot = SimpleNamespace(
                reserve_categories={},
                reservations={
                    "1:simipour": [123],
                    "1:medusa simipour": [456],
                    "1:statue simipour": [123],
                    "1:simisage": [123],
                },
                reserve_path=Path(directory) / "reserves.json",
            )
            message = Mock()
            message.guild.id = 1
            message.author = Mock(spec=discord.Member)
            message.content = "v!r remove all simipour"
            message.mentions = []
            message.reply = AsyncMock()

            await NamingBot.handle_reserve_remove(cast(NamingBot, bot), message)

            self.assertEqual(bot.reservations, {"1:simisage": [123]})
            message.reply.assert_awaited_once()

    async def test_member_can_view_own_reserves_without_manager_role(self) -> None:
        bot = SimpleNamespace(
            command_permissions={"1": 900},
            reservations={"1:pikachu": [123], "1:eevee": [456]},
        )
        message = Mock()
        message.guild.id = 1
        message.author = Mock(spec=discord.Member)
        message.author.id = 123
        message.author.display_name = "Test member"
        message.author.roles = []
        message.content = "v!r <@!123>"
        message.reply = AsyncMock()

        with patch("bot.reply_with_reservation_embeds", new=AsyncMock()) as reply:
            await NamingBot.handle_reserve_command(
            cast(NamingBot, bot), message)

            reply.assert_awaited_once()
            embeds = awaited_args(reply)[1]
            self.assertEqual(embeds[0].title, "Pokémon reserved by Test member")
            self.assertEqual(embeds[0].description, "Pikachu")

            message.content = "v!r <@456>"
            await NamingBot.handle_reserve_command(
            cast(NamingBot, bot), message)

        message.reply.assert_awaited_once_with(
            "Only reserve managers or members with the configured "
            "command role can add, remove, or clear reservations.",
            mention_author=False,
        )

    async def test_configured_role_can_add_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            role_id = 900
            bot = SimpleNamespace(
                command_permissions={"1": role_id},
                reserve_categories={},
                reservations={},
                reserve_path=Path(directory) / "reserves.json",
            )
            message = Mock()
            message.guild.id = 1
            message.author = Mock(spec=discord.Member)
            message.author.roles = [Mock(id=role_id)]
            message.content = "v!r add pikachu <@123>"
            target = Mock()
            target.id = 123
            target.mention = "<@123>"
            message.mentions = [target]
            message.reply = AsyncMock()

            await NamingBot.handle_reserve_command(
            cast(NamingBot, bot), message)

            self.assertEqual(bot.reservations, {"1:pikachu": [123]})

    async def test_vr_all_resumes_only_current_server_channels(self) -> None:
        role_id = 900
        guild = SimpleNamespace(id=1)
        channel = SimpleNamespace(id=10, guild=guild)
        thread = SimpleNamespace(id=11, guild=guild)
        guild_channels = {10: channel}
        guild.get_channel = guild_channels.get
        guild.get_thread = lambda channel_id: thread if channel_id == 11 else None
        bot = SimpleNamespace(
            command_permissions={"1": role_id},
            reservations={},
            muted_poketwo_channels={10, 11, 20},
            set_poketwo_blocked=AsyncMock(return_value=True),
        )
        message = Mock()
        message.guild = guild
        message.author = Mock(spec=discord.Member)
        message.author.id = 456
        message.author.roles = [Mock(id=role_id)]
        message.content = "v!r all"
        message.reply = AsyncMock()

        await NamingBot.handle_reserve_command(
            cast(NamingBot, bot), message)

        self.assertEqual(bot.muted_poketwo_channels, {20})
        self.assertEqual(
            bot.set_poketwo_blocked.await_args_list,
            [call(channel, False), call(thread, False)],
        )
        message.reply.assert_awaited_once_with(
            "Resumed Pokétwo in 2 paused channel(s).",
            mention_author=False,
        )

    async def test_all_applin_reserve_asks_event_forms_or_all_forms(self) -> None:
        for choice, expected in (
            (
                "Event forms only",
                {
                    reservation_key(1, "Enchanted Applin"): [123],
                    reservation_key(1, "Rotten Applin"): [123],
                },
            ),
            (
                "All forms",
                {all_forms_reservation_key(1, "Applin"): [123]},
            ),
        ):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                role_id = 900
                bot = SimpleNamespace(
                    command_permissions={"1": role_id},
                    reserve_categories={},
                    reservations={},
                    reserve_path=Path(directory) / "reserves.json",
                )
                message = Mock()
                message.guild.id = 1
                message.author = Mock(spec=discord.Member)
                message.author.id = 456
                message.author.roles = [Mock(id=role_id)]
                message.content = "v!r add all applin <@123>"
                target = Mock()
                target.id = 123
                target.mention = "<@123>"
                message.mentions = [target]
                message.reply = AsyncMock()

                await NamingBot.handle_reserve_command(
            cast(NamingBot, bot), message)

                self.assertEqual(bot.reservations, {})
                view = awaited_kwargs(message.reply)["view"]
                interaction = Mock()
                interaction.guild_id = 1
                interaction.user = Mock(spec=discord.Member)
                interaction.user.id = message.author.id
                interaction.user.roles = [Mock(id=role_id)]
                interaction.response.edit_message = AsyncMock()
                interaction.response.send_message = AsyncMock()
                self.assertTrue(await view.interaction_check(interaction))
                button = next(
                    button
                    for button in view.children
                    if button.label == choice
                )
                await button.callback(interaction)

                self.assertEqual(bot.reservations, expected)

    async def test_unknown_pokemon_cannot_be_added_to_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            role_id = 900
            bot = SimpleNamespace(
                command_permissions={"1": role_id},
                reserve_categories={},
                reservations={},
                reserve_path=Path(directory) / "reserves.json",
            )
            message = Mock()
            message.guild.id = 1
            message.author = Mock(spec=discord.Member)
            message.author.roles = [Mock(id=role_id)]
            message.content = "v!r add towel <@123>"
            target = Mock()
            target.id = 123
            target.mention = "<@123>"
            message.mentions = [target]
            message.reply = AsyncMock()

            await NamingBot.handle_reserve_command(
            cast(NamingBot, bot), message)

            self.assertEqual(bot.reservations, {})
            self.assertFalse(bot.reserve_path.exists())
            message.reply.assert_awaited_once_with(
                "Unknown Pokémon: towel.",
                mention_author=False,
            )

    async def test_reserve_search_rejects_unknown_pokemon_name(self) -> None:
        bot = SimpleNamespace(reservations={})
        message = Mock()
        message.guild.id = 1
        message.content = "v!r search towel"
        message.mentions = []
        message.reply = AsyncMock()

        await NamingBot.handle_reserve_search(
            cast(NamingBot, bot), message)

        message.reply.assert_awaited_once_with(
            "**towel** is not a valid Pokémon name.",
            mention_author=False,
        )

    async def test_reserve_add_and_remove_expand_category_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bot = SimpleNamespace(
                reserve_categories={"1": {"rare": ["pikachu", "eevee"]}},
                reservations={},
                reserve_path=Path(directory) / "reserves.json",
            )

            async def handle_remove(message: Mock) -> None:
                await NamingBot.handle_reserve_remove(
            cast(NamingBot, bot), message)

            bot.handle_reserve_remove = handle_remove

            def reserve_message(content: str) -> Mock:
                message = Mock()
                message.guild.id = 1
                message.author = Mock(spec=discord.Member)
                message.author.roles = [Mock(id=RESERVE_ROLE_ID)]
                message.content = content
                target = Mock()
                target.id = 123
                target.mention = "<@123>"
                message.mentions = [target]
                message.reply = AsyncMock()
                return message

            await NamingBot.handle_reserve_command(
                cast(NamingBot, bot),
                reserve_message("v!r add rare <@123>"),
            )
            self.assertEqual(
                bot.reservations,
                {"1:pikachu": [123], "1:eevee": [123]},
            )

            await NamingBot.handle_reserve_command(
                cast(NamingBot, bot),
                reserve_message("v!r remove rare <@123>"),
            )
            self.assertEqual(bot.reservations, {})

    async def test_only_reserve_managers_can_manage_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bot = Mock()
            bot.reserve_categories = {}
            bot.reserve_categories_path = Path(directory) / "categories.json"
            message = Mock()
            message.guild.id = 1
            message.author.roles = [Mock(id=RESERVE_ROLE_ID + 1)]
            message.content = "v!addcategory rare"
            message.reply = AsyncMock()

            await NamingBot.handle_reserve_category_command(
            cast(NamingBot, bot), message)

            message.reply.assert_awaited_once_with(
                "Only reserve managers or members with the configured "
                "command role can manage reserve categories.",
                mention_author=False,
            )
            self.assertEqual(bot.reserve_categories, {})

    async def test_create_append_and_delete_category_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bot = Mock()
            bot.reserve_categories = {}
            bot.reserve_categories_path = Path(directory) / "categories.json"
            message = Mock()
            message.guild.id = 1
            message.author.roles = [Mock(id=RESERVE_ROLE_ID)]
            message.reply = AsyncMock()

            message.content = "v!addcategory rare"
            await NamingBot.handle_reserve_category_command(
            cast(NamingBot, bot), message)
            self.assertEqual(bot.reserve_categories, {"1": {"rare": []}})

            message.content = "v!categorycreate rare pikachu, eevee"
            await NamingBot.handle_reserve_category_command(
            cast(NamingBot, bot), message)
            self.assertEqual(
                bot.reserve_categories,
                {"1": {"rare": ["pikachu", "eevee"]}},
            )
            self.assertEqual(
                load_reserve_categories(bot.reserve_categories_path),
                bot.reserve_categories,
            )

            message.content = "v!cd rare"
            await NamingBot.handle_reserve_category_command(
            cast(NamingBot, bot), message)
            self.assertEqual(bot.reserve_categories, {})


class CommandPermissionTests(unittest.TestCase):
    def test_lists_commands_that_use_the_configured_role(self) -> None:
        commands = {
            "v!grab": "general",
            "v!test shiny": "general",
            "v!r search pikachu": None,
            "v!r <@100>": None,
            "v!r": "reserves",
            "v!p": "reserves",
            "v!p all": "reserves",
            "v!pause": "reserves",
            "v!pause all": "reserves",
            "v!q": None,
            "v!cd rare": "reserves",
            "v!settings": "settings",
            "v!settime @role": "general",
            "v!timereset": "general",
            "v!event": "general",
            "v!backfill stop": "backfill",
            "v!backfill <#789>": "backfill",
            "v!backfill 789": "backfill",
        }
        for command, expected_group in commands.items():
            with self.subTest(command=command):
                self.assertEqual(command_permission_group(command), expected_group)
        self.assertIsNone(command_permission_group("v!lowaccuracy off"))
        self.assertIsNone(command_permission_group("v!sh pikachu"))

    def test_all_forms_lists_custom_forms_without_catalog_entry(self) -> None:
        self.assertEqual(
            format_reserved_pokemon_names("all applin"),
            ["applin", "enchanted applin", "rotten applin"],
        )

    def test_collection_pings_for_custom_form_shown_name(self) -> None:
        collections = {reservation_key(1, "oracle meowscarada"): [5]}
        self.assertEqual(
            collection_user_ids_for_pokemon(
                collections,
                1,
                "Meowscarada",
                additional_names=("Oracle Meowscarada",),
            ),
            [5],
        )

    def test_custom_forms_ping_all_lists(self) -> None:
        forms = {
            "enchanted applin": "Applin",
            "rotten applin": "Applin",
            "madusa simipour": "Simipour",
            "statue simipour": "Simipour",
            "elixir reuniclus": "Reuniclus",
            "cauldron reuniclus": "Reuniclus",
            "oracle meowscarada": "Meowscarada",
            "witch meowscarada": "Meowscarada",
        }
        shown = {"madusa simipour": "Medusa Simipour"}
        for typed, species in forms.items():
            data = {reservation_key_for_command(1, typed): [5]}
            guess = shown.get(typed, typed.title())
            for lookup in (
                reserved_user_ids_for_pokemon,
                shinyhunter_user_ids_for_pokemon,
                collection_user_ids_for_pokemon,
            ):
                with self.subTest(typed=typed, lookup=lookup.__name__):
                    self.assertEqual(
                        lookup(data, 1, species, additional_names=(guess,)), [5]
                    )

    def test_shinyhunt_pings_for_custom_form_shown_name(self) -> None:
        shinyhunters = {reservation_key(1, "oracle meowscarada"): [5]}
        self.assertEqual(
            shinyhunter_user_ids_for_pokemon(
                shinyhunters,
                1,
                "Meowscarada",
                additional_names=("Oracle Meowscarada",),
            ),
            [5],
        )

    def test_privileged_manager_only_has_access_in_their_guild(self) -> None:
        guild_id, user_id = next(iter(bot_module.PRIVILEGED_MANAGER_IDS.items()))
        home = SimpleNamespace(id=guild_id)
        elsewhere = SimpleNamespace(id=guild_id + 1)
        manager = SimpleNamespace(id=user_id, guild=home, roles=[])
        away = SimpleNamespace(id=user_id, guild=elsewhere, roles=[])
        stranger = SimpleNamespace(id=user_id + 1, guild=home, roles=[])
        self.assertTrue(
            require_not_none(bot_module.member_guild_permissions(manager)).administrator
        )
        self.assertIsNone(bot_module.member_guild_permissions(away))
        self.assertIsNone(bot_module.member_guild_permissions(stranger))
        bot = SimpleNamespace(command_permissions={str(guild_id): 900})
        for group in ("general", "reserves", "settings", "backfill"):
            self.assertTrue(can_use_permission_group(bot, group, guild_id, manager))
            self.assertFalse(can_use_permission_group(bot, group, guild_id, away))
            self.assertFalse(can_use_permission_group(bot, group, guild_id, stranger))

    def test_premium_only_commands(self) -> None:
        for command in ("v!grab", "v!r add pikachu <@1>", "v!r e <@1>", "v!r exchange <@1>"):
            with self.subTest(command=command):
                self.assertTrue(is_premium_only_command(command))
        for command in ("v!r search pikachu", "v!r", "v!settings"):
            with self.subTest(command=command):
                self.assertFalse(is_premium_only_command(command))

    def test_premium_server_owner_can_use_every_permission_group(self) -> None:
        guild = SimpleNamespace(id=42, owner_id=7)
        owner = SimpleNamespace(id=7, guild=guild, roles=[])
        other = SimpleNamespace(id=8, guild=guild, roles=[])
        premium = SimpleNamespace(
            command_permissions={"42": 900},
            premium_tier_for_guild=lambda guild_id: "gold",
        )
        free = SimpleNamespace(
            command_permissions={"42": 900},
            premium_tier_for_guild=lambda guild_id: None,
        )
        for group in ("general", "reserves", "settings", "backfill"):
            with self.subTest(group=group):
                self.assertTrue(can_use_permission_group(premium, group, 42, owner))
                self.assertFalse(can_use_permission_group(premium, group, 42, other))
                self.assertFalse(can_use_permission_group(free, group, 42, owner))

    def test_configured_role_adds_access_without_removing_existing_access(self) -> None:
        role_id = 900
        bot = SimpleNamespace(command_permissions={"42": role_id})

        def member(*, roles=(), manage_guild=False, administrator=False):
            return SimpleNamespace(
                roles=[SimpleNamespace(id=value) for value in roles],
                guild_permissions=SimpleNamespace(
                    manage_guild=manage_guild,
                    administrator=administrator,
                ),
            )

        self.assertFalse(
            can_use_permission_group(bot, "general", 42, member())
        )
        self.assertTrue(
            can_use_permission_group(bot, "general", 42, member(roles=(role_id,)))
        )
        self.assertTrue(
            can_use_permission_group(
                bot,
                "reserves",
                42,
                member(roles=(RESERVE_ROLE_ID,)),
            )
        )
        self.assertTrue(
            can_use_permission_group(
                bot,
                "settings",
                42,
                member(manage_guild=True),
            )
        )
        self.assertTrue(
            can_use_permission_group(
                bot,
                "settings",
                42,
                member(roles=(role_id,)),
            )
        )
        self.assertTrue(
            can_use_permission_group(
                bot,
                "backfill",
                42,
                member(administrator=True),
            )
        )
        self.assertTrue(
            can_use_permission_group(
                bot,
                "backfill",
                42,
                member(roles=(role_id,)),
            )
        )
        self.assertTrue(
            has_manage_server_access(
                bot,
                42,
                member(roles=(role_id,)),
            )
        )
        self.assertTrue(
            can_use_permission_group(
                SimpleNamespace(command_permissions={}),
                "general",
                42,
                member(),
            )
        )

    def test_command_permission_file_round_trips_per_server_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "command_permissions.json"
            expected = {"42": 900, "43": 901}

            save_command_permissions(path, expected)

            self.assertEqual(load_command_permissions(path), expected)


class CommandLockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.bot = NamingBot(ConfigTests().load_config())
        self.bot.command_locks_path = Path(self.directory.name) / "locks.json"
        self.bot.command_locks = {}
        self.bot.track_incense_command = Mock()
        self.bot.track_chat_event_message = Mock()

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self.directory.cleanup()

    def message(
        self,
        content: str,
        *,
        administrator: bool = False,
        author_id: int = 123,
        author_is_bot: bool = False,
    ) -> Mock:
        message = Mock()
        message.content = content
        message.guild.id = SERVER_ID
        message.channel.id = 456
        message.channel.guild.id = SERVER_ID
        message.author.id = author_id
        message.author.bot = author_is_bot
        message.author.guild_permissions.administrator = administrator
        message.author.roles = []
        message.embeds = []
        message.attachments = []
        message.reply = AsyncMock()
        return message

    async def test_admin_lock_blocks_commands_until_admin_reenables_them(self) -> None:
        member_lock = self.message("v!coff")

        await self.bot.on_message(member_lock)

        self.assertIn("Only server administrators", member_lock.reply.await_args.args[0])
        self.assertFalse(self.bot.commands_locked_for_guild(SERVER_ID))

        admin_lock = self.message("v!coff", administrator=True)
        await self.bot.on_message(admin_lock)

        self.assertTrue(self.bot.commands_locked_for_guild(SERVER_ID))
        self.assertEqual(
            load_command_locks(self.bot.command_locks_path),
            {str(SERVER_ID): True},
        )

        blocked_command = self.message("v!ping")
        self.bot.handle_ping_command = AsyncMock()
        await self.bot.on_message(blocked_command)

        self.assertIn("disabled", blocked_command.reply.await_args.args[0])
        self.bot.handle_ping_command.assert_not_awaited()

        member_unlock = self.message("v!con")
        await self.bot.on_message(member_unlock)

        self.assertIn("Only server administrators", member_unlock.reply.await_args.args[0])
        self.assertTrue(self.bot.commands_locked_for_guild(SERVER_ID))

        admin_unlock = self.message("v!con", administrator=True)
        await self.bot.on_message(admin_unlock)

        self.assertFalse(self.bot.commands_locked_for_guild(SERVER_ID))
        self.assertEqual(load_command_locks(self.bot.command_locks_path), {})

    async def test_support_command_shows_gofundme_button(self) -> None:
        message = self.message("V!SUPPORT ")
        await self.bot.on_message(message)

        kwargs = awaited_kwargs(message.reply)
        self.assertIn("optional", kwargs["embed"].description)
        self.assertIn("<a:emoji_27:1534340529192697959>", kwargs["embed"].description)
        self.assertEqual(kwargs["view"].children[0].url, "https://gofund.me/a71832b06")
        self.assertEqual(kwargs["view"].children[0].label, "Donate on GoFundMe")

    async def test_support_falls_back_to_text_without_embed_permission(self) -> None:
        message = self.message("v!support")
        forbidden = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions"
        )
        message.reply.side_effect = [forbidden, None]

        await self.bot.on_message(message)

        self.assertEqual(message.reply.await_count, 2)
        self.assertIn("https://gofund.me/a71832b06", message.reply.await_args.args[0])

    async def test_support_command_respects_command_lock(self) -> None:
        self.bot.set_commands_locked(SERVER_ID, True)
        message = self.message("v!support")

        await self.bot.on_message(message)

        self.assertIn("disabled", message.reply.await_args.args[0])

    async def test_command_lock_does_not_stop_automatic_spawn_handling(self) -> None:
        self.bot.set_commands_locked(SERVER_ID, True)
        self.bot.track_profile_catch = Mock()
        self.bot.track_profile_box_shiny = AsyncMock()
        self.bot.handle_catch_starboard = AsyncMock()
        self.bot.handle_spawn = AsyncMock()
        message = self.message(
            "A wild Pokémon has appeared!",
            author_id=self.bot.config.poketwo_bot_id,
            author_is_bot=True,
        )

        await self.bot.on_message(message)

        cast(AsyncMock, self.bot.handle_spawn).assert_awaited_once_with(message)


class CommandPermissionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_manage_server_can_set_and_clear_the_server_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bot = SimpleNamespace(
                command_permissions={},
                command_permissions_path=Path(directory) / "permissions.json",
            )
            guild = Mock()
            guild.id = SERVER_ID
            role = Mock()
            role.id = 900
            guild.get_role = Mock(return_value=role)
            message = Mock()
            message.guild = guild
            message.author.guild_permissions.manage_guild = True
            message.reply = AsyncMock()
            message.content = "v!permission 900"

            await NamingBot.handle_permission_command(
            cast(NamingBot, bot), message)

            expected = {str(SERVER_ID): 900}
            self.assertEqual(bot.command_permissions, expected)
            self.assertEqual(load_command_permissions(bot.command_permissions_path), expected)

            message.content = "v!permission off"
            await NamingBot.handle_permission_command(
            cast(NamingBot, bot), message)

            self.assertEqual(bot.command_permissions, {})
            self.assertEqual(load_command_permissions(bot.command_permissions_path), {})

    async def test_non_manager_cannot_change_the_permission_role(self) -> None:
        bot = SimpleNamespace(
            command_permissions={},
            command_permissions_path=Path("unused-permissions.json"),
        )
        message = Mock()
        message.guild.id = SERVER_ID
        message.author.guild_permissions.manage_guild = False
        message.content = "v!permission 900"
        message.reply = AsyncMock()

        await NamingBot.handle_permission_command(
            cast(NamingBot, bot), message)

        self.assertIn(
            "Manage Server permission",
            message.reply.await_args.args[0],
        )
        self.assertEqual(bot.command_permissions, {})

    async def test_configured_role_can_manage_reserve_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            role_id = 900
            bot = SimpleNamespace(
                command_permissions={str(SERVER_ID): role_id},
                reserve_categories={},
                reserve_categories_path=Path(directory) / "categories.json",
            )
            message = Mock()
            message.guild.id = SERVER_ID
            message.author.roles = [Mock(id=role_id)]
            message.content = "v!addcategory rare"
            message.reply = AsyncMock()

            await NamingBot.handle_reserve_category_command(
            cast(NamingBot, bot), message)

            self.assertEqual(
                bot.reserve_categories,
                {str(SERVER_ID): {"rare": []}},
            )

    async def test_configured_role_can_stop_profile_backfill(self) -> None:
        role_id = 900
        bot = SimpleNamespace(
            command_permissions={str(SERVER_ID): role_id},
            profile_backfills_in_progress=set(),
            profile_backfill_stop_requests=set(),
        )
        message = Mock()
        message.guild.id = SERVER_ID
        message.author.roles = [Mock(id=role_id)]
        message.author.guild_permissions.administrator = False
        message.content = "v!backfill stop"
        message.reply = AsyncMock()

        await NamingBot.handle_profile_backfill_command(
            cast(NamingBot, bot), message)

        self.assertEqual(
            message.reply.await_args.args[0],
            "No profile backfill is running.",
        )


class PokemonNameValidationTests(unittest.TestCase):
    def test_accepts_unicode_pokemon_names(self) -> None:
        for name in ("Flabébé", "Nidoran♀", "Type: Null"):
            with self.subTest(name=name):
                self.assertTrue(is_valid_pokemon_name(name))

    def test_accepts_special_pokemon_names_in_user_commands(self) -> None:
        for name in (
            "Chef Dente",
            "Prof Tangrowth",
            "Peakychu",
            "DJ Rotom",
            "Smearguru",
            "Mosslax",
            "Zenith Marshadow",
            "Partner Eevee",
            "Blaze Breed Tauros",
            "Aqua Breed Tauros",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_known_pokemon_name(name))
                self.assertEqual(parse_shinyhunt_command(f"v!sh {name}"), name)
                self.assertEqual(parse_collection_add_command(f"v!cl add {name}"), [name])
                self.assertEqual(
                    parse_reserve_add_command(f"v!r add {name} <@319>"),
                    ([name], 319),
                )

    def test_rejects_multiple_candidates_and_unexpected_symbols(self) -> None:
        self.assertFalse(is_valid_pokemon_name("Gothorita / Gothita"))
        self.assertFalse(is_valid_pokemon_name("Gothorita!"))


class ProfileShopDataTests(unittest.TestCase):
    def test_shop_catalog_inventory_migration_and_asset_codes(self) -> None:
        import bot

        shop_items = bot.load_profile_shop(
            Path(__file__).with_name("data") / "profile_shop.json"
        )
        self.assertEqual(shop_items["frame:amethyst"]["price"], 45000)
        self.assertEqual(shop_items["frame:celestial"]["price"], 60000)
        self.assertEqual(shop_items["frame:ocean"]["price"], 50000)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shop_path = root / "profile_shop.json"
            inventory_path = root / "profile_inventory.json"
            shop_path.write_text(
                '{"items": [{"type": "frame", "key": "mystic", "price": 80}]}',
                encoding="utf-8",
            )

            items = bot.load_profile_shop(shop_path)
            self.assertEqual(items["frame:mystic"]["price"], 80)
            self.assertEqual(bot.load_profile_shop(root / "empty.json"), {})

            profiles = {
                "123": {
                    **bot.PROFILE_DEFAULTS,
                    "background": "cosmog",
                    "frame": "mystic",
                }
            }
            inventory = bot.load_profile_inventory(inventory_path, profiles)
            self.assertEqual(
                [
                    (asset["type"], asset["key"])
                    for asset in inventory["123"]["assets"]
                ],
                [("background", "cosmog"), ("frame", "mystic")],
            )
            migrated_codes = [
                asset["code"] for asset in inventory["123"]["assets"]
            ]
            self.assertEqual(len(migrated_codes), len(set(migrated_codes)))
            self.assertTrue(
                all(len(code) == 7 and code.isalnum() for code in migrated_codes)
            )
            inventory["123"]["balances"] = {"Pokédollar": 25}
            bot.save_profile_inventory(inventory_path, inventory)
            self.assertEqual(
                bot.load_profile_inventory(inventory_path, {}),
                inventory,
            )

            codes = bot.profile_asset_codes()
            self.assertEqual(len(codes), len(set(codes.values())))
            self.assertTrue(
                all(len(code) == 7 and code.isalnum() for code in codes.values())
            )


class OrgRpcTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_org_channel_ignores_board_commands_but_handles_json(self) -> None:
        from org_rpc import OrgRpc

        with tempfile.TemporaryDirectory() as directory:
            channel = SimpleNamespace(id=456, send=AsyncMock())
            message = SimpleNamespace(
                id=123,
                author=SimpleNamespace(id=789),
                channel=channel,
                guild=None,
                content="!org start",
            )
            rpc = OrgRpc(
                channel_id=channel.id,
                guild_id=None,
                org_bot_user_id=message.author.id,
                org=Mock(entries=[]),
                add_to_vivillon=Mock(),
                remove_from_vivillon=Mock(return_value=False),
                dedupe_path=Path(directory) / "dedupe.json",
            )

            with patch.object(rpc, "_handle_request", new=AsyncMock()) as handle:
                self.assertTrue(await rpc.handle_message(message))
                handle.assert_not_awaited()
                channel.send.assert_not_awaited()

                message.content = '{"type": "list", "request_id": "round-1"}'
                self.assertTrue(await rpc.handle_message(message))
                handle.assert_awaited_once_with(message)


class OrgReservesTests(unittest.TestCase):
    def test_validation_and_restrictions(self):
        import tempfile
        from org_api import OrgError, OrgReserves

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "r.json").write_text(
                '{"slots": {"s": {"allowed": ["Pikachu"]}}}', encoding="utf-8"
            )
            org = OrgReserves(root / "o.json", root / "r.json", ["Pikachu", "Eevee"])
            self.assertEqual(org.validate("all pikachu", "s"), ("Pikachu", True))
            with self.assertRaises(OrgError):
                org.validate("Eevee", "s")
            with self.assertRaises(OrgError):
                org.validate("Nope", None)
            self.assertTrue(org.add("Pikachu", 1, "s"))
            self.assertFalse(org.add("Pikachu", 1, "s"))
            self.assertEqual(org.reset(), 1)
            self.assertEqual(org.entries, [])

    def test_shared_org_restrictions_apply_to_all_configured_slots(self):
        from org_api import OrgError, OrgReserves

        slot_names = (
            "rares",
            "regionals",
            "gmax",
            "eevos",
            "paradox",
            "slot1",
            "slot2",
            "slot3",
            "slot4",
            "donator",
            "boostie",
        )
        org = OrgReserves(
            data_path("org_reserves.json"),
            data_path("org_restrictions.json"),
            ["Abomasnow", "Orbeetle", "Gmax Orbeetle"],
        )

        self.assertEqual(set(org.restrictions), set(slot_names))
        shared_rule = org.restrictions[slot_names[0]]
        for slot in slot_names:
            with self.subTest(slot=slot):
                self.assertEqual(org.restrictions[slot], shared_rule)
                self.assertEqual(org.validate("Abomasnow", slot), ("Abomasnow", False))
                with self.assertRaises(OrgError):
                    org.validate("Orbeetle", slot)
                with self.assertRaises(OrgError):
                    org.validate("Gmax Orbeetle", slot)


class OrgApiValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_individual_add_rejects_live_category_members_without_saving(self) -> None:
        from aiohttp.test_utils import TestClient, TestServer
        from bot import pokemon_matches_all_forms_reservation
        from org_api import OrgReserves, create_app, load_json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories = {
                "1": {
                    "regional": ["Pikachu", "Heat Rotom"],
                    "wildcard": ["All Eevee", "All Raichu"],
                },
                "2": {"other": ["Bulbasaur"]},
            }
            bot = SimpleNamespace(reservations={}, reserve_path=root / "native.json")
            org = OrgReserves(
                root / "org.json",
                root / "restrictions.json",
                [
                    "Pikachu", "Rotom", "Heat Rotom", "Eevee", "Raichu",
                    "Alolan Raichu", "Bulbasaur",
                ],
            )
            app = create_app(
                "test-api-key",
                org,
                1,
                lambda name, user_id: NamingBot.org_add_reserve(
                    cast(NamingBot, bot), name, user_id
                ),
                lambda name, user_id: NamingBot.org_remove_reserve(
                    cast(NamingBot, bot), name, user_id
                ),
                lambda: categories,
                matches_all_forms=pokemon_matches_all_forms_reservation,
            )
            headers = {"Authorization": "Bearer test-api-key"}
            with patch.dict(bot_module.os.environ, {"ORG_GUILD_ID": "1"}):
                async with TestClient(TestServer(app)) as client:
                    for pokemon in (
                        "pIkAcHu", "all Pikachu", "All Rotom", "Eevee",
                        "Alolan Raichu", "All Alolan Raichu",
                    ):
                        with self.subTest(pokemon=pokemon):
                            response = await client.post(
                                "/api/org/reserves",
                                json={
                                    "action": "add",
                                    "pokemon": pokemon,
                                    "userId": "123",
                                    "slot": "slot1",
                                },
                                headers=headers,
                            )
                            self.assertEqual(response.status, 409)
                            result = await response.json()
                            self.assertFalse(result["success"])
                            self.assertIn("cannot be individually reserved", result["error"])
                            self.assertEqual(org.entries, [])
                            self.assertEqual(load_json(org.path, []), [])
                            self.assertEqual(bot.reservations, {})
                            self.assertEqual(load_reservations(bot.reserve_path), {})

                    response = await client.post(
                        "/api/org/reserves",
                        json={
                            "action": "add",
                            "pokemon": "Bulbasaur",
                            "userId": "123",
                            "slot": "slot1",
                        },
                        headers=headers,
                    )
                    self.assertEqual(response.status, 200)
                    self.assertTrue((await response.json())["success"])
                    self.assertEqual(
                        load_json(org.path, []),
                        [{"pokemon": "Bulbasaur", "userId": "123", "slot": "slot1"}],
                    )
                    self.assertEqual(load_reservations(bot.reserve_path), {"1:bulbasaur": [123]})

                    categories["1"]["regional"].append("Bulbasaur")
                    response = await client.post(
                        "/api/org/reserves",
                        json={
                            "action": "add",
                            "pokemon": "Bulbasaur",
                            "userId": "456",
                            "slot": "slot2",
                        },
                        headers=headers,
                    )
                    self.assertEqual(response.status, 409)
                    self.assertEqual(len(org.entries), 1)
                    self.assertEqual(
                        load_json(org.path, []),
                        [{"pokemon": "Bulbasaur", "userId": "123", "slot": "slot1"}],
                    )
                    self.assertEqual(load_reservations(bot.reserve_path), {"1:bulbasaur": [123]})

                    response = await client.post(
                        "/api/org/reserves",
                        json={
                            "action": "remove",
                            "pokemon": "Bulbasaur",
                            "userId": "123",
                            "slot": "slot1",
                        },
                        headers=headers,
                    )
                    self.assertEqual(response.status, 200)
                    self.assertTrue((await response.json())["changed"])
                    self.assertEqual(load_json(org.path, []), [])
                    self.assertEqual(load_reservations(bot.reserve_path), {})

    async def test_validate_rpc_matches_org_reserves_for_every_slot(self) -> None:
        from aiohttp.test_utils import TestClient, TestServer
        from org_api import OrgError, OrgReserves, create_app

        slots = (
            "rares",
            "regionals",
            "gmax",
            "eevos",
            "paradox",
            "slot1",
            "slot2",
            "slot3",
            "slot4",
            "donator",
            "boostie",
        )
        org = OrgReserves(
            data_path("org_reserves.json"),
            data_path("org_restrictions.json"),
            ["Abomasnow", "Orbeetle"],
        )
        app = create_app("test-api-key", org, 1, lambda *_: None, lambda *_: False)

        async with TestClient(TestServer(app)) as client:
            for slot in slots:
                for pokemon in ("Abomasnow", "Orbeetle"):
                    try:
                        name, all_forms = org.validate(pokemon, slot)
                        expected = {
                            "success": True,
                            "valid": True,
                            "pokemon": f"All {name}" if all_forms else name,
                        }
                    except OrgError as error:
                        expected = {"success": False, "error": error.message}
                    response = await client.post(
                        "/api/org/validate",
                        json={"pokemon": pokemon, "slot": slot},
                        headers={"Authorization": "Bearer test-api-key"},
                    )
                    self.assertEqual(
                        response.status, 200 if expected["success"] else 403
                    )
                    self.assertEqual(await response.json(), expected)

    async def test_category_listing_and_reservation_are_atomic_and_idempotent(self) -> None:
        import tempfile
        from aiohttp.test_utils import TestClient, TestServer
        from org_api import OrgReserves, create_app

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories = {"1": {"regional": ["Pikachu", "Eevee"]}}
            vivillon_reserves: list[tuple[str, int]] = []

            def add_category(names: list[str], user_id: int) -> None:
                vivillon_reserves.extend((name, user_id) for name in names)

            org = OrgReserves(root / "org.json", root / "restrictions.json", ["Pikachu", "Eevee"])
            app = create_app(
                "test-api-key",
                org,
                1,
                lambda *_: None,
                lambda *_: False,
                lambda: categories,
                add_category,
            )
            headers = {"Authorization": "Bearer test-api-key"}

            async with TestClient(TestServer(app)) as client:
                response = await client.get("/api/org/categories", headers=headers)
                self.assertEqual(
                    await response.json(),
                    {
                        "success": True,
                        "count": 1,
                        "categories": [
                            {
                                "name": "regional",
                                "pokemon": ["Pikachu", "Eevee"],
                                "count": 2,
                            }
                        ],
                    },
                )

                request = {"category": "Regional", "userId": "123"}
                response = await client.post(
                    "/api/org/reserves/category", json=request, headers=headers
                )
                self.assertEqual(response.status, 200)
                self.assertTrue((await response.json())["changed"])
                self.assertEqual(len(vivillon_reserves), 2)

                response = await client.post(
                    "/api/org/reserves/category", json=request, headers=headers
                )
                self.assertFalse((await response.json())["changed"])
                self.assertEqual(len(vivillon_reserves), 2)

                response = await client.post(
                    "/api/org/reserves/category",
                    json={"category": "regional", "userId": "456"},
                    headers=headers,
                )
                self.assertEqual(response.status, 409)
                self.assertEqual(len(vivillon_reserves), 2)

                response = await client.get("/api/org/reserves", headers=headers)
                listed = await response.json()
                self.assertEqual(listed["count"], 2)
                self.assertTrue(
                    all(entry["type"] == "category" for entry in listed["reserves"])
                )

                response = await client.post(
                    "/api/org/reserves",
                    json={
                        "action": "add",
                        "pokemon": "Pikachu",
                        "userId": "456",
                    },
                    headers=headers,
                )
                self.assertEqual(response.status, 409)

    async def test_category_reservation_rolls_back_org_entries_on_vivillon_failure(self) -> None:
        import tempfile
        from aiohttp.test_utils import TestClient, TestServer
        from org_api import OrgReserves, create_app

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            org = OrgReserves(root / "org.json", root / "restrictions.json", ["Pikachu"])

            def fail_add(_names: list[str], _user_id: int) -> None:
                raise ValueError("storage failed")

            app = create_app(
                "test-api-key",
                org,
                1,
                lambda *_: None,
                lambda *_: False,
                lambda: {"1": {"regional": ["Pikachu"]}},
                fail_add,
            )
            async with TestClient(TestServer(app)) as client:
                response = await client.post(
                    "/api/org/reserves/category",
                    json={"category": "regional", "userId": "123"},
                    headers={"Authorization": "Bearer test-api-key"},
                )
                self.assertEqual(response.status, 500)
                self.assertEqual(org.entries, [])
                self.assertEqual((root / "org.json").read_text(encoding="utf-8"), "[]\n")

    async def test_individual_remove_matches_pokemon_user_and_slot(self) -> None:
        import tempfile
        from aiohttp.test_utils import TestClient, TestServer
        from org_api import OrgReserves, create_app

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vivillon_reserves: set[tuple[str, int]] = set()

            def add_to_vivillon(name: str, user_id: int) -> None:
                vivillon_reserves.add((name, user_id))

            def remove_from_vivillon(name: str, user_id: int) -> bool:
                reservation = (name, user_id)
                if reservation not in vivillon_reserves:
                    return False
                vivillon_reserves.remove(reservation)
                return True

            org = OrgReserves(root / "org.json", root / "restrictions.json", ["Pikachu"])
            app = create_app(
                "test-api-key",
                org,
                1,
                add_to_vivillon,
                remove_from_vivillon,
            )
            headers = {"Authorization": "Bearer test-api-key"}

            async with TestClient(TestServer(app)) as client:
                for slot in ("slot1", "slot2"):
                    response = await client.post(
                        "/api/org/reserves",
                        json={
                            "action": "add",
                            "pokemon": "Pikachu",
                            "userId": "123",
                            "slot": slot,
                        },
                        headers=headers,
                    )
                    self.assertEqual(response.status, 200)

                listed = await (await client.get("/api/org/reserves", headers=headers)).json()
                self.assertEqual(
                    [entry["slot"] for entry in listed["reserves"]],
                    ["slot1", "slot2"],
                )

                response = await client.post(
                    "/api/org/reserves",
                    json={
                        "action": "remove",
                        "pokemon": "Pikachu",
                        "userId": "123",
                        "slot": "slot1",
                    },
                    headers=headers,
                )
                self.assertEqual(response.status, 200)
                self.assertIn(("Pikachu", 123), vivillon_reserves)
                self.assertEqual(
                    [(entry["pokemon"], entry["slot"]) for entry in org.entries],
                    [("Pikachu", "slot2")],
                )

                response = await client.post(
                    "/api/org/reserves",
                    json={
                        "action": "remove",
                        "pokemon": "Pikachu",
                        "userId": "123",
                    },
                    headers=headers,
                )
                self.assertEqual(response.status, 400)

                response = await client.post(
                    "/api/org/reserves",
                    json={
                        "action": "remove",
                        "pokemon": "Pikachu",
                        "userId": "123",
                        "slot": "slot2",
                    },
                    headers=headers,
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(vivillon_reserves, set())
                self.assertEqual(org.entries, [])

    async def test_round_reset_clears_org_and_configured_guild_reserves(self) -> None:
        import tempfile
        from aiohttp.test_utils import TestClient, TestServer
        from org_api import OrgReserves, create_app, save_json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            org = OrgReserves(root / "org.json", root / "restrictions.json", ["Pikachu"])
            org.entries = [
                {"pokemon": "Pikachu", "userId": "123", "slot": "slot1"},
                {
                    "pokemon": "Eevee",
                    "userId": "456",
                    "slot": None,
                    "type": "category",
                    "category": "regional",
                },
            ]
            save_json(org.path, org.entries)
            vivillon_reserves = {
                1: {"Pikachu", "Eevee"},
                2: {"Pikachu"},
            }

            def clear_vivillon(guild_id: int) -> int:
                cleared = len(vivillon_reserves.get(guild_id, set()))
                vivillon_reserves.pop(guild_id, None)
                return cleared

            app = create_app(
                "test-api-key",
                org,
                1,
                lambda *_: None,
                lambda *_: False,
                clear_reserves_from_vivillon=clear_vivillon,
            )
            async with TestClient(TestServer(app)) as client:
                response = await client.post(
                    "/api/org/reset",
                    headers={"Authorization": "Bearer test-api-key"},
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    await response.json(),
                    {
                        "success": True,
                        "cleared": 2,
                        "clearedVivillon": 2,
                    },
                )
                self.assertEqual(org.entries, [])
                self.assertEqual(vivillon_reserves, {2: {"Pikachu"}})


class TypeEmojiTests(unittest.TestCase):
    def test_dual_type_pokemon_get_both_emojis_in_order(self) -> None:
        import bot

        self.assertEqual(
            bot.type_emoji_text("Charizard"),
            f"{bot.TYPE_EMOJIS['fire']}{bot.TYPE_EMOJIS['flying']}",
        )

    def test_forms_use_their_own_types(self) -> None:
        import bot

        self.assertEqual(bot.pokemon_types_for("Heat Rotom"), ["electric", "fire"])
        self.assertEqual(bot.pokemon_types_for("Bug Silvally", "Silvally"), ["bug"])
        self.assertEqual(bot.pokemon_types_for("Icy-Snow Vivillon"), ["bug", "flying"])

    def test_every_type_has_an_emoji_and_reply_leads_with_it(self) -> None:
        import bot

        self.assertEqual(len(bot.TYPE_EMOJIS), 18)
        reply = bot.format_typed_spawn_reply(
            "Gengar",
            100.0,
            1,
            bot.type_emoji_text("Gengar"),
            [],
            [123],
            [456],
            [789],
        )
        lines = reply.splitlines()
        self.assertTrue(lines[0].startswith(bot.TYPE_EMOJIS["ghost"]))
        self.assertIn("Gengar: 100.00%", lines[0])
        self.assertEqual(
            lines[1:4],
            [
                "Shinyhunt: <@123>",
                "Collection: <@456>",
                "Typeping: <@789>",
            ],
        )


class MusicActivityAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_activity_page_and_song_are_served(self) -> None:
        from aiohttp.test_utils import TestClient, TestServer
        from bot import create_activity_app

        async with TestClient(TestServer(create_activity_app(123456))) as client:
            page = await client.get("/")
            self.assertEqual(page.status, 200)
            text = await page.text()
            self.assertIn('new window.DiscordSDK("123456")', text)
            self.assertNotIn("__CLIENT_ID__", text)
            self.assertEqual((await client.get("/sdk.js")).status, 200)
            song = await client.get("/return_to_me.wav")
            self.assertEqual(song.status, 200)
            self.assertEqual((await client.get("/../bot.py")).status, 404)


if __name__ == "__main__":
    unittest.main()
