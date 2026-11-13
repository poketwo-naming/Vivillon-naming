import asyncio
import base64
import csv
import hashlib
import mimetypes
from io import BytesIO
import json
import logging
import math
import os
import random
import re
import threading
import time
from collections import OrderedDict, deque
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Final, Literal, TypeGuard, TypedDict, cast

import aiohttp
import discord
from discord.ext import commands
from aiohttp import web
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
from image_match import (
    CUSTOM_FORM_SPECIES,
    FORM_DISPLAY_NAMES,
    ARCEUS_FORM_SET,
    base_pokemon_name,
    canonicalize_regional_name,
    minimum_votes_for,
    SILVALLY_FORMS,
    SQUAWKABILLY_PLUMAGE_FORMS,
    UNOWN_LETTER_PATTERN,
    VIVILLON_FORM_SET,
    ImageMatcher,
    cv2,
    species_display_name,
    squawkabilly_form_by_color,
    vivillon_form_by_pattern,
)
from org_api import OrgError, OrgReserves, create_app
import org_rpc
import pg_store
from data_paths import data_path
from daycare import DaycareFeature
from help_menu import HELP_COMMAND_PATTERN, HelpMenuView, build_help_menu_embeds
from pokeball_drops import PokeballDrops
from openai import AsyncOpenAI, BadRequestError, OpenAIError
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionContentPartImageParam,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vivillon_naming")

SPAWN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bwild\s+(?:pokemon|pok[eé]mon)\b", re.IGNORECASE
)
RESERVE_ROLE_ID: Final[int] = 1532820386511720579
POKETWO_COMMAND_BOT_ID: Final[int] = 716390085896962058
CATCH_COMMAND_NAME_ALIASES: Final[dict[str, str]] = {
    "blade aegislash": "Aegislash",
    "hisui sneasel": "Sneasel",
    "hisuian sneasel": "Sneasel",
    "shield aegislash": "Aegislash",
}
PREMIUM_TIER_LIMITS: Final[dict[str, int]] = {
    "bronze": 100,
    "silver": 200,
    "gold": 300,
}
PREMIUM_TIER_BUTTERFLIES: Final[dict[str, tuple[str, str, int]]] = {
    "bronze": ("Bronze butterfly", "butterfly-bronze.png", 0xCD7F32),
    "silver": ("Silver butterfly", "butterfly-silver.png", 0xC0C0C0),
    "gold": ("Gold butterfly", "butterfly-gold.png", 0xFFD700),
}
SERVER_ID: Final[int] = 1530949341013868635
SERVER_IDS: Final[frozenset[int]] = frozenset(
    {SERVER_ID, 1543384606630481920, 1473361675452420136}
)
# Guild id -> the one user who may use every command in that guild only.
PRIVILEGED_MANAGER_IDS: Final[dict[int, int]] = {
    1473361675452420136: 616386709659189268,
}
INCENSE_DURATION_SECONDS: Final[int] = 60 * 60
API_STATUS_WINDOW_SECONDS: Final[int] = 5 * 60
RECOGNITION_WINDOW_SECONDS: Final[float] = 1.0
RECOGNITION_ALERT_CHANNEL_ID: Final[int] = 1531476097970212915
RECOGNITION_ALERT_USER_ID: Final[int] = 729509574486523907
RESERVE_REPORT_CHANNEL_ID: Final[int] = 1532512015703085147
RESERVE_REPORT_TRADE_THREAD_ID: Final[int] = 1538294047095922748
RESERVE_REPORT_PRICES: Final[tuple[tuple[int, int], ...]] = (
    (255, 2500), (337, 5000), (674, 10000), (899, 15000),
    (1349, 20000), (3596, 30000), (5394, 35000),
    (15196, 40000), (30000, 50000),
)
RESERVE_REPORT_EVENT_FORMS: Final[frozenset[str]] = frozenset({
    "enchanted applin", "rotten applin", "oracle meowscarada",
    "witch meowscarada", "medusa simipour", "statue simipour",
    "elixir reuniclus", "cauldron reuniclus",
})
API_STATUS_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!api\s*$",
    re.IGNORECASE,
)
PERMISSION_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!permission(?:\s+(off|\d+))?\s*$",
    re.IGNORECASE,
)
COMMANDS_OFF_PATTERN: Final[re.Pattern[str]] = re.compile(r"^v!coff\s*$", re.IGNORECASE)
COMMANDS_ON_PATTERN: Final[re.Pattern[str]] = re.compile(r"^v!con\s*$", re.IGNORECASE)
PREMIUM_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!premium(?:\s+add\s+(?P<tier>bronze|silver|gold)\s+(?P<guild_id>[0-9]+))?\s*$",
    re.IGNORECASE,
)
PROFILE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!profile(?:\s+<@!?(\d+)>)?\s*$",
    re.IGNORECASE,
)
PROFILE_BUY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!buy(?:\s+(.+?))?\s*$",
    re.IGNORECASE,
)
PROFILE_SHOP_PREVIEW_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!shop\s+preview(?:\s+(.+?))?\s*$",
    re.IGNORECASE,
)
PROFILE_BACKFILL_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!backfill(?:\s+(?P<stop>stop)"
    r"|\s+continue\s+(?P<continue_from><#\d+>|\d+)"
    r"|\s+(?P<channel><#\d+>|\d+))?\s*$",
    re.IGNORECASE,
)
PROFILE_CATCH_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bCongratulations\s+(?P<catcher>[^!\n]+)!\s*You caught a\b",
    re.IGNORECASE,
)
SHINYHUNT_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!sh\s+(.+?)\s*$",
    re.IGNORECASE,
)
SHINYHUNT_REMOVE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!sh\s+remove\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+add\s+(.+?)\s+<@!?(\d+)>\s*$",
    re.IGNORECASE,
)
RESERVE_SEARCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+search\s+(.+?)\s*$",
    re.IGNORECASE,
)
RESERVE_REMOVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+remove\s+(.+?)(?:(?:\s*,\s*|\s+)<@!?(\d+)>)?\s*$",
    re.IGNORECASE,
)
ADD_RESERVE_CATEGORY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!addcategory\s+([a-z0-9_-]{1,32})\s*$",
    re.IGNORECASE,
)
CREATE_RESERVE_CATEGORY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!categorycreate\s+([a-z0-9_-]{1,32})\s+(.+?)\s*$",
    re.IGNORECASE,
)
LIST_RESERVE_CATEGORIES_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!categorylist\s*$",
    re.IGNORECASE,
)
DELETE_RESERVE_CATEGORY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!(?:categorydelete|cd)\s+([a-z0-9_-]{1,32})\s*$",
    re.IGNORECASE,
)
COLLECTION_ADD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!cl\s+add\s+(.+?)\s*$",
    re.IGNORECASE,
)
COLLECTION_REMOVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!cl\s+remove\s+(.+?)\s*$",
    re.IGNORECASE,
)
TYPE_PING_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!(?:tp|typeping)\s*$",
    re.IGNORECASE,
)
TYPE_PING_CLEAR_ALL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!(?:tp|typeping)\s+clear\s+all\s*$",
    re.IGNORECASE,
)
RESERVATION_EMBED_PAGE_SIZE: Final[int] = 20
CHAT_EVENT_EMOJI: Final[str] = "⏲️"
CHAT_EVENT_SIGNUP_SECONDS: Final[int] = 60
CHAT_EVENT_MIN_PARTICIPANTS: Final[int] = 2
PROFILE_DEFAULTS: Final[dict[str, int | str]] = {
    "text_color": "white",
    "background": "default",
    "middle_background": "white",
    "frame": "none",
}
PROFILE_STAT_DEFAULTS: Final[dict[str, int]] = {
    "total": 0,
    "shiny": 0,
    "box_shiny": 0,
    "low_iv": 0,
    "high_iv": 0,
    "gmax": 0,
    "missingno": 0,
}
PROFILE_RECORD_LABELS: Final[dict[str, tuple[str, str]]] = {
    "highest_iv": ("Highest IV", "high_iv"),
    "lowest_iv": ("Lowest IV", "low_iv"),
    "highest_shiny_iv": ("Highest Shiny IV", "shiny"),
    "lowest_shiny_iv": ("Lowest Shiny IV", "shiny"),
}


@dataclass(frozen=True)
class ProfileIvRecord:
    pokemon: str
    iv: float
    level: str = "???"
    gender: str | None = None


PROFILE_TEXT_COLORS: Final[dict[str, tuple[str, str]]] = {
    "white": ("Default text color", "#FFFFFF"),
    "black": ("Black", "#171717"),
    "pink": ("Pink", "#F3A6C8"),
    "blue": ("Blue", "#9BD8F2"),
    "gold": ("Gold", "#F4D06F"),
}
PROFILE_BACKGROUNDS: Final[dict[str, tuple[str, str]]] = {
    "default": ("Default background", "#292A2F"),
    "cosmog": ("Cosmog", "Cosmog blurred profile background"),
    "hiszorua": ("Hisuian Zorua", "Hisuian Zorua blurred profile background"),
    "eevee": ("Eevee", "Eevee blurred, rotated profile background"),
    "moonnight": ("Moon Night", "Moon Night blurred profile background"),
    "meadownight": ("Meadow Night", "Meadow Night blurred profile background"),
    "buneary": ("Buneary", "Buneary blurred profile background"),
    "slakoth": ("Slakoth", "Slakoth blurred profile background"),
    "marshadow": ("Marshadow", "Marshadow blurred profile background"),
    "jirachi": ("Jirachi", "Jirachi blurred profile background"),
    "gardevoir": ("Gardevoir", "Gardevoir blurred profile background"),
    "pink_ninetales": ("Pink Ninetales", "Pink Ninetales blurred profile background"),
}
PROFILE_BACKGROUND_IMAGES: Final[dict[str, Path]] = {
    "cosmog": Path(__file__).with_name("background") / "cosmog.png",
    "hiszorua": Path(__file__).with_name("background") / "hiszorua.png",
    "eevee": Path(__file__).with_name("background") / "eevee.png",
    "moonnight": Path(__file__).with_name("background") / "moonnight.png",
    "meadownight": Path(__file__).with_name("background") / "meadownight.png",
    "buneary": Path(__file__).with_name("background") / "buneary.png",
    "slakoth": Path(__file__).with_name("background") / "slakoth.png",
    "marshadow": Path(__file__).with_name("background") / "marshadow.png",
    "jirachi": Path(__file__).with_name("background") / "jirachi.png",
    "gardevoir": Path(__file__).with_name("background") / "gardevoir.png",
    "pink_ninetales": Path(__file__).with_name("background") / "pink_ninetales.png",
}
PROFILE_MIDDLE_BACKGROUNDS: Final[dict[str, tuple[str, str]]] = {
    "white": ("Default middle background", "#FFFFFF"),
    "cosmog": ("Cosmog", "Cosmog middle background"),
    "hiszorua": ("Hisuian Zorua", "Hisuian Zorua middle background"),
    "eevee": ("Eevee", "Eevee middle background"),
    "buneary": ("Buneary", "Buneary middle background"),
    "slakoth": ("Slakoth", "Slakoth middle background"),
    "marshadow": ("Marshadow", "Marshadow middle background"),
    "jirachi": ("Jirachi", "Jirachi middle background"),
    "gardevoir": ("Gardevoir", "Gardevoir middle background"),
    "pink_ninetales": ("Pink Ninetales", "Pink Ninetales middle background"),
}
PROFILE_MIDDLE_BACKGROUND_IMAGES: Final[dict[str, Path]] = {
    "cosmog": Path(__file__).with_name("middle background") / "Cosmog.png",
    "hiszorua": Path(__file__).with_name("middle background") / "hiszorua.png",
    "eevee": Path(__file__).with_name("middle background") / "eevee.png",
    "buneary": Path(__file__).with_name("middle background") / "Buneary.png",
    "slakoth": Path(__file__).with_name("middle background") / "Slakoth.png",
    "marshadow": Path(__file__).with_name("middle background") / "Marshadow.png",
    "jirachi": Path(__file__).with_name("middle background") / "Jirachi.png",
    "gardevoir": Path(__file__).with_name("middle background") / "Gardevoir.png",
    "pink_ninetales": Path(__file__).with_name("middle background") / "Pink Ninetales.png",
}
PROFILE_LEGACY_CHOICES: Final[dict[str, frozenset[str]]] = {
    "background": frozenset({"rose", "blue", "purple", "mint"}),
    "middle_background": frozenset({"light_gray", "soft_pink", "soft_blue"}),
}
PROFILE_FRAMES: Final[dict[str, tuple[str, str]]] = {
    "none": ("No frame", "No frame selected"),
    "mystic": ("Mystic", "Mystic profile frame"),
    "gem": ("Gem", "Gem profile frame"),
    "nightflower": ("Nightflower", "Nightflower profile frame"),
    "flowerspring": ("Flower Spring", "Flower Spring profile frame"),
    "moonlit": ("Moonlit", "Moonlit profile frame"),
    "moonveil": ("Moonveil", "Moonveil profile frame"),
    "jirachi": ("Jirachi", "Jirachi profile frame"),
    "magic": ("Magic", "Magic profile frame"),
    "amethyst": ("Amethyst", "Amethyst profile frame"),
    "celestial": ("Celestial", "Celestial profile frame"),
    "ocean": ("Ocean", "Ocean profile frame"),
    "pink_ninetales": ("Pink Ninetales", "Pink Ninetales profile frame"),
}
PROFILE_FRAME_IMAGES: Final[dict[str, Path]] = {
    "mystic": Path(__file__).with_name("Frames") / "mystic.png",
    "gem": Path(__file__).with_name("Frames") / "gem.png",
    "nightflower": Path(__file__).with_name("Frames") / "nightflower.png",
    "flowerspring": Path(__file__).with_name("Frames") / "flowerspring.png",
    "moonlit": Path(__file__).with_name("Frames") / "moonlit.png",
    "moonveil": Path(__file__).with_name("Frames") / "moonveil.png",
    "jirachi": Path(__file__).with_name("Frames") / "jirachi.png",
    "magic": Path(__file__).with_name("Frames") / "magic.png",
    "amethyst": Path(__file__).with_name("Frames") / "amethyst.png",
    "celestial": Path(__file__).with_name("Frames") / "celestial.png",
    "ocean": Path(__file__).with_name("Frames") / "ocean.png",
    "pink_ninetales": Path(__file__).with_name("Frames") / "pink_ninetales.png",
}
PROFILE_FRAME_OPENINGS: Final[dict[str, tuple[int, int, int, int]]] = {
    "nightflower": (74, 84, 1595, 845),
    "flowerspring": (42, 61, 909, 576),
    "moonlit": (45, 62, 963, 624),
    "moonveil": (118, 130, 1418, 894),
    "jirachi": (65, 64, 1086, 699),
    "magic": (50, 71, 1416, 866),
    "amethyst": (20, 45, 1095, 723),
    "celestial": (82, 110, 1339, 851),
    "ocean": (91, 123, 1491, 948),
    "pink_ninetales": (100, 90, 1436, 934),
}
PROFILE_FRAME_SCALES: Final[dict[str, float]] = {
    "mystic": 1.0,
    "gem": 1.02,
}
PROFILE_CARD_SCALES: Final[dict[str, float]] = {
    "mystic": 1.0,
    "gem": 1.0,
    "nightflower": 1.0,
    "flowerspring": 1.0,
    "moonlit": 1.08,
    "moonveil": 1.1,
    "jirachi": 1.0,
    "magic": 1.0,
    "pink_ninetales": 1.0,
}
PROFILE_FRAME_CANVAS_SIZE: Final[tuple[int, int]] = (1467, 868)
PROFILE_FRAME_ALPHA_GAMMA: Final[float] = 0.6
PROFILE_FRAME_CORNER_RADIUS: Final[int] = 72
PROFILE_SETTING_CHOICES: Final[dict[str, dict[str, tuple[str, str]]]] = {
    "text_color": PROFILE_TEXT_COLORS,
    "background": PROFILE_BACKGROUNDS,
    "middle_background": PROFILE_MIDDLE_BACKGROUNDS,
    "frame": PROFILE_FRAMES,
}
PROFILE_FLOWER_SPRING_USER_ID: Final[int] = 1286779672549392527
PROFILE_MOONLIT_USER_ID: Final[int] = 883224024161873940
PROFILE_MARSHADOW_USER_ID: Final[int] = 1398882668401135657
PROFILE_JIRACHI_USER_ID: Final[int] = 616386709659189268
PROFILE_GARDEVOIR_USER_ID: Final[int] = 729509574486523907
PROFILE_PINK_NINETALES_USER_ID: Final[int] = 217819108329259008
PROFILE_ALL_ACCESS_USER_IDS: Final[frozenset[int]] = frozenset(
    {PROFILE_GARDEVOIR_USER_ID}
)
PROFILE_USER_ONLY_CHOICES: Final[dict[int, dict[str, frozenset[str]]]] = {
    PROFILE_FLOWER_SPRING_USER_ID: {
        "background": frozenset({"buneary"}),
        "middle_background": frozenset({"buneary"}),
        "frame": frozenset({"flowerspring"}),
    },
    PROFILE_MOONLIT_USER_ID: {
        "background": frozenset({"slakoth"}),
        "middle_background": frozenset({"slakoth"}),
        "frame": frozenset({"moonlit"}),
    },
    PROFILE_MARSHADOW_USER_ID: {
        "background": frozenset({"marshadow"}),
        "middle_background": frozenset({"marshadow"}),
        "frame": frozenset({"moonveil"}),
    },
    PROFILE_JIRACHI_USER_ID: {
        "background": frozenset({"jirachi"}),
        "middle_background": frozenset({"jirachi"}),
        "frame": frozenset({"jirachi"}),
    },
    PROFILE_GARDEVOIR_USER_ID: {
        "background": frozenset({"gardevoir"}),
        "middle_background": frozenset({"gardevoir"}),
        "frame": frozenset({"magic"}),
    },
    PROFILE_PINK_NINETALES_USER_ID: {
        "background": frozenset({"pink_ninetales"}),
        "middle_background": frozenset({"pink_ninetales"}),
        "frame": frozenset({"pink_ninetales"}),
    },
}
PROFILE_RETURN_TO_ME: Final[dict[str, tuple[str, str, Path]]] = {
    "return_to_me": (
        "Return to me",
        "Plays a looping song only you can hear",
        Path(__file__).with_name("music") / "return_to_me.mp3",
    ),
}
ACTIVITY_DIR: Final[Path] = Path(__file__).with_name("activity")
PROFILE_MUSIC_FILE: Final[Path] = (
    Path(__file__).with_name("music") / "return_to_me.ogg"
)
PROFILE_SETTING_LABELS: Final[dict[str, str]] = {
    "text_color": "Text color",
    "background": "Background",
    "middle_background": "Middle background",
    "frame": "Frame",
}
PROFILE_ASSET_SETTINGS: Final[tuple[str, ...]] = (
    "background",
    "middle_background",
    "frame",
)
PROFILE_DEFAULT_ASSETS: Final[dict[str, str]] = {
    "background": "default",
    "middle_background": "white",
    "frame": "none",
}
PROFILE_SHOP_CURRENCY: Final[str] = "Pokédollar"
BINGO_QUEST_REWARD: Final[int] = 25
BINGO_BLACKOUT_REWARD: Final[int] = 200
PROFILE_SHOP_PAGE_SIZE: Final[int] = 10
PROFILE_SHOP_CURRENCY_ICON: Final[Path] = (
    Path(__file__).with_name("assets") / "pokedollar.png"
)
PROFILE_SHOP_CURRENCY_ICON_FILENAME: Final[str] = "pokedollar.png"
GIGANTAMAX_EMOJI: Final[str] = "<:gigantamax_icon_by_jormxdos_dffv:1570591025322528828>"
PROFILE_EMOJI_URLS: Final[dict[str, str]] = {
    "low_iv": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f4c9.png",
    "high_iv": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f4c8.png",
    "shiny": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/2728.png",
    "gmax": "https://cdn.discordapp.com/emojis/1504098787658961028.png?size=64",
    "missingno": "https://cdn.discordapp.com/emojis/1563908280445575300.png?size=64",
}


def profile_setting_choices_for_user(
    user_id: int,
    setting: str,
) -> dict[str, tuple[str, str]]:
    choices = PROFILE_SETTING_CHOICES.get(setting, {})
    restricted_choices = set()
    for owner_id, owner_choices in PROFILE_USER_ONLY_CHOICES.items():
        if owner_id != user_id and user_id not in PROFILE_ALL_ACCESS_USER_IDS:
            restricted_choices.update(owner_choices.get(setting, frozenset()))
    return {
        value: choice
        for value, choice in choices.items()
        if value not in restricted_choices
    }


def profile_asset_id(setting: str, key: str) -> str:
    return f"{setting}:{key}"


def profile_asset_codes() -> dict[str, str]:
    asset_ids = sorted(
        profile_asset_id(setting, key)
        for setting in PROFILE_ASSET_SETTINGS
        for key in PROFILE_SETTING_CHOICES[setting]
        if key != PROFILE_DEFAULT_ASSETS[setting]
    )
    codes: dict[str, str] = {}
    used_codes: set[str] = set()
    for asset_id in asset_ids:
        suffix = 0
        while True:
            digest = hashlib.sha256(f"{asset_id}:{suffix}".encode()).hexdigest()
            code = digest[:7].upper()
            if code not in used_codes:
                codes[asset_id] = code
                used_codes.add(code)
                break
            suffix += 1
    return codes


def profile_inventory_code(
    user_id: str,
    asset_id: str,
    copy_number: int,
    used_codes: set[str],
) -> str:
    salt = 0
    while True:
        value = f"inventory:{user_id}:{asset_id}:{copy_number}:{salt}"
        code = hashlib.sha256(value.encode()).hexdigest()[:7].upper()
        if code not in used_codes:
            used_codes.add(code)
            return code
        salt += 1


def profile_inventory_item(asset_id: str, code: str) -> dict[str, str]:
    setting, _, key = asset_id.partition(":")
    return {"code": code, "type": setting, "key": key}


def load_profile_shop(path: Path) -> dict[str, dict[str, str | int]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read profile shop from {path}") from error
    if not isinstance(data, dict) or set(data) != {"items"} or not isinstance(data["items"], list):
        raise ValueError(f"Profile shop in {path} has an invalid format")

    items: dict[str, dict[str, str | int]] = {}
    for entry in data["items"]:
        if not isinstance(entry, dict):
            raise ValueError(f"Profile shop in {path} has an invalid item")
        setting = entry.get("type")
        key = entry.get("key")
        price = entry.get("price")
        currency = entry.get("currency", PROFILE_SHOP_CURRENCY)
        if (
            not isinstance(setting, str)
            or setting not in PROFILE_ASSET_SETTINGS
            or not isinstance(key, str)
            or key not in PROFILE_SETTING_CHOICES[setting]
            or key == PROFILE_DEFAULT_ASSETS[setting]
            or isinstance(price, bool)
            or not isinstance(price, int)
            or price < 0
            or not isinstance(currency, str)
            or not currency.strip()
        ):
            raise ValueError(f"Profile shop in {path} has an invalid item")
        asset_id = profile_asset_id(setting, key)
        if asset_id in items:
            raise ValueError(f"Profile shop in {path} has a duplicate item")
        items[asset_id] = {
            "type": setting,
            "key": key,
            "price": price,
            "currency": currency.strip(),
        }
    return items


def load_profile_inventory(
    path: Path,
    profiles: dict[str, dict[str, int | str]],
) -> dict[str, dict[str, Any]]:
    used_codes = set(profile_asset_codes().values())
    if not path.exists():
        users: dict[str, dict[str, Any]] = {}
        for user_id, settings in sorted(profiles.items()):
            assets: list[dict[str, str]] = []
            for setting in PROFILE_ASSET_SETTINGS:
                key = str(settings.get(setting, PROFILE_DEFAULT_ASSETS[setting]))
                if key == PROFILE_DEFAULT_ASSETS[setting]:
                    continue
                asset_id = profile_asset_id(setting, key)
                code = profile_inventory_code(user_id, asset_id, 1, used_codes)
                assets.append(profile_inventory_item(asset_id, code))
            if assets:
                users[user_id] = {"balances": {}, "assets": assets}
        return users
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read profile inventory from {path}") from error
    if not isinstance(data, dict) or set(data) != {"users"} or not isinstance(data["users"], dict):
        raise ValueError(f"Profile inventory in {path} has an invalid format")

    users: dict[str, dict[str, Any]] = {}
    for user_id, stored_inventory in sorted(data["users"].items()):
        if (
            not isinstance(user_id, str)
            or not user_id.isdecimal()
            or not isinstance(stored_inventory, dict)
            or not isinstance(stored_inventory.get("balances", {}), dict)
            or not isinstance(stored_inventory.get("assets", []), list)
        ):
            raise ValueError(f"Profile inventory in {path} has an invalid user")
        balances = stored_inventory.get("balances", {})
        if any(
            not isinstance(currency, str)
            or not currency.strip()
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount < 0
            for currency, amount in balances.items()
        ):
            raise ValueError(f"Profile inventory in {path} has an invalid balance")
        assets: list[dict[str, str]] = []
        copy_counts: dict[str, int] = {}
        for stored_asset in stored_inventory.get("assets", []):
            if isinstance(stored_asset, str):
                setting, separator, key = stored_asset.partition(":")
                if not separator:
                    raise ValueError(f"Profile inventory in {path} has an invalid asset")
                asset_id = profile_asset_id(setting, key)
                copy_number = copy_counts.get(asset_id, 0) + 1
                copy_counts[asset_id] = copy_number
                code = profile_inventory_code(user_id, asset_id, copy_number, used_codes)
            elif isinstance(stored_asset, dict):
                setting = stored_asset.get("type")
                key = stored_asset.get("key")
                code = stored_asset.get("code")
                if (
                    not isinstance(setting, str)
                    or not isinstance(key, str)
                    or not isinstance(code, str)
                    or re.fullmatch(r"[A-Z0-9]{7}", code) is None
                ):
                    raise ValueError(f"Profile inventory in {path} has an invalid asset")
                asset_id = profile_asset_id(setting, key)
                if code in used_codes:
                    raise ValueError(f"Profile inventory in {path} has duplicate asset codes")
                used_codes.add(code)
                copy_counts[asset_id] = copy_counts.get(asset_id, 0) + 1
            else:
                raise ValueError(f"Profile inventory in {path} has an invalid asset")
            if (
                setting not in PROFILE_ASSET_SETTINGS
                or key not in PROFILE_SETTING_CHOICES[setting]
                or key == PROFILE_DEFAULT_ASSETS[setting]
            ):
                raise ValueError(f"Profile inventory in {path} has an invalid asset")
            assets.append(profile_inventory_item(asset_id, code))
        users[user_id] = {
            "balances": dict(balances),
            "assets": assets,
        }

    for user_id, settings in sorted(profiles.items()):
        inventory = users.setdefault(user_id, {"balances": {}, "assets": []})
        owned_asset_ids = {
            profile_asset_id(asset["type"], asset["key"])
            for asset in inventory["assets"]
        }
        copy_counts: dict[str, int] = {}
        for asset in inventory["assets"]:
            asset_id = profile_asset_id(asset["type"], asset["key"])
            copy_counts[asset_id] = copy_counts.get(asset_id, 0) + 1
        for setting in PROFILE_ASSET_SETTINGS:
            key = str(settings.get(setting, PROFILE_DEFAULT_ASSETS[setting]))
            if key == PROFILE_DEFAULT_ASSETS[setting]:
                continue
            asset_id = profile_asset_id(setting, key)
            if asset_id in owned_asset_ids:
                continue
            copy_number = copy_counts.get(asset_id, 0) + 1
            code = profile_inventory_code(user_id, asset_id, copy_number, used_codes)
            inventory["assets"].append(profile_inventory_item(asset_id, code))
            owned_asset_ids.add(asset_id)
    return users


def save_profile_inventory(
    path: Path,
    users: dict[str, dict[str, Any]],
) -> None:
    data = {"users": users}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save profile inventory to {path}") from error


def load_pokemon_forms(path: Path) -> dict[str, list[dict[str, str]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load Pokémon form catalog from {path}") from error

    if not isinstance(data, dict) or not isinstance(data.get("forms"), dict):
        raise ValueError(f"Pokémon form catalog at {path} has an invalid format")

    forms: dict[str, list[dict[str, str]]] = {}
    for species_name, entries in data["forms"].items():
        if not isinstance(species_name, str) or not isinstance(entries, list):
            raise ValueError(f"Pokémon form catalog at {path} has an invalid entry")
        validated_entries = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("identifier"), str)
                or not isinstance(entry.get("display_name"), str)
            ):
                raise ValueError(f"Pokémon form catalog at {path} has an invalid form")
            validated_entries.append(
                {
                    "identifier": entry["identifier"],
                    "display_name": canonicalize_regional_name(
                        entry["display_name"]
                    ),
                }
            )
        forms[species_name] = validated_entries
    return forms


def normalize_pokemon_alias(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name).casefold()
    return re.sub(r"[\s_-]+", " ", normalized).strip()


def load_single_type_aliases(path: Path, key: str) -> frozenset[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load Pokémon form catalog from {path}") from error

    aliases = data.get(key) if isinstance(data, dict) else None
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) for alias in aliases
    ):
        raise ValueError(f"Pokémon form catalog at {path} has invalid {key} data")
    return frozenset(normalize_pokemon_alias(alias) for alias in aliases)


POKEMON_FORMS: Final[dict[str, list[dict[str, str]]]] = load_pokemon_forms(
    data_path("pokemon_forms.json")
)
SINGLE_TYPE_FIRE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "single_type_fire_aliases",
)
SINGLE_TYPE_NORMAL_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "single_type_normal_aliases",
)
SINGLE_TYPE_WATER_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "single_type_water_aliases",
)
SINGLE_TYPE_ELECTRIC_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "single_type_electric_aliases",
)
SINGLE_TYPE_GRASS_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "single_type_grass_aliases",
)
SINGLE_TYPE_ICE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "single_type_ice_aliases",
)
ICE_AND_FIRE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "ice_and_fire_type_aliases",
)
ICE_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "ice_and_water_type_aliases",
)
ICE_AND_ELECTRIC_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "ice_and_electric_type_aliases",
)
NORMAL_AND_ICE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "normal_and_ice_type_aliases",
)
GRASS_AND_FIRE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "grass_and_fire_type_aliases",
)
GRASS_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "grass_and_water_type_aliases",
)
GRASS_AND_NORMAL_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "grass_and_normal_type_aliases",
)
GRASS_AND_ELECTRIC_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "grass_and_electric_type_aliases",
)
NORMAL_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "normal_and_water_type_aliases",
)
WATER_AND_FIRE_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "water_and_fire_type_aliases",
)
FIRE_AND_ELECTRIC_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "fire_and_electric_type_aliases",
)
ELECTRIC_AND_WATER_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "electric_and_water_type_aliases",
)
ELECTRIC_AND_NORMAL_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "electric_and_normal_type_aliases",
)
FIRE_AND_NORMAL_TYPE_ALIASES: Final[frozenset[str]] = load_single_type_aliases(
    data_path("pokemon_forms.json"),
    "fire_and_normal_type_aliases",
)

@dataclass(frozen=True)
class Config:
    discord_token: str
    openai_api_key: str | None
    poketwo_bot_id: int
    max_concurrent_vision_requests: int
    openai_model: str
    openai_image_detail: str = "high"

    @classmethod
    def from_environment(cls) -> "Config":
        in_designated_codespace = (
            os.environ.get("CODESPACES") == "true"
            and os.environ.get("CODESPACE_NAME")
            == "bookish-space-xylophone-gx67456vpq4whwpqx"
        )
        # Set ALLOW_EXTERNAL_HOST=true to explicitly authorize another host.
        external_host_allowed = os.environ.get("ALLOW_EXTERNAL_HOST") == "true"
        if not (in_designated_codespace or external_host_allowed):
            raise ValueError(
                "This bot is only authorized in its designated Codespace "
                "(or set ALLOW_EXTERNAL_HOST=true)"
            )

        discord_token = os.environ.get("DISCORD_TOKEN")
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        poketwo_bot_id = os.environ.get("POKETWO_BOT_ID")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN is required")
        openai_api_key = (openai_api_key or "").strip() or None
        if not poketwo_bot_id:
            raise ValueError("POKETWO_BOT_ID is required")

        image_detail = os.environ.get("OPENAI_IMAGE_DETAIL", "high").strip().lower()
        if image_detail not in {"low", "high", "auto"}:
            raise ValueError("OPENAI_IMAGE_DETAIL must be low, high, or auto")
        try:
            poketwo_bot_id = int(poketwo_bot_id)
            max_concurrent_vision_requests = int(
                os.environ.get("MAX_CONCURRENT_VISION_REQUESTS", "300")
            )
            if not 1 <= max_concurrent_vision_requests <= 300:
                raise ValueError
            return cls(
                discord_token=discord_token,
                openai_api_key=openai_api_key,
                poketwo_bot_id=poketwo_bot_id,
                max_concurrent_vision_requests=max_concurrent_vision_requests,
                openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                openai_image_detail=image_detail,
            )
        except ValueError as error:
            raise ValueError(
                "POKETWO_BOT_ID must be a positive numeric Discord ID; "
                "MAX_CONCURRENT_VISION_REQUESTS must be an integer from 1 to 300"
            ) from error


def message_text(message: discord.Message) -> str:
    parts = [message.content]
    for embed in message.embeds:
        parts.extend((embed.title or "", embed.description or ""))
        parts.extend((embed.author.name or "", embed.footer.text or ""))
        parts.extend(f"{field.name}: {field.value}" for field in embed.fields)
    return unicodedata.normalize(
        "NFC", "\n".join(part for part in parts if part)
    )


def is_messageable_channel(
    channel: object,
) -> TypeGuard[discord.abc.Messageable]:
    return callable(getattr(channel, "send", None))


def is_renamable_channel(
    channel: object,
) -> TypeGuard[discord.TextChannel | discord.Thread]:
    return callable(getattr(channel, "edit", None))


def poketwo_incense_action(content: str, poketwo_bot_id: int) -> str | None:
    mention = rf"<@!?{poketwo_bot_id}>"
    match = re.search(
        rf"(?:^|\s)(?:{mention}\s+|p!\s*)"
        rf"(?P<buy>inc\s+buy\s+-y)\b|"
        rf"(?:^|\s)(?:{mention}\s+|p!\s*)"
        rf"(?P<start>buy\s+incense)\b|"
        rf"(?:^|\s)(?:{mention}\s+|p!\s*)"
        rf"(?P<stop>stopincense)\b",
        content,
        re.IGNORECASE,
    )
    if match is None:
        return None
    if match.group("buy"):
        return "buy"
    return "start" if match.group("start") else "stop"


def incense_action_from_message(
    message: discord.Message,
    poketwo_bot_id: int,
) -> str | None:
    if message.author.id == poketwo_bot_id:
        if re.search(
            r"\bYou purchased an Incense\b",
            message_text(message),
            re.IGNORECASE,
        ):
            return "buy"
        status = re.search(
            r"\bIncense\s*:\s*(Active|Inactive)\b",
            message_text(message),
            re.IGNORECASE,
        )
        if status is None:
            return None
        return "start" if status.group(1).casefold() == "active" else "stop"
    return poketwo_incense_action(message.content, poketwo_bot_id)


def image_url(message: discord.Message) -> str | None:
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                return attachment.url
    for embed in message.embeds:
        for image in (embed.image, embed.thumbnail):
            if image.url:
                return image.url
    return None


LOW_ACCURACY_THRESHOLD = 50
CORROBORATED_CONFIDENCE_FLOOR = 85.0
CORRECTION_FIELDS = (
    "image_sha256",
    "correct_name",
    "source_message_id",
    "previous_guess",
    "previous_confidence",
    "corrected_by",
    "alert_message_id",
)


def load_image_corrections(path: Path) -> dict[str, str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != list(CORRECTION_FIELDS):
                raise ValueError(f"Invalid correction CSV header in {path}")
            corrections: dict[str, str] = {}
            for row in reader:
                digest = row.get("image_sha256", "")
                name = row.get("correct_name", "")
                if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest) or not name:
                    raise ValueError(f"Invalid correction CSV row in {path}")
                corrections[digest] = name
            return corrections
    except FileNotFoundError:
        return {}


def append_image_correction(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CORRECTION_FIELDS)
        if file.tell() == 0:
            writer.writeheader()
        writer.writerow(row)


def append_pokemon_confidence(path: Path, name: str, confidence: float) -> None:
    try:
        with path.open("a", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            if file.tell() == 0:
                writer.writerow(("pokemon_name", "confidence_percent"))
            writer.writerow((name, f"{confidence:.2f}"))
    except OSError:
        logger.exception("Could not save Pokemon confidence to %s", path)


def load_pokemon_confidence_names(path: Path) -> set[str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            return {
                normalize_pokemon_alias(name)
                for row in csv.DictReader(file)
                if isinstance((name := row.get("pokemon_name")), str) and name.strip()
            }
    except FileNotFoundError:
        return set()
    except (OSError, csv.Error):
        logger.exception("Could not read Pokemon confidence file %s", path)
        return set()


def load_low_accuracy_channels(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): value
        for key, value in data.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def save_low_accuracy_channels(path: Path, channels: dict[str, int]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(channels), encoding="utf-8")
    temporary.replace(path)


def load_command_permissions(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read command permissions from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Command permissions in {path} have an invalid format")

    permissions: dict[str, int] = {}
    for guild_id, role_id in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(role_id, int)
            or isinstance(role_id, bool)
            or role_id <= 0
        ):
            raise ValueError(f"Command permissions in {path} have an invalid entry")
        permissions[guild_id] = role_id
    return permissions


def save_command_permissions(path: Path, permissions: dict[str, int]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(permissions, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save command permissions to {path}") from error


def load_command_locks(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read command locks from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Command locks in {path} have an invalid format")

    locks: dict[str, bool] = {}
    for guild_id, locked in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(locked, bool)
        ):
            raise ValueError(f"Command locks in {path} have an invalid entry")
        locks[guild_id] = locked
    return locks


def save_command_locks(path: Path, locks: dict[str, bool]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(locks, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save command locks to {path}") from error


def load_auto_pause_incense_settings(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read auto-pause settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Auto-pause settings in {path} have an invalid format")

    settings: dict[str, bool] = {}
    for guild_id, enabled in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(enabled, bool)
        ):
            raise ValueError(f"Auto-pause settings in {path} have an invalid entry")
        settings[guild_id] = enabled
    return settings


def save_auto_pause_incense_settings(
    path: Path,
    settings: dict[str, bool],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save auto-pause settings to {path}") from error


def load_premium_servers(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read premium servers from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Premium servers in {path} have an invalid format")

    premium_servers: dict[str, str] = {}
    for guild_id, tier in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(tier, str)
            or tier.casefold() not in PREMIUM_TIER_LIMITS
        ):
            raise ValueError(f"Premium servers in {path} have an invalid entry")
        premium_servers[guild_id] = tier.casefold()
    return premium_servers


def save_premium_servers(path: Path, premium_servers: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(premium_servers, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save premium servers to {path}") from error


def build_premium_status_embeds(current_tier: str | None) -> list[discord.Embed]:
    embeds = []
    for tier, limit in PREMIUM_TIER_LIMITS.items():
        if current_tier is not None and tier != current_tier:
            continue
        _, filename, color = PREMIUM_TIER_BUTTERFLIES[tier]
        status = (
            "✅ Active for this server"
            if current_tier == tier
            else "Not active for this server"
        )
        embed = discord.Embed(
            title=f"{tier.title()} Premium",
            description=(
                f"**Spawn naming:** up to {limit} simultaneous spawns\n"
                f"**Status:** {status}"
            ),
            color=color,
        )
        embed.set_thumbnail(url=f"attachment://{filename}")
        embeds.append(embed)
    return embeds


def premium_status_files(current_tier: str | None = None) -> list[discord.File]:
    thumbnail_dir = Path(__file__).with_name("butterfly_variants")
    return [
        discord.File(thumbnail_dir / filename, filename=filename)
        for tier, (_, filename, _) in PREMIUM_TIER_BUTTERFLIES.items()
        if current_tier is None or tier == current_tier
    ]


def is_image_test_command(content: str) -> bool:
    return (
        re.fullmatch(r"v!test(?:\s+shiny)?\s*", content, re.IGNORECASE)
        is not None
    )


def command_permission_group(content: str) -> str | None:
    content = content.strip()
    if re.fullmatch(r"[vh]!grab", content, re.IGNORECASE):
        return "general"
    if is_image_test_command(content):
        return "general"
    if re.match(r"^v!r\s+search(?:\s|$)", content, re.IGNORECASE):
        return None
    if re.fullmatch(r"v!r\s+<@!?\d+>", content, re.IGNORECASE):
        return None
    if re.fullmatch(r"v!(?:p|pause)(?:\s+all)?", content, re.IGNORECASE):
        return "reserves"
    if re.fullmatch(r"v!r(?:\s+.+)?", content, re.IGNORECASE):
        return "reserves"
    if re.match(
        r"^v!(?:addcategory|categorycreate|categorylist|categorydelete|cd)(?:\s|$)",
        content,
        re.IGNORECASE,
    ):
        return "reserves"
    if re.fullmatch(r"v!settings", content, re.IGNORECASE):
        return "settings"
    if re.match(r"^v!settime(?:\s|$)", content, re.IGNORECASE) or re.fullmatch(
        r"v!timereset", content, re.IGNORECASE
    ):
        return "general"
    if re.fullmatch(r"v!event", content, re.IGNORECASE):
        return "general"
    if PROFILE_BACKFILL_COMMAND_PATTERN.fullmatch(content):
        return "backfill"
    return None


PREMIUM_ONLY_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!(?:grab|r\s+(?:add|e|exchange))(?:\s|$)",
    re.IGNORECASE,
)


def is_premium_only_command(content: str) -> bool:
    return PREMIUM_ONLY_COMMAND_PATTERN.match(content.strip()) is not None


def is_premium_server_owner(bot: object, member: object) -> bool:
    guild = getattr(member, "guild", None)
    tier_for_guild = getattr(bot, "premium_tier_for_guild", None)
    if guild is None or not callable(tier_for_guild):
        return False
    return (
        getattr(guild, "owner_id", None) == getattr(member, "id", object())
        and tier_for_guild(guild.id) is not None
    )


def is_privileged_manager(member: object) -> bool:
    guild_id = getattr(getattr(member, "guild", None), "id", None)
    manager_id = PRIVILEGED_MANAGER_IDS.get(guild_id) if isinstance(guild_id, int) else None
    return manager_id is not None and getattr(member, "id", None) == manager_id


def member_guild_permissions(member: object) -> discord.Permissions | None:
    if is_privileged_manager(member):
        return discord.Permissions.all()
    return getattr(member, "guild_permissions", None)


def member_is_administrator(member: object) -> bool:
    permissions = member_guild_permissions(member)
    return permissions is not None and permissions.administrator


def member_has_role_id(member: object, role_id: int) -> bool:
    return any(
        getattr(role, "id", None) == role_id
        for role in getattr(member, "roles", ())
    )


def command_role_id_for_guild(bot: object, guild_id: int) -> int | None:
    permissions = getattr(bot, "command_permissions", None)
    if not isinstance(permissions, dict):
        return None
    role_id = permissions.get(str(guild_id))
    return (
        role_id
        if isinstance(role_id, int) and not isinstance(role_id, bool)
        else None
    )


def member_has_command_role(bot: object, guild_id: int, member: object) -> bool:
    role_id = command_role_id_for_guild(bot, guild_id)
    return role_id is not None and member_has_role_id(member, role_id)


def has_reserve_manager_access(
    bot: object, guild_id: int, member: object
) -> bool:
    return (
        member_has_role_id(member, RESERVE_ROLE_ID)
        or member_has_command_role(bot, guild_id, member)
        or is_premium_server_owner(bot, member)
        or is_privileged_manager(member)
    )


def has_manage_server_access(bot: object, guild_id: int, member: object) -> bool:
    permissions = member_guild_permissions(member)
    return (
        member_has_command_role(bot, guild_id, member)
        or is_premium_server_owner(bot, member)
        or bool(getattr(permissions, "manage_guild", False))
    )


def can_use_permission_group(
    bot: object,
    group: str,
    guild_id: int,
    member: object,
) -> bool:
    role_id = command_role_id_for_guild(bot, guild_id)
    if (
        role_id is None
        or member_has_role_id(member, role_id)
        or is_premium_server_owner(bot, member)
        or is_privileged_manager(member)
    ):
        return True
    if group == "reserves":
        return member_has_role_id(member, RESERVE_ROLE_ID)
    permissions = member_guild_permissions(member)
    if group == "settings":
        return bool(getattr(permissions, "manage_guild", False))
    if group == "backfill":
        return bool(getattr(permissions, "administrator", False))
    return False


class NoMatchError(Exception):
    pass


def local_fallback_prediction(
    matcher: ImageMatcher | None,
    image_bytes: bytes,
) -> tuple[str, float] | None:
    if matcher is None:
        return None
    guess = matcher.best_guess(image_bytes)
    if guess is None:
        return None
    name, votes = guess
    needed = max(1, minimum_votes_for(name))
    confidence = round(min(49.99, votes / needed * 49.99), 2)
    # Plumage forms share one shape, so enough votes plus a matching colour is a solid answer.
    if (
        name in SQUAWKABILLY_PLUMAGE_FORMS
        and votes >= needed
        and squawkabilly_form_by_color(image_bytes) == name
    ):
        logger.info("Squawkabilly plumage confirmed by colour: %s (%d votes)", name, votes)
        return name, CORROBORATED_CONFIDENCE_FLOOR
    logger.warning(
        "Using low-confidence local guess %s (%d reference votes)",
        name,
        votes,
    )
    return name, confidence


async def download_image(
    http: aiohttp.ClientSession, url: str
) -> tuple[bytes, str]:
    async with http.get(url) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise ValueError(f"Spawn image URL returned non-image content: {content_type}")
        image_bytes = await response.read()
    if not image_bytes:
        raise ValueError("Spawn image was empty")
    return image_bytes, content_type


async def recognize_pokemon(
    url: str,
    *,
    client: AsyncOpenAI | None,
    http: aiohttp.ClientSession,
    model: str,
    detail: str = "high",
    matcher: ImageMatcher | None = None,
) -> tuple[str, float]:
    downloaded: tuple[bytes, str] | None = None
    download_seconds = 0.0
    match_seconds = 0.0
    if matcher is not None and (
        matcher.entries or matcher.exact_references or matcher.corrected_references
    ):
        download_started = time.monotonic()
        downloaded = await download_image(http, url)
        download_seconds = time.monotonic() - download_started
        match_started = time.monotonic()
        found = await asyncio.to_thread(matcher.match, downloaded[0])
        match_seconds = time.monotonic() - match_started
        if found is not None:
            if found[1] == 0:
                logger.info(
                    "Matched %s from an exact reference image "
                    "[download %.2fs, match %.2fs]",
                    found[0],
                    download_seconds,
                    match_seconds,
                )
            else:
                logger.info(
                    "Matched %s from reference images (%d votes) "
                    "[download %.2fs, match %.2fs]",
                    *found,
                    download_seconds,
                    match_seconds,
                )
            return found[0], 100.0
    logger.info(
        "No reference match [download %.2fs, match %.2fs]",
        download_seconds,
        match_seconds,
    )

    if client is None:
        fallback = (
            local_fallback_prediction(matcher, downloaded[0])
            if downloaded is not None
            else None
        )
        if fallback is not None:
            return fallback
        raise NoMatchError("No reference image matched and OpenAI is not configured")

    prediction: tuple[str, float] | None = None
    if downloaded is None:
        # Letting OpenAI fetch the image skips our own download and base64 step.
        try:
            prediction = await request_prediction(
                url, client=client, model=model, detail=detail
            )
        except BadRequestError:
            logger.info("OpenAI could not fetch the image URL; uploading it instead")
            downloaded = await download_image(http, url)
        except (OpenAIError, asyncio.TimeoutError, ValueError):
            logger.exception("Vision prediction failed; trying a local best guess")
            downloaded = await download_image(http, url)
            fallback = local_fallback_prediction(matcher, downloaded[0])
            if fallback is not None:
                return fallback
            raise
        else:
            if prediction[0] not in VIVILLON_FORM_SET or cv2 is None:
                return prediction
            downloaded = await download_image(http, url)

    image_bytes, content_type = downloaded
    if prediction is None:
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        try:
            prediction = await request_prediction(
                f"data:{content_type};base64,{encoded_image}",
                client=client,
                model=model,
                detail=detail,
            )
        except (OpenAIError, asyncio.TimeoutError, ValueError):
            logger.exception("Vision prediction failed; trying a local best guess")
            fallback = local_fallback_prediction(matcher, image_bytes)
            if fallback is not None:
                return fallback
            raise
    if prediction[0] in VIVILLON_FORM_SET and cv2 is not None:
        matched_form = await asyncio.to_thread(vivillon_form_by_pattern, image_bytes)
        if matched_form is None:
            logger.info("Keeping an unverified Vivillon guess at low confidence")
            prediction = prediction[0], min(prediction[1], LOW_ACCURACY_THRESHOLD - 0.01)
        else:
            prediction = matched_form, prediction[1]
    if (
        prediction[1] < LOW_ACCURACY_THRESHOLD
        and matcher is not None
        and downloaded is not None
    ):
        local_guess = await asyncio.to_thread(matcher.best_guess, image_bytes)
        if (
            local_guess is not None
            and normalize_pokemon_alias(local_guess[0])
            == normalize_pokemon_alias(prediction[0])
            and local_guess[1] >= minimum_votes_for(local_guess[0])
        ):
            logger.info(
                "Local matcher corroborated low-confidence guess %s (%d votes)",
                prediction[0],
                local_guess[1],
            )
            prediction = prediction[0], CORROBORATED_CONFIDENCE_FLOOR
    return prediction


async def request_prediction(
    image_ref: str,
    *,
    client: AsyncOpenAI,
    model: str,
    detail: str,
) -> tuple[str, float]:
    custom_forms = "; ".join(
        f"{form} (base species: {species})"
        for form, species in sorted(CUSTOM_FORM_SPECIES.items())
    )
    if detail == "auto":
        image_detail: Literal["auto", "low", "high"] = "auto"
    elif detail == "low":
        image_detail = "low"
    elif detail == "high":
        image_detail = "high"
    else:
        raise ValueError(f"Unsupported image detail setting: {detail}")
    system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "Identify the Pokémon species shown in this Pokétwo wild-spawn "
                "image. The species may be any Pokémon in the National Pokédex "
                "through #1026. Inspect the Pokémon itself and compare its overall "
                "silhouette, body proportions, face, appendages, colors, markings, "
                "and distinctive accessories. If this is a Discord screenshot, "
                "focus on the largest embedded wild-spawn artwork; ignore "
                "surrounding chat, UI text, other bot guesses, and smaller "
                "catch-card thumbnails. Use multiple visible traits to "
                "identify it; do not rely on a single color, type, pose, background, "
                "or habitat. For Finizen versus Palafin, specifically check the "
                "chest/underside: Palafin has a red, heart-shaped mark there, while "
                "Finizen does not. Use that mark when it is visible; do not guess "
                "Palafin if it is obscured. Pay particular attention to features "
                "that separate similar species and neighboring evolutions. "
                "Identify a regional "
                "variant or alternate forme only when its visible features support "
                "that specific form; do not infer details hidden by the image. "
                "This server also recognizes these custom forms: "
                f"{custom_forms}. When the image clearly matches one, return its "
                "exact listed form name; otherwise return the base species name. "
                "Choose the closest match to the visible evidence, and lower the "
                "confidence when important features are unclear or obscured. "
                "When the Pokémon is clearly visible and its distinctive traits "
                "support one identification, use high confidence; reserve low "
                "confidence for genuinely ambiguous, obscured, or unreadable images. "
                "Return only the single most likely Pokémon or custom form name. "
                "Never return a description, reasoning, multiple candidates, "
                "alternate names, aliases, or a list. Estimate "
                "confidence in that exact identification as a percentage from 0 "
                "to 100 with up to two decimal places; confidence should reflect "
                "how clearly the visible traits support the chosen species and "
                "form. Return JSON only, "
                "in the form "
                '{"name":"one Pokémon or custom form name","confidence":85.34}. '
                "Include a form or regional name when needed to identify the "
                "shown Pokémon. Always provide your single best Pokémon guess, "
                "even when the image is unclear or you are uncertain; lower the "
                "confidence instead of returning an empty name."
            ),
        }
    image_content: ChatCompletionContentPartImageParam = {
        "type": "image_url",
        "image_url": {
            "url": image_ref,
            "detail": image_detail,
        },
    }
    user_message: ChatCompletionUserMessageParam = {
        "role": "user",
        "content": [image_content],
    }
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    result = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        max_completion_tokens=60,
        messages=messages,
    )
    content = result.choices[0].message.content
    if not content:
        raise ValueError("Vision model returned an empty response")
    prediction = json.loads(content)
    if not isinstance(prediction, dict):
        raise ValueError("Vision model response must be a JSON object")
    name = prediction.get("name")
    if not isinstance(name, str):
        raise ValueError("Vision model response did not include a Pokémon name")
    confidence = prediction.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 100
    ):
        raise ValueError("Vision model response included an invalid confidence percentage")
    name = canonicalize_regional_name(unicodedata.normalize("NFC", name.strip()))
    if not name or len(name) > 60 or (
        not is_valid_pokemon_name(name) and not is_missingno_name(name)
    ):
        raise ValueError("Vision model returned an invalid Pokémon name")
    return name, float(confidence)


def is_valid_pokemon_name(name: str) -> bool:
    allowed_punctuation = " .'-:♀♂"
    return bool(name) and any(char.isalpha() for char in name) and all(
        unicodedata.category(char)[0] in {"L", "M", "N"}
        or char in allowed_punctuation
        for char in name
    )


def is_missingno_name(name: str) -> bool:
    return name.strip().casefold().rstrip(".") in {"missingno", "???"}


def display_pokemon_name(name: str) -> str:
    if name.casefold() == "male meowstic":
        return "Meowstic"
    if name.casefold() == "plant wormadam":
        return "Wormadam"
    if name.casefold() == "male basculegion":
        return "Basculegion"
    return FORM_DISPLAY_NAMES.get(canonicalize_regional_name(name), canonicalize_regional_name(name))


def is_unown_form_name(name: str) -> bool:
    return (
        base_pokemon_name(name).casefold() == "unown"
        or UNOWN_LETTER_PATTERN.fullmatch(name) is not None
    )


def unown_display_form(name: str) -> str | None:
    if UNOWN_LETTER_PATTERN.fullmatch(name) is not None:
        return name
    variant = re.fullmatch(r"Unown Variant\s+(\d+)", name, re.IGNORECASE)
    if variant is None:
        return None
    number = int(variant.group(1))
    if 1 <= number <= 26:
        return f"{chr(ord('A') + number - 1)} Unown"
    return {27: "! Unown", 28: "? Unown"}.get(number)


def format_guess(
    name: str, confidence: float, guess_name: str | None = None
) -> str:
    return f"{display_pokemon_name(guess_name or name)}: {confidence:.2f}%"


def shown_form_name(name: str, form_name: str | None) -> str:
    """Silvally types, Vivillon patterns and Arceus types are shown by form, but caught and reserved as the species."""
    unown_form = unown_display_form(form_name or name)
    if unown_form is not None:
        return unown_form
    if form_name in CUSTOM_FORM_SPECIES:
        return form_name
    if (
        form_name in SILVALLY_FORMS
        or form_name in VIVILLON_FORM_SET
        or form_name in ARCEUS_FORM_SET
        or form_name in FORM_DISPLAY_NAMES
    ):
        return form_name
    return name


def format_catch_command(poketwo_bot_id: int, name: str) -> str:
    del poketwo_bot_id
    normalized_name = re.sub(r"[\s_-]+", " ", name.casefold()).strip()
    catch_name = (
        "Unown"
        if is_unown_form_name(name)
        else CATCH_COMMAND_NAME_ALIASES.get(normalized_name, display_pokemon_name(name))
    )
    return f"@Pokétwo#8236 c {catch_name.lower()}"


def format_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    type_ping_user_ids: list[int] | None = None,
    *,
    assisted: bool = True,
    guess_name: str | None = None,
) -> str:
    command = format_catch_command(poketwo_bot_id, name)
    lines = [format_guess(name, confidence, guess_name)]
    lines.extend(
        format_spawn_mention_lines(
            reserved_user_ids,
            shinyhunter_user_ids,
            collection_user_ids,
            type_ping_user_ids,
        )
    )
    if assisted:
        lines.append(f"**Copy Here >** `{command}`")
    return "\n".join(lines)


def is_fire_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES
        or normalized_name in WATER_AND_FIRE_TYPE_ALIASES
        or normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in GRASS_AND_FIRE_TYPE_ALIASES
        or normalized_name in ICE_AND_FIRE_TYPE_ALIASES
        or is_single_type_fire_pokemon(name)
    )


def is_water_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in NORMAL_AND_WATER_TYPE_ALIASES
        or normalized_name in WATER_AND_FIRE_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES
        or normalized_name in GRASS_AND_WATER_TYPE_ALIASES
        or normalized_name in ICE_AND_WATER_TYPE_ALIASES
        or is_single_type_water_pokemon(name)
    )


def is_normal_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in NORMAL_AND_ICE_TYPE_ALIASES
        or normalized_name in NORMAL_AND_WATER_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES
        or normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES
        or normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES
        or is_single_type_normal_pokemon(name)
    )


def is_electric_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES
        or normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES
        or normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES
        or is_single_type_electric_pokemon(name)
    )


def is_grass_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in GRASS_AND_FIRE_TYPE_ALIASES
        or normalized_name in GRASS_AND_WATER_TYPE_ALIASES
        or normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES
        or normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES
        or is_single_type_grass_pokemon(name)
    )


def is_ice_icon_pokemon(name: str) -> bool:
    normalized_name = normalize_pokemon_alias(name)
    return (
        normalized_name in ICE_AND_FIRE_TYPE_ALIASES
        or normalized_name in ICE_AND_WATER_TYPE_ALIASES
        or normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES
        or normalized_name in NORMAL_AND_ICE_TYPE_ALIASES
        or is_single_type_ice_pokemon(name)
    )


def fire_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES:
        return None
    if normalized_name in WATER_AND_FIRE_TYPE_ALIASES:
        return None
    if normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_FIRE_TYPE_ALIASES:
        return None
    if normalized_name in ICE_AND_FIRE_TYPE_ALIASES:
        return None
    return None


def water_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in NORMAL_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in ICE_AND_WATER_TYPE_ALIASES:
        return None
    return None


def normal_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in NORMAL_AND_ICE_TYPE_ALIASES:
        return None
    if normalized_name in NORMAL_AND_WATER_TYPE_ALIASES:
        return None
    if normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES:
        return None
    if normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES:
        return None
    return None


def electric_companion_icon_filename_for_pokemon(name: str) -> str | None:
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES:
        return None
    if normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES:
        return None
    return None


def format_custom_type_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    include_fire: bool = False,
    include_water: bool = False,
    include_normal: bool = False,
    include_electric: bool = False,
    include_grass: bool = False,
    include_ice: bool = False,
    assisted: bool = True,
    guess_name: str | None = None,
    type_ping_user_ids: list[int] | None = None,
) -> str:
    emoji_by_type = {
        "fire": "<:fire:1560301436074729532>",
        "water": "<:water:1560303864094130357>",
        "normal": "<:Normal:1560305235279482930>",
        "electric": "<:Electric:1560306053164572732>",
        "grass": "<:grass:1560307079896502282>",
        "ice": "<:Ice:1560307867200782386>",
    }
    included_types = {
        type_name
        for type_name, included in (
            ("fire", include_fire),
            ("water", include_water),
            ("normal", include_normal),
            ("electric", include_electric),
            ("grass", include_grass),
            ("ice", include_ice),
        )
        if included
    }
    normalized_name = normalize_pokemon_alias(name)
    if normalized_name in FIRE_AND_NORMAL_TYPE_ALIASES:
        type_order = ("fire", "normal")
    elif normalized_name in NORMAL_AND_WATER_TYPE_ALIASES:
        type_order = ("normal", "water")
    elif normalized_name in WATER_AND_FIRE_TYPE_ALIASES:
        type_order = ("water", "fire")
    elif normalized_name in FIRE_AND_ELECTRIC_TYPE_ALIASES:
        type_order = ("fire", "electric")
    elif normalized_name in ELECTRIC_AND_WATER_TYPE_ALIASES:
        type_order = ("electric", "water")
    elif normalized_name in ELECTRIC_AND_NORMAL_TYPE_ALIASES:
        type_order = ("electric", "normal")
    elif normalized_name in GRASS_AND_ELECTRIC_TYPE_ALIASES:
        type_order = ("grass", "electric")
    elif normalized_name in ICE_AND_ELECTRIC_TYPE_ALIASES:
        type_order = ("ice", "electric")
    elif normalized_name in ICE_AND_FIRE_TYPE_ALIASES:
        type_order = ("ice", "fire")
    elif normalized_name in ICE_AND_WATER_TYPE_ALIASES:
        type_order = ("ice", "water")
    elif normalized_name in NORMAL_AND_ICE_TYPE_ALIASES:
        type_order = ("normal", "ice")
    elif normalized_name in GRASS_AND_FIRE_TYPE_ALIASES:
        type_order = ("grass", "fire")
    elif normalized_name in GRASS_AND_WATER_TYPE_ALIASES:
        type_order = ("grass", "water")
    elif normalized_name in GRASS_AND_NORMAL_TYPE_ALIASES:
        type_order = ("grass", "normal")
    else:
        type_order = ("fire", "water", "normal", "electric", "grass", "ice")
    type_emojis = [
        emoji_by_type[type_name]
        for type_name in type_order
        if type_name in included_types
    ]
    lines = [
        f"{' '.join(type_emojis)} {format_guess(name, confidence, guess_name)}"
    ]
    lines.extend(
        format_spawn_mention_lines(
            reserved_user_ids,
            shinyhunter_user_ids,
            collection_user_ids,
            type_ping_user_ids,
        )
    )
    if assisted:
        lines.append(
            f"**Copy Here >** `{format_catch_command(poketwo_bot_id, name)}`"
        )
    return "\n".join(lines)


def format_spawn_mention_lines(
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    type_ping_user_ids: list[int] | None = None,
) -> list[str]:
    if reserved_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in reserved_user_ids)
        return [f"Reserved: {mentions}"]
    lines = []
    if shinyhunter_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in shinyhunter_user_ids)
        lines.append(f"Shinyhunt: {mentions}")
    if collection_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in collection_user_ids)
        lines.append(f"Collection: {mentions}")
    if type_ping_user_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in type_ping_user_ids)
        lines.append(f"Typeping: {mentions}")
    return lines


TYPE_EMOJIS: Final[dict[str, str]] = {
    "normal": "<:Normal:1560305235279482930>",
    "fire": "<:fire:1560301436074729532>",
    "water": "<:water:1560303864094130357>",
    "electric": "<:Electric:1560306053164572732>",
    "grass": "<:grass:1560307079896502282>",
    "ice": "<:Ice:1560307867200782386>",
    "bug": "<:bug:1564785932496797757>",
    "dark": "<:dark:1564786204699005129>",
    "dragon": "<:Dragon:1564786673840160818>",
    "fairy": "<:Fairy:1564786928631677068>",
    "fighting": "<:Fighting:1564787413547483156>",
    "flying": "<:Flying:1564787610143162489>",
    "ghost": "<:Ghost:1564787837306540213>",
    "ground": "<:Ground:1564789353648230441>",
    "poison": "<:Poison:1564788700687114310>",
    "psychic": "<:Psychic:1564788957437366342>",
    "rock": "<:rock:1564789532384174100>",
    "steel": "<:Steel:1564789710440898610>",
}
TYPE_PING_TYPES: Final[tuple[str, ...]] = tuple(sorted(TYPE_EMOJIS))


def format_type_ping_embed(enabled_types: list[str]) -> discord.Embed:
    enabled = set(enabled_types)
    embed = discord.Embed(title="Type Pings", color=discord.Color.blurple())
    embed.description = "\n".join(
        f"{TYPE_EMOJIS[type_name]} {type_name.title()} "
        f"{'✅' if type_name in enabled else '❌'}"
        for type_name in TYPE_PING_TYPES
    )
    return embed


def _type_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold())
    return re.sub(
        r"[^a-z0-9]", "", "".join(c for c in folded if not unicodedata.combining(c))
    )


def load_pokemon_types(path: Path) -> dict[str, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load Pokémon types from %s", path)
        return {}
    return {
        _type_key(name): [t for t in types if t in TYPE_EMOJIS]
        for name, types in data.items()
        if isinstance(name, str) and isinstance(types, list)
    }


POKEMON_TYPES: Final[dict[str, list[str]]] = load_pokemon_types(
    data_path("pokemon_types.json")
)


def pokemon_types_for(*names: str | None) -> list[str]:
    """Types of a Pokémon, trying the most specific name first."""
    for name in names:
        if not name:
            continue
        for kind in ("Silvally", "Arceus"):
            prefix = name.removesuffix(f" {kind}")
            if prefix != name and _type_key(prefix) in TYPE_EMOJIS:
                return [_type_key(prefix)]
        if name in VIVILLON_FORM_SET:
            return ["bug", "flying"]
        types = POKEMON_TYPES.get(_type_key(name))
        if types:
            return types
    return []


def type_emoji_text(*names: str | None) -> str:
    return "".join(TYPE_EMOJIS[t] for t in pokemon_types_for(*names))


def type_ping_user_ids_for_pokemon(
    type_pings: dict[str, list[str]],
    guild_id: int,
    pokemon_types: list[str],
) -> list[int]:
    matching_types = set(pokemon_types)
    matching_user_ids = []
    for key, enabled_types in type_pings.items():
        stored_guild_id, separator, stored_user_id = key.partition(":")
        if (
            separator
            and stored_guild_id == str(guild_id)
            and matching_types.intersection(enabled_types)
        ):
            matching_user_ids.append(int(stored_user_id))
    return sorted(matching_user_ids)


def format_typed_spawn_reply(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    type_emojis: str,
    reserved_user_ids: list[int] | None = None,
    shinyhunter_user_ids: list[int] | None = None,
    collection_user_ids: list[int] | None = None,
    type_ping_user_ids: list[int] | None = None,
    *,
    assisted: bool = True,
    guess_name: str | None = None,
) -> str:
    lines = [f"{type_emojis} {format_guess(name, confidence, guess_name)}"]
    lines.extend(
        format_spawn_mention_lines(
            reserved_user_ids,
            shinyhunter_user_ids,
            collection_user_ids,
            type_ping_user_ids,
        )
    )
    if assisted:
        lines.append(f"**Copy Here >** `{format_catch_command(poketwo_bot_id, name)}`")
    return "\n".join(lines)


def is_single_type_pokemon(name: str, type_aliases: frozenset[str]) -> bool:
    return normalize_pokemon_alias(name) in type_aliases


def is_single_type_fire_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_FIRE_ALIASES)


def is_single_type_normal_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_NORMAL_ALIASES)


def is_single_type_water_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_WATER_ALIASES)


def is_single_type_electric_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_ELECTRIC_ALIASES)


def is_single_type_grass_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_GRASS_ALIASES)


def is_single_type_ice_pokemon(name: str) -> bool:
    return is_single_type_pokemon(name, SINGLE_TYPE_ICE_ALIASES)


def type_icon_filename_for_pokemon(name: str) -> str | None:
    if normalize_pokemon_alias(name) in ICE_AND_WATER_TYPE_ALIASES:
        return "ice_water_type_icons.png"
    if is_single_type_water_pokemon(name):
        return "water_type.png"
    if is_single_type_ice_pokemon(name):
        return "ice_type.png"
    return None


def format_type_spawn_embed(
    name: str,
    confidence: float,
    poketwo_bot_id: int,
    icon_filename: str,
    *,
    assisted: bool = True,
    guess_name: str | None = None,
) -> discord.Embed:
    del confidence, guess_name
    embed = discord.Embed(
        description=(
            f"`{format_catch_command(poketwo_bot_id, name)}`" if assisted else None
        )
    )
    embed.set_thumbnail(url=f"attachment://{icon_filename}")
    return embed


SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/official-artwork/{}.png"
)
SHINY_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/official-artwork/shiny/{}.png"
)
STARBOARD_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/home/{}.png"
)
STARBOARD_SHINY_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/home/shiny/{}.png"
)
PROJECT_POKEMON_SHINY_MODEL_URL = (
    "https://projectpokemon.org/images/shiny-sprite/{}.gif"
)
SHOWDOWN_ANIMATED_SHINY_SPRITE_URL = (
    "https://play.pokemonshowdown.com/sprites/ani-shiny/{}.gif"
)
SWSH_FORM_MODEL_SLUGS: Final[dict[str, str]] = {
    "Galarian Articuno": "articuno-galar",
    "Galarian Moltres": "moltres-galar",
    "Galarian Zapdos": "zapdos-galar",
}


@lru_cache(maxsize=1)
def load_sprite_ids() -> dict[str, int]:
    path = data_path("pokemon_sprites.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sprite_url_for_pokemon(name: str, *, shiny: bool = False) -> str | None:
    sprite_id = load_sprite_ids().get(name)
    if not sprite_id:
        return None
    return (SHINY_SPRITE_URL if shiny else SPRITE_URL).format(sprite_id)


def starboard_sprite_url_for_pokemon(
    name: str,
    *,
    shiny: bool = False,
) -> str | None:
    sprite_id = load_sprite_ids().get(name)
    if not sprite_id:
        return None
    url = STARBOARD_SHINY_SPRITE_URL if shiny else STARBOARD_SPRITE_URL
    return url.format(sprite_id)


def pokemon_sprite_slug(name: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
        .replace("'", "")
        .replace("’", "")
    )
    for prefix, suffix in (
        ("alolan ", "alola"),
        ("galarian ", "galar"),
        ("hisuian ", "hisui"),
        ("paldean ", "paldea"),
    ):
        if normalized.startswith(prefix):
            normalized = f"{normalized[len(prefix):]} {suffix}"
            break
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


THUMBNAIL_ASSETS_DIR: Final[Path] = Path(__file__).with_name("assets") / "thumbnails"


def custom_thumbnail_path(name: str) -> Path | None:
    """Bundled artwork for Pokémon or forms needing a non-default sprite."""
    filename = re.sub(r"[^a-z0-9]", "", normalize_pokemon_alias(name)) + ".png"
    path = THUMBNAIL_ASSETS_DIR / filename
    return path if path.is_file() else None


def custom_starboard_thumbnail_path(
    details: "CatchDetails", category: str
) -> Path | None:
    del category
    if details.shiny:
        filename = re.sub(
            r"[^a-z0-9]", "", normalize_pokemon_alias(details.pokemon)
        ) + ".png"
        shiny_path = THUMBNAIL_ASSETS_DIR / "shiny" / filename
        if shiny_path.is_file():
            return shiny_path
    return custom_thumbnail_path(details.pokemon)


def catch_card_files(name: str, thumbnail_name: str | None = None) -> list[discord.File]:
    path = custom_thumbnail_path(thumbnail_name or name)
    return [discord.File(path, filename=path.name)] if path else []


def format_pc_catch_embed(
    name: str, thumbnail_name: str | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Catch {display_pokemon_name(shown_form_name(name, thumbnail_name))}",
        description=(
            f"Copy Below\n"
            f"```\n{format_catch_command(POKETWO_COMMAND_BOT_ID, name)}\n```"
        ),
    )
    custom_path = custom_thumbnail_path(thumbnail_name or name)
    sprite_url = sprite_url_for_pokemon(name)
    if custom_path:
        embed.set_thumbnail(url=f"attachment://{custom_path.name}")
    elif sprite_url:
        embed.set_thumbnail(url=sprite_url)
    return embed


@dataclass(frozen=True)
class CatchDetails:
    user_id: int | None
    pokemon: str
    level: str
    iv: str
    iv_value: float | None
    gender: str | None
    shiny: bool
    chain: int | None
    gigantamax: bool
    missingno: bool
    trainer: str | None = None


def parse_catch_details(
    text: str,
    *,
    user_id: int | None = None,
) -> CatchDetails | None:
    catch_match = re.search(r"\byou caught\b(?P<body>[^\n]*)", text, re.IGNORECASE)
    if catch_match is None:
        return None

    user_match = re.search(
        r"\bcongratulations\s+<@!?(\d+)>",
        text[: catch_match.start()],
        re.IGNORECASE,
    )
    if user_match is None and user_id is None:
        return None
    caught_user_id = (
        int(user_match.group(1)) if user_match is not None else user_id
    )
    if caught_user_id is None:
        return None

    body = catch_match.group("body").strip()
    level_match = re.search(
        r"\b(?:level|lv\.?)\s*(\d+|\?{2,})",
        body,
        re.IGNORECASE,
    )
    if level_match is None:
        level = "???"
        pokemon_text = body.split("!", 1)[0].strip()
        pokemon_text = re.sub(r"^a\s+", "", pokemon_text, flags=re.IGNORECASE)
        pokemon_text = re.sub(
            r"\s*\(\s*(?:\d+(?:[.,]\d+)?|\?{2,})\s*%?\s*\)\s*$",
            "",
            pokemon_text,
        ).strip()
        if not is_missingno_name(pokemon_text):
            return None
    else:
        level = level_match.group(1)
        pokemon_text = body[level_match.end() :].strip()
        pokemon_text = re.sub(r"^[.!,:;]+\s*", "", pokemon_text)
        pokemon_text = pokemon_text.split("!", 1)[0].strip()
        pokemon_text = re.sub(
            r"\s*\(\s*(?:\d+(?:[.,]\d+)?|\?{2,})\s*%?\s*\)\s*$",
            "",
            pokemon_text,
        ).strip()

    pokemon_text = re.sub(r"<a?:[A-Za-z0-9_~]+:\d+>", " ", pokemon_text).strip()
    gender = None
    if re.search(r"(?:♀|\bfemale\b)", body, re.IGNORECASE):
        gender = "Female"
        pokemon_text = re.sub(r"(?:♀|\bfemale\b)", "", pokemon_text, flags=re.IGNORECASE)
    elif re.search(r"(?:♂|\bmale\b)", body, re.IGNORECASE):
        gender = "Male"
        pokemon_text = re.sub(r"(?:♂|\bmale\b)", "", pokemon_text, flags=re.IGNORECASE)
    pokemon_text = pokemon_text.replace("’", "'").replace("‘", "'")
    pokemon_text = pokemon_text.strip(" .,:;")
    missingno = is_missingno_name(pokemon_text)
    if missingno:
        pokemon_text = "Missingno"
    elif not pokemon_text or not is_valid_pokemon_name(pokemon_text):
        return None

    iv_match = re.search(
        r"\(\s*(\d+(?:[.,]\d+)?|\?{2,})\s*%\s*\)"
        r"|\bIV\s*[:=]\s*(\d+(?:[.,]\d+)?|\?{2,})\s*%?",
        text,
        re.IGNORECASE,
    )
    iv_text = next((value for value in iv_match.groups() if value), None) if iv_match else None
    if iv_text:
        iv_text = iv_text.replace(",", ".")
    if missingno and iv_text is None:
        iv_text = "???"
    iv_value = None
    if iv_text and not iv_text.startswith("?"):
        numeric_iv = float(iv_text)
        if 0 <= numeric_iv <= 100:
            iv_value = numeric_iv
        else:
            iv_text = None
    iv = f"{iv_text}%" if iv_text and not iv_text.startswith("?") else (iv_text or "Unknown")

    shiny = bool(re.search(r"colors seem unusual|✨", text, re.IGNORECASE))
    chain_match = re.search(
        r"\b(?:shiny\s*(?:chain|streak)|chain|streak)\b[^\d]{0,30}(\d+)",
        text,
        re.IGNORECASE,
    )
    chain = int(chain_match.group(1)) if chain_match and shiny else None
    gigantamax = bool(
        re.search(r"\b(?:gigantamax|gmax)\b|gigantamax factor", text, re.IGNORECASE)
    )
    if gigantamax and not re.match(r"^(?:gigantamax|gmax)\b", pokemon_text, re.IGNORECASE):
        pokemon_text = f"Gigantamax {pokemon_text}"

    return CatchDetails(
        user_id=caught_user_id,
        pokemon=display_pokemon_name(pokemon_text),
        level=level,
        iv=iv,
        iv_value=iv_value,
        gender=gender,
        shiny=shiny,
        chain=chain,
        gigantamax=gigantamax,
        missingno=missingno,
    )


def parse_box_shiny_count(text: str) -> int:
    if re.search(
        r"\byou open\s+\d+\b[^\n]*\bchests?\b",
        text,
        re.IGNORECASE,
    ) is None:
        return 0
    shiny_marker = re.compile(
        r"✨|🌟|⭐|colors seem unusual|\bshiny\b|"
        r"<a?:[a-z0-9_~]*(?:shiny|sparkle)[a-z0-9_~]*:\d+>",
        re.IGNORECASE,
    )
    return sum(
        1
        for line in text.splitlines()
        if re.search(r"\b(?:level|lv\.?)\s*\d+\b", line, re.IGNORECASE)
        and shiny_marker.search(line)
    )


def profile_catch_user_id(message: discord.Message) -> int | None:
    match = PROFILE_CATCH_PREFIX_PATTERN.search(message_text(message))
    if match is None:
        return None
    mention = re.search(r"<@!?(\d+)>", match.group("catcher"))
    if mention is not None:
        return int(mention.group(1))
    for user in getattr(message, "mentions", []):
        user_id = getattr(user, "id", None)
        if isinstance(user_id, int) and not isinstance(user_id, bool):
            return user_id
    return None


def is_catch_detection_embed(embed: discord.Embed) -> bool:
    title = embed.title or ""
    footer = embed.footer.text or ""
    return footer == "Catch Detection System" and re.search(
        r"\bCatch Detected!\s*$",
        title,
        re.IGNORECASE,
    ) is not None


def has_catch_detection_embed(message: discord.Message) -> bool:
    return any(is_catch_detection_embed(embed) for embed in message.embeds)


def is_automated_message(message: discord.Message) -> bool:
    return bool(
        getattr(message.author, "bot", False)
        or getattr(message, "webhook_id", None) is not None
        or getattr(message, "application_id", None) is not None
    )


def parse_catch_detection_details(message: discord.Message) -> CatchDetails | None:
    for embed in message.embeds:
        if not is_catch_detection_embed(embed):
            continue
        fields = {}
        for field in embed.fields:
            if isinstance(field.name, str) and isinstance(field.value, str):
                fields[field.name.strip().rstrip(":").strip().casefold()] = (
                    field.value.strip()
                )
        for line in (embed.description or "").splitlines():
            description_field = re.fullmatch(
                r"\s*`{0,3}\s*(trainer|pokemon|level|ivs?)\s*:\s*(.*?)\s*`{0,3}\s*",
                line,
                re.IGNORECASE,
            )
            if description_field is not None:
                name, value = description_field.groups()
                fields.setdefault(name.casefold(), value.strip())
        trainer = fields.get("trainer", "").strip()
        trainer_match = re.search(r"<@!?(\d+)>", trainer)
        pokemon_text = fields.get("pokemon", "").replace("’", "'").replace("‘", "'")
        pokemon_text = re.sub(r"<a?:[A-Za-z0-9_~]+:\d+>", " ", pokemon_text).strip()
        level = fields.get("level", "???")
        iv_text = fields.get("ivs", fields.get("iv", ""))
        iv_text = iv_text.replace(",", ".")
        iv_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%?", iv_text)
        missingno = is_missingno_name(pokemon_text)
        gender = None
        if re.search(r"(?:♀|\bfemale\b)", pokemon_text, re.IGNORECASE):
            gender = "Female"
            pokemon_text = re.sub(
                r"(?:♀|\bfemale\b)", "", pokemon_text, flags=re.IGNORECASE
            )
        elif re.search(r"(?:♂|\bmale\b)", pokemon_text, re.IGNORECASE):
            gender = "Male"
            pokemon_text = re.sub(
                r"(?:♂|\bmale\b)", "", pokemon_text, flags=re.IGNORECASE
            )
        pokemon_text = pokemon_text.strip(" .,:;")
        if missingno:
            pokemon_text = "Missingno"
        report_text = "\n".join(
            [embed.title or "", embed.description or ""]
            + [f"{field.name}: {field.value}" for field in embed.fields]
        )
        shiny = re.search(
            r"\bshiny\b|colors seem unusual|✨", report_text, re.IGNORECASE
        ) is not None
        gigantamax = re.search(
            r"\b(?:gigantamax|gmax)\b|gigantamax factor",
            report_text,
            re.IGNORECASE,
        ) is not None
        chain_match = re.search(
            r"\b(?:shiny\s*(?:chain|streak)|chain|streak)\b[^\d]{0,30}(\d+)",
            report_text,
            re.IGNORECASE,
        )
        if (
            (not missingno and not is_valid_pokemon_name(pokemon_text))
            or re.fullmatch(r"\d+|\?{2,}", level) is None
        ):
            continue
        iv_value = float(iv_match.group(1)) if iv_match else None
        if iv_value is not None and not 0 <= iv_value <= 100:
            continue
        if missingno and iv_value is None:
            iv_text = "???"
        iv = (
            f"{iv_value:g}%"
            if iv_value is not None
            else (iv_text if missingno and re.search(r"\?{2,}", iv_text) else "Unknown")
        )
        if gigantamax and not re.match(
            r"^(?:gigantamax|gmax)\b", pokemon_text, re.IGNORECASE
        ):
            pokemon_text = f"Gigantamax {pokemon_text}"
        return CatchDetails(
            user_id=int(trainer_match.group(1)) if trainer_match else None,
            pokemon=display_pokemon_name(pokemon_text),
            level=level,
            iv=iv,
            iv_value=iv_value,
            gender=gender,
            shiny=shiny,
            chain=int(chain_match.group(1)) if chain_match and shiny else None,
            gigantamax=gigantamax,
            missingno=missingno,
            trainer=trainer if trainer_match is None else None,
        )
    return None


def starboard_category(details: CatchDetails) -> str | None:
    if details.missingno:
        return "missingno"
    if details.gigantamax:
        return "gigantamax"
    if details.shiny:
        return "shiny"
    if details.iv_value is not None and details.iv_value >= 90:
        return "high_iv"
    if details.iv_value is not None and details.iv_value < 10:
        return "low_iv"
    return None


NORMAL_STARBOARD_POKEMON_NAMES: Final[frozenset[str]] = frozenset(
    normalize_pokemon_alias(name).replace("’", "'")
    for name in """
Alolan Ninetales
Alolan Vulpix
Alolan Geodude
Alolan Graveler
Alolan Raticate
Alolan Rattata
Alolan Persian
Alolan Meowth
Alolan Exeggutor
Alolan Dugtrio
Alolan Diglett
Alolan Grimer
Alolan Golem
Alolan Sandshrew
Alolan Sandslash
Alolan Marowak
Alolan Raichu
Alolan Muk
Galarian Linoone
Galarian Yamask
Galarian Slowpoke
Galarian Slowbro
Galarian Slowking
Galarian Farfetch'd
Galarian Rapidash
Galarian Ponyta
Galarian Mr. Mime
Galarian Weezing
Galarian Zigzagoon
Galarian Corsola
Galarian Meowth
Galarian Darumaka
Galarian Stunfisk
Galarian Darmanitan
Galarian Zen Darmanitan
Darmanitan Galar Zen
Partner Pikachu
Partner Eevee
Obstagoon
Sirfetch'd
Cursola
Runerigus
Mr. Rime
Perrserker
Hisuian Growlithe
Hisuian Arcanine
Hisuian Electrode
Hisuian Voltorb
Hisuian Typhlosion
Hisuian Lilligant
Hisuian Samurott
Hisuian Sneasel
Hisuian Decidueye
Hisuian Qwilfish
Hisuian Braviary
Hisuian Avalugg
Hisuian Zoroark
Hisuian Zorua
Hisuian Sliggoo
Hisuian Goodra
Basculegion
Sneasler
Overqwil
Paldean Wooper
Combat Breed Tauros
Tauros Combat Breed
Blaze Breed Tauros
Tauros Blaze Breed
Aqua Breed Tauros
Tauros Aqua Breed
Articuno
Zapdos
Moltres
Mewtwo
Mew
Raikou
Entei
Suicune
Lugia
Ho-oh
Celebi
Regirock
Regice
Registeel
Latias
Latios
Kyogre
Groudon
Rayquaza
Jirachi
Deoxys
Attack Deoxys
Defense Deoxys
Speed Deoxys
Uxie
Mesprit
Azelf
Dialga
Palkia
Heatran
Regigigas
Giratina
Cresselia
Phione
Manaphy
Darkrai
Shaymin
Victini
Cobalion
Terrakion
Virizion
Tornadus
Thundurus
Reshiram
Zekrom
Landorus
Kyurem
Keldeo
Meloetta
Pirouette Meloetta
Yveltal
Diancie
Hoopa
Volcanion
Type: Null
Type Null
Tapu Koko
Tapu Lele
Tapu Bulu
Tapu Fini
Cosmog
Cosmoem
Solgaleo
Lunala
Nihilego
Buzzwole
Pheromosa
Xurkitree
Celesteela
Kartana
Guzzlord
Necrozma
Magearna
Marshadow
Zenith Marshadow
Poipole
Naganadel
Stakataka
Blacephalon
Zeraora
Meltan
Kubfu
Zarude
Dada Zarude
Regieleki
Regidrago
Glastrier
Spectrier
Calyrex
Enamorus
Wo-Chien
Chien-Pao
Ting-Lu
Chi-Yu
Okidogi
Munkidori
Fezandipiti
Terapagos
Pecharunt
Zacian
Zamazenta
Eternatus
Melmetal
Galarian Articuno
Galarian Moltres
Galarian Zapdos
""".splitlines()
    if name.strip()
)
NORMAL_STARBOARD_ALL_FORMS: Final[tuple[str, ...]] = (
    "Arceus",
    "Genesect",
    "Xerneas",
    "Zygarde",
    "Silvally",
    "Ogerpon",
    "Urshifu",
    "Koraidon",
    "Miraidon",
)


def is_normal_starboard_pokemon(pokemon_name: str) -> bool:
    pokemon_name = re.sub(
        r"^(?:gigantamax|gmax)\s+",
        "",
        pokemon_name,
        flags=re.IGNORECASE,
    )
    normalized_name = normalize_pokemon_alias(pokemon_name).replace("’", "'")
    if normalized_name in NORMAL_STARBOARD_POKEMON_NAMES:
        return True
    return any(
        pokemon_matches_all_forms_reservation(pokemon_name, species_name)
        for species_name in NORMAL_STARBOARD_ALL_FORMS
    )


def catch_starboard_destinations(
    details: CatchDetails,
    settings: StarboardSettings,
) -> dict[int, str]:
    channel_ids: dict[str, int | None] = {}
    for key in ("normal_channel", "shiny_channel", "normal_pokemon_channel"):
        value = settings[key]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError(f"Invalid starboard channel ID in {key}")
        channel_ids[key] = value

    category = starboard_category(details)
    normal_pokemon_catch = is_normal_starboard_pokemon(details.pokemon)
    posts: dict[int, str] = {}
    normal_channel_id = channel_ids["normal_channel"]
    shiny_channel_id = channel_ids["shiny_channel"]
    normal_pokemon_channel_id = channel_ids["normal_pokemon_channel"]
    if category is not None and normal_channel_id is not None:
        posts[normal_channel_id] = category
    if details.shiny and shiny_channel_id is not None:
        posts.setdefault(shiny_channel_id, "shiny")
    if (
        normal_pokemon_catch
        and not details.shiny
        and normal_pokemon_channel_id is not None
    ):
        posts.setdefault(normal_pokemon_channel_id, "normal_pokemon")
    return posts


def starboard_sprite_names(details: CatchDetails) -> tuple[str, str]:
    base_name = re.sub(
        r"^(?:gigantamax|gmax)\s+",
        "",
        details.pokemon,
        flags=re.IGNORECASE,
    )
    base_name = CUSTOM_FORM_SPECIES.get(base_name, base_name)
    sprite_ids = load_sprite_ids()
    if base_name not in sprite_ids:
        slug = pokemon_sprite_slug(base_name)
        base_name = next(
            (name for name in sprite_ids if pokemon_sprite_slug(name) == slug),
            base_name,
        )
    if details.gigantamax and base_name.casefold().endswith(" alcremie"):
        base_name = "Alcremie"
    if base_name not in sprite_ids:
        base_name = next(
            (
                species_name
                for species_name in NORMAL_STARBOARD_ALL_FORMS
                if pokemon_matches_all_forms_reservation(base_name, species_name)
            ),
            base_name,
        )
    sprite_name = f"Gmax {base_name}" if details.gigantamax else base_name
    if sprite_name not in sprite_ids:
        sprite_name = base_name
    return base_name, sprite_name


def starboard_art_url(
    details: CatchDetails,
    *,
    use_3d_shiny_model: bool = False,
) -> str | None:
    base_name, sprite_name = starboard_sprite_names(details)
    sprite_ids = load_sprite_ids()
    sprite_id = sprite_ids.get(sprite_name)
    regional_form = re.match(
        r"^(?:Alolan|Galarian|Hisuian|Paldean)\s+(.+)$",
        base_name,
        flags=re.IGNORECASE,
    )
    species_name = regional_form.group(1) if regional_form else base_name
    base_sprite_id = sprite_ids.get(species_name)
    regional_form_prefix = (
        base_name.split(maxsplit=1)[0].casefold() if regional_form else None
    )

    if use_3d_shiny_model and details.shiny:
        animated_form_slugs = {
            "Pau Oricorio": "oricorio-pau",
            "Roaming Gimmighoul": "gimmighoul-roaming",
        }
        if base_name in animated_form_slugs:
            return SHOWDOWN_ANIMATED_SHINY_SPRITE_URL.format(
                animated_form_slugs[base_name]
            )
        form_model_slug = SWSH_FORM_MODEL_SLUGS.get(base_name)
        if form_model_slug is not None:
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{form_model_slug}.gif"
            )
        if (
            details.gigantamax
            and sprite_id is not None
            and base_sprite_id is not None
            and 810 <= base_sprite_id <= 905
        ):
            slug = pokemon_sprite_slug(base_name)
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{slug}-gigantamax.gif"
            )
        if (
            sprite_id is not None
            and 810 <= sprite_id <= 905
            and not regional_form
        ):
            slug = pokemon_sprite_slug(sprite_name)
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{slug}.gif"
            )
        if (
            base_sprite_id is not None
            and 810 <= base_sprite_id <= 905
            and regional_form_prefix == "galarian"
        ):
            slug = pokemon_sprite_slug(base_name)
            return (
                "https://projectpokemon.org/images/sprites-models/"
                f"swsh-shiny-sprites/{slug}.gif"
            )
        if (
            base_sprite_id is not None
            and base_sprite_id <= 809
            and regional_form_prefix not in {"hisuian", "paldean"}
        ):
            return PROJECT_POKEMON_SHINY_MODEL_URL.format(
                pokemon_sprite_slug(base_name)
            )
        return SHOWDOWN_ANIMATED_SHINY_SPRITE_URL.format(
            pokemon_sprite_slug(base_name)
        )
    return starboard_sprite_url_for_pokemon(sprite_name, shiny=details.shiny)


def format_starboard_embed(
    details: CatchDetails,
    category: str,
    caught_at: datetime,
    *,
    use_3d_shiny_model: bool = False,
    test_preview: bool = False,
) -> discord.Embed:
    titles = {
        "shiny": "✨ Shiny Capture ✨",
        "high_iv": "📈 High-IV Capture",
        "low_iv": "📉 Low-IV Capture",
        "missingno": "❔ MissingNo. Capture",
        "gigantamax": "Gigantamax Capture",
        "normal_pokemon": "⭐ Pokémon Spotlight",
    }
    caught_by = details.trainer or (
        f"<@{details.user_id}>" if details.user_id is not None else "Unknown"
    )
    description_lines = [
        f"**Caught by:** {caught_by}",
        f"**Pokémon:** {details.pokemon}",
    ]
    if category == "gigantamax":
        heading = f"{GIGANTAMAX_EMOJI} **Gigantamax Capture** {GIGANTAMAX_EMOJI}"
        if test_preview:
            heading = f"🧪 **TEST —** {heading}"
        description_lines.insert(0, f"{heading}\n")
    if category in {"high_iv", "low_iv"}:
        description_lines.extend(
            (f"**IV:** {details.iv}", f"**Level:** {details.level}")
        )
    else:
        description_lines.append(f"**Level:** {details.level}")
        if category != "gigantamax":
            description_lines.append(f"**IV:** {details.iv}")
    if category == "shiny":
        if details.gender:
            description_lines.append(f"**Gender:** {details.gender}")
        if details.chain is not None:
            description_lines.append(f"**Shiny chain:** {details.chain}")

    embed = discord.Embed(
        title=(
            None
            if category == "gigantamax"
            else f"🧪 TEST — {titles[category]}" if test_preview else titles[category]
        ),
        description="\n".join(description_lines),
        color=discord.Color(DEFAULT_EMBED_COLOR),
        timestamp=caught_at,
    )
    if category == "normal_pokemon":
        _, sprite_name = starboard_sprite_names(details)
        image_url = sprite_url_for_pokemon(sprite_name)
    else:
        image_url = starboard_art_url(
            details,
            use_3d_shiny_model=use_3d_shiny_model,
        )
    footer_text = (
        "Test preview — not an actual catch" if test_preview else "Caught at"
    )
    if test_preview and image_url and image_url.startswith(
        "https://projectpokemon.org/images/sprites-models/"
    ):
        footer_text += " · 3D animation by PKParaiso via Project Pokémon"
    elif test_preview and image_url and image_url.startswith(
        "https://projectpokemon.org/images/shiny-sprite/"
    ):
        footer_text += " · 3D animation via Project Pokémon"
    elif test_preview and image_url and image_url.startswith(
        "https://play.pokemonshowdown.com/sprites/ani-shiny/"
    ):
        footer_text += " · Animated sprite via Pokémon Showdown"
    embed.set_footer(text=footer_text)
    custom_thumbnail = custom_starboard_thumbnail_path(details, category)
    if custom_thumbnail:
        embed.set_thumbnail(url=f"attachment://{custom_thumbnail.name}")
    elif image_url:
        embed.set_thumbnail(url=image_url)
    return embed


def starboard_jump_view(jump_url: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Jump to message",
            emoji="🔗",
            style=discord.ButtonStyle.link,
            url=jump_url,
        )
    )
    return view


def reservation_key(guild_id: int, pokemon_name: str) -> str:
    normalized_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(pokemon_name)
    ).casefold()
    return f"{guild_id}:{normalized_name}"


def all_forms_reservation_key(guild_id: int, pokemon_name: str) -> str:
    normalized_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(pokemon_name)
    ).casefold()
    return f"{guild_id}:*:{normalized_name}"


def reservation_key_for_command(guild_id: int, pokemon_name: str) -> str:
    pokemon_name = canonicalize_pokemon_name(pokemon_name)
    all_forms_prefix = "all "
    if pokemon_name.casefold().startswith(all_forms_prefix):
        base_name = pokemon_name[len(all_forms_prefix) :].strip()
        return all_forms_reservation_key(guild_id, base_name)
    return reservation_key(guild_id, pokemon_name)


def reserve_category_storage_key(category_name: str) -> str:
    return unicodedata.normalize("NFC", category_name.strip()).casefold()


def add_reserve_category(
    categories: dict[str, dict[str, list[str]]],
    guild_id: int,
    category_name: str,
) -> tuple[dict[str, dict[str, list[str]]], bool]:
    updated = {
        server_id: {
            name: list(pokemon_names)
            for name, pokemon_names in server_categories.items()
        }
        for server_id, server_categories in categories.items()
    }
    server_categories = updated.setdefault(str(guild_id), {})
    category_key = reserve_category_storage_key(category_name)
    if category_key in server_categories:
        return updated, False
    server_categories[category_key] = []
    return updated, True


def append_reserve_category_pokemon(
    categories: dict[str, dict[str, list[str]]],
    guild_id: int,
    category_name: str,
    pokemon_names: list[str],
) -> tuple[dict[str, dict[str, list[str]]], list[str], bool]:
    updated = {
        server_id: {
            name: list(existing_names)
            for name, existing_names in server_categories.items()
        }
        for server_id, server_categories in categories.items()
    }
    server_categories = updated.get(str(guild_id), {})
    category_key = reserve_category_storage_key(category_name)
    existing_names = server_categories.get(category_key)
    if existing_names is None:
        return updated, [], False

    existing_keys = {
        unicodedata.normalize("NFC", canonicalize_pokemon_name(name)).casefold()
        for name in existing_names
    }
    added_names: list[str] = []
    for name in pokemon_names:
        canonical_name = canonicalize_pokemon_name(name)
        name_key = unicodedata.normalize("NFC", canonical_name).casefold()
        if name_key in existing_keys:
            continue
        existing_names.append(canonical_name)
        existing_keys.add(name_key)
        added_names.append(canonical_name)
    return updated, added_names, True


def delete_reserve_category(
    categories: dict[str, dict[str, list[str]]],
    guild_id: int,
    category_name: str,
) -> tuple[dict[str, dict[str, list[str]]], bool]:
    updated = {
        server_id: {
            name: list(pokemon_names)
            for name, pokemon_names in server_categories.items()
        }
        for server_id, server_categories in categories.items()
    }
    server_categories = updated.get(str(guild_id))
    category_key = reserve_category_storage_key(category_name)
    if server_categories is None or category_key not in server_categories:
        return updated, False
    del server_categories[category_key]
    if not server_categories:
        del updated[str(guild_id)]
    return updated, True


def expand_reserve_category_names(
    categories: dict[str, dict[str, list[str]]],
    guild_id: int,
    pokemon_names: list[str],
) -> tuple[list[str], list[str]]:
    server_categories = categories.get(str(guild_id), {})
    expanded_names: list[str] = []
    expanded_keys: set[str] = set()
    used_categories: list[str] = []
    for name in pokemon_names:
        category_key = reserve_category_storage_key(name)
        category_pokemon = server_categories.get(category_key)
        names_to_add = category_pokemon if category_pokemon is not None else [name]
        if category_pokemon is not None:
            used_categories.append(category_key)
        for pokemon_name in names_to_add:
            canonical_name = canonicalize_pokemon_name(pokemon_name)
            key = reservation_key_for_command(guild_id, canonical_name)
            if key in expanded_keys:
                continue
            expanded_keys.add(key)
            expanded_names.append(canonical_name)
    return expanded_names, used_categories


def format_reserve_category_embeds(
    categories: dict[str, dict[str, list[str]]],
    guild_id: int,
) -> list[discord.Embed]:
    category_entries = sorted(categories.get(str(guild_id), {}).items())
    if not category_entries:
        return [
            discord.Embed(
                title="Reserve Categories",
                description="No categories have been created.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        category_entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(category_entries), RESERVATION_EMBED_PAGE_SIZE)
    ]
    embeds: list[discord.Embed] = []
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title="Reserve Categories",
            description="\n\n".join(
                f"{category_name}\n{len(pokemon_names)} Pokémon"
                for category_name, pokemon_names in page_entries
            ),
            color=discord.Color.blurple(),
        )
        if len(pages) > 1:
            embed.set_footer(text=f"Page {page_number} of {len(pages)}")
        embeds.append(embed)
    return embeds


def pokemon_matches_all_forms_reservation(
    pokemon_name: str,
    reserved_name: str,
) -> bool:
    pokemon_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(pokemon_name)
    ).casefold()
    reserved_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(reserved_name)
    ).casefold()
    if pokemon_name == reserved_name:
        return True
    for form_index, form in enumerate(POKEMON_FORMS.get(reserved_name, [])):
        aliases = pokemon_form_reservation_aliases(
            reserved_name,
            form,
            is_default=form_index == 0,
        )
        if pokemon_name in {
            unicodedata.normalize("NFC", alias).casefold()
            for alias in aliases
        }:
            return True
    if pokemon_name.startswith(
        tuple(f"{reserved_name}{separator}" for separator in (" ", "-", "(", ":", "["))
    ):
        return True
    # Forms named with a prefix, such as "Mega Marshadow" or "Zenith Marshadow".
    return " " not in reserved_name and reserved_name in re.split(
        r"[\s()\-:\[\]]+", pokemon_name
    )


def reserved_user_ids_for_pokemon(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    *,
    additional_names: tuple[str, ...] = (),
) -> list[int]:
    user_ids: set[int] = set()
    wildcard_prefix = f"{guild_id}:*:"
    for candidate in dict.fromkeys((pokemon_name, *additional_names)):
        user_ids.update(reservations.get(reservation_key(guild_id, candidate), []))
        for key, reserved_user_ids in reservations.items():
            if not key.startswith(wildcard_prefix):
                continue
            reserved_name = key.removeprefix(wildcard_prefix)
            if pokemon_matches_all_forms_reservation(candidate, reserved_name):
                user_ids.update(reserved_user_ids)
    return sorted(user_ids)


@lru_cache(maxsize=1)
def load_report_spawn_chances() -> list[tuple[str, int]]:
    path = Path(__file__).with_name("data") / "poketwo_spawn_chances.csv"
    with path.open(encoding="utf-8") as file:
        return [
            (row["Pokemon"], int(row["Chance"].split("/", 1)[1]))
            for row in csv.DictReader(file)
        ]


def report_category_price(
    categories: dict[str, dict[str, list[str]]],
    guild_id: int,
    pokemon_name: str,
    *,
    gigantamax: bool = False,
) -> int | None:
    if pokemon_name.casefold() in RESERVE_REPORT_EVENT_FORMS:
        return 45000
    prices = {"gmax": 35000, "eevos": 35000, "paradox": 35000,
              "rare": 45000, "regional": 45000, "event": 45000, "events": 45000}
    matching_prices = [35000] if gigantamax else []
    for category, names in categories.get(str(guild_id), {}).items():
        price = prices.get(reserve_category_storage_key(category))
        if price is None:
            continue
        for name in names:
            if name.casefold().startswith("all "):
                matches = pokemon_matches_all_forms_reservation(pokemon_name, name[4:].strip())
            else:
                matches = reservation_key(guild_id, pokemon_name) == reservation_key(guild_id, name)
            if matches:
                matching_prices.append(price)
                break
    return max(matching_prices, default=None)


def report_spawn_price(pokemon_name: str) -> int | None:
    name_key = reservation_key(0, pokemon_name)
    chance_denominator = next(
        (
            denominator
            for name, denominator in load_report_spawn_chances()
            if reservation_key(0, name) == name_key
        ),
        None,
    )
    if chance_denominator is None:
        return None
    price = RESERVE_REPORT_PRICES[0][1]
    for denominator, amount in RESERVE_REPORT_PRICES:
        if chance_denominator >= denominator:
            price = amount
    return price


def report_spawn_form(content: str, species: str) -> str | None:
    line = unicodedata.normalize("NFC", content.split("\n", 1)[0])
    line = re.sub(r"<a?:[A-Za-z0-9_~]+:\d+>", " ", line)
    line = "".join(
        char for char in line
        if (unicodedata.category(char) != "So" or char in "♀♂")
        and char not in "*`_\ufe0f"
    ).strip()
    candidates = [species, *custom_forms_for_species(species)]
    for name in sorted(candidates, key=len, reverse=True):
        if re.fullmatch(
            rf"(?:pok[eé]mon\s*:\s*)?{re.escape(name)}\s*"
            r"(?::\s*\d+(?:\.\d+)?\s*%)?\s*",
            line,
            re.IGNORECASE,
        ):
            return name
    return None


def report_reserve_pings(content: str) -> set[int]:
    user_ids: set[int] = set()
    for line in content.splitlines():
        line = line.replace("**", "").replace("__", "")
        match = re.match(
            r"^\s*(?:reserve\s+pings?|reserved(?:\s+(?:by|pings?))?|reserves?)\s*:\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if match:
            user_ids.update(int(user_id) for user_id in re.findall(r"<@!?(\d+)>", match.group(1)))
    return user_ids


def parse_shinyhunt_command(content: str) -> str | None:
    match = SHINYHUNT_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None
    return parse_shinyhunt_name(match.group(1))


def parse_shinyhunt_remove_command(content: str) -> str | None:
    match = SHINYHUNT_REMOVE_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None
    return parse_shinyhunt_name(match.group(1))


def parse_shinyhunt_name(value: str) -> str | None:
    pokemon_name = unicodedata.normalize("NFC", value.strip())
    if (
        not pokemon_name
        or "," in pokemon_name
        or len(pokemon_name) > 60
        or not is_valid_pokemon_name(pokemon_name)
    ):
        return None
    return pokemon_name


def add_shinyhunter(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int,
) -> dict[str, list[int]]:
    updated_shinyhunters = {
        key: list(user_ids) for key, user_ids in shinyhunters.items()
    }
    guild_prefix = f"{guild_id}:"
    for key in list(updated_shinyhunters):
        if not key.startswith(guild_prefix):
            continue
        user_ids = updated_shinyhunters[key]
        if user_id in user_ids:
            user_ids.remove(user_id)
            if not user_ids:
                del updated_shinyhunters[key]
    user_ids = updated_shinyhunters.setdefault(
        reservation_key_for_command(guild_id, pokemon_name),
        [],
    )
    if user_id not in user_ids:
        user_ids.append(user_id)
    return updated_shinyhunters


def remove_shinyhunter(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int,
) -> tuple[dict[str, list[int]], bool]:
    updated_shinyhunters = {
        key: list(user_ids) for key, user_ids in shinyhunters.items()
    }
    key = reservation_key_for_command(guild_id, pokemon_name)
    user_ids = updated_shinyhunters.get(key)
    if user_ids is None or user_id not in user_ids:
        return updated_shinyhunters, False

    user_ids.remove(user_id)
    if not user_ids:
        del updated_shinyhunters[key]
    return updated_shinyhunters, True


def clear_shinyhunter(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> tuple[dict[str, list[int]], bool]:
    updated_shinyhunters = {
        key: list(user_ids) for key, user_ids in shinyhunters.items()
    }
    guild_prefix = f"{guild_id}:"
    cleared = False
    for key in list(updated_shinyhunters):
        if not key.startswith(guild_prefix):
            continue
        user_ids = updated_shinyhunters[key]
        if user_id not in user_ids:
            continue
        user_ids.remove(user_id)
        cleared = True
        if not user_ids:
            del updated_shinyhunters[key]
    return updated_shinyhunters, cleared


def clear_guild_shinyhunts(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(user_ids)
        for key, user_ids in shinyhunters.items()
        if not key.startswith(guild_prefix)
    }


def format_shinyhunt_status(pokemon_name: str) -> str:
    return f"You are currently shinyhunting {format_shinyhunt_name(pokemon_name)}"


def format_shinyhunt_confirmation(pokemon_name: str) -> str:
    return f"You are now shinyhunting {format_shinyhunt_name(pokemon_name)}"


def format_shinyhunt_name(pokemon_name: str) -> str:
    normalized_name = pokemon_name.casefold()
    if normalized_name.startswith("all "):
        return f"all forms of {normalized_name[4:].strip()}"
    if normalized_name.startswith("*:"):
        return f"all forms of {normalized_name[2:]}"
    return normalized_name


def shinyhunt_pokemon_for_user(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    pokemon_names = []
    for key, user_ids in shinyhunters.items():
        if not key.startswith(guild_prefix) or user_id not in user_ids:
            continue
        name = key.removeprefix(guild_prefix)
        pokemon_names.append(f"all {name[2:]}" if name.startswith("*:") else name)
    return sorted(pokemon_names)


def shinyhunter_user_ids_for_pokemon(
    shinyhunters: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    *,
    additional_names: tuple[str, ...] = (),
) -> list[int]:
    return reserved_user_ids_for_pokemon(
        shinyhunters,
        guild_id,
        pokemon_name,
        additional_names=additional_names,
    )


def parse_collection_add_command(content: str) -> list[str] | None:
    return parse_collection_pokemon_command(content, COLLECTION_ADD_PATTERN)


def parse_collection_pokemon_command(
    content: str,
    pattern: re.Pattern[str],
) -> list[str] | None:
    match = pattern.fullmatch(content)
    if match is None:
        return None

    pokemon_names = [
        unicodedata.normalize("NFC", name.strip())
        for name in match.group(1).split(",")
    ]
    if any(
        not name or len(name) > 60 or not is_valid_pokemon_name(name)
        for name in pokemon_names
    ):
        return None

    unique_names: list[str] = []
    seen_names: set[str] = set()
    for pokemon_name in pokemon_names:
        normalized_name = pokemon_name.casefold()
        if normalized_name not in seen_names:
            unique_names.append(pokemon_name)
            seen_names.add(normalized_name)
    return unique_names


def add_collection_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> dict[str, list[int]]:
    updated_collections = {
        key: list(user_ids) for key, user_ids in collections.items()
    }
    for pokemon_name in pokemon_names:
        user_ids = updated_collections.setdefault(
            reservation_key_for_command(guild_id, pokemon_name),
            [],
        )
        if user_id not in user_ids:
            user_ids.append(user_id)
    return updated_collections


def migrate_legacy_all_keys(
    collections: dict[str, list[int]],
) -> dict[str, list[int]]:
    """Convert old literal "all <pokemon>" collection keys to all-forms keys."""
    migrated: dict[str, list[int]] = {}
    for key, user_ids in collections.items():
        guild_id, separator, name = key.partition(":")
        if separator and name.casefold().startswith("all "):
            key = f"{guild_id}:*:{name[4:].strip().casefold()}"
        merged = migrated.setdefault(key, [])
        merged.extend(user_id for user_id in user_ids if user_id not in merged)
    return migrated


def collection_pokemon_for_user(
    collections: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    return sorted(
        {
            name
            for key, user_ids in collections.items()
            if key.startswith(guild_prefix) and user_id in user_ids
            for name in format_reserved_pokemon_names(key.removeprefix(guild_prefix))
        }
    )


def split_collection_add_names(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> tuple[list[str], list[str]]:
    def is_added(name: str) -> bool:
        return user_id in collections.get(
            reservation_key_for_command(guild_id, name), []
        )

    already_added = [name for name in pokemon_names if is_added(name)]
    new_names = [name for name in pokemon_names if not is_added(name)]
    return new_names, already_added


def format_collection_add_confirmation(
    added_names: list[str],
    already_added_names: list[str],
) -> str:
    def display(name: str) -> str:
        if name.casefold().startswith("all "):
            return f"All forms of {name[4:].strip()}"
        return name[0].upper() + name[1:]

    lines = []
    if added_names:
        display_names = ", ".join(display(name) for name in added_names)
        lines.append(f"Added {display_names} to your collection.")
    if already_added_names:
        display_names = ", ".join(display(name) for name in already_added_names)
        lines.append(f"{display_names} already added to your collection.")
    return " ".join(lines)


def collection_user_ids_for_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    *,
    additional_names: tuple[str, ...] = (),
) -> list[int]:
    return reserved_user_ids_for_pokemon(
        collections,
        guild_id,
        pokemon_name,
        additional_names=additional_names,
    )


def remove_collection_pokemon(
    collections: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int,
) -> tuple[dict[str, list[int]], list[str], list[str]]:
    updated_collections = {
        key: list(user_ids) for key, user_ids in collections.items()
    }
    removed_names: list[str] = []
    missing_names: list[str] = []
    for pokemon_name in pokemon_names:
        key = reservation_key_for_command(guild_id, pokemon_name)
        user_ids = updated_collections.get(key)
        if user_ids is None or user_id not in user_ids:
            missing_names.append(pokemon_name)
            continue
        user_ids.remove(user_id)
        removed_names.append(pokemon_name)
        if not user_ids:
            del updated_collections[key]
    return updated_collections, removed_names, missing_names


def clear_user_collection(
    collections: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    updated_collections: dict[str, list[int]] = {}
    for key, user_ids in collections.items():
        remaining_user_ids = list(user_ids)
        if key.startswith(guild_prefix) and user_id in remaining_user_ids:
            remaining_user_ids.remove(user_id)
        if remaining_user_ids:
            updated_collections[key] = remaining_user_ids
    return updated_collections


def clear_guild_collection(
    collections: dict[str, list[int]],
    guild_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(user_ids)
        for key, user_ids in collections.items()
        if not key.startswith(guild_prefix)
    }


def parse_reserve_add_command(content: str) -> tuple[list[str], int] | None:
    match = RESERVE_COMMAND_PATTERN.fullmatch(content)
    if match is None:
        return None

    pokemon_names = [
        unicodedata.normalize("NFC", name.strip())
        for name in match.group(1).split(",")
    ]
    if (
        not pokemon_names
        or any(
            not name or len(name) > 60 or not is_valid_pokemon_name(name)
            for name in pokemon_names
        )
    ):
        return None
    unique_names: list[str] = []
    seen_names: set[str] = set()
    for name in pokemon_names:
        normalized_name = name.casefold()
        if normalized_name not in seen_names:
            unique_names.append(name)
            seen_names.add(normalized_name)
    return unique_names, int(match.group(2))


def parse_add_reserve_category_command(content: str) -> str | None:
    match = ADD_RESERVE_CATEGORY_PATTERN.fullmatch(content)
    if match is None:
        return None
    return match.group(1)


def parse_create_reserve_category_command(
    content: str,
) -> tuple[str, list[str]] | None:
    match = CREATE_RESERVE_CATEGORY_PATTERN.fullmatch(content)
    if match is None:
        return None
    pokemon_names = [
        canonicalize_pokemon_name(name.strip())
        for name in match.group(2).split(",")
    ]
    if any(
        not name or len(name) > 60 or not is_valid_pokemon_name(name)
        for name in pokemon_names
    ):
        return None
    unique_names: list[str] = []
    seen_names: set[str] = set()
    for pokemon_name in pokemon_names:
        normalized_name = unicodedata.normalize("NFC", pokemon_name).casefold()
        if normalized_name not in seen_names:
            unique_names.append(pokemon_name)
            seen_names.add(normalized_name)
    return match.group(1), unique_names


def parse_delete_reserve_category_command(content: str) -> str | None:
    match = DELETE_RESERVE_CATEGORY_PATTERN.fullmatch(content)
    if match is None:
        return None
    return match.group(1)


def parse_reserve_remove_command(
    content: str,
) -> tuple[list[str], int | None] | None:
    match = RESERVE_REMOVE_PATTERN.fullmatch(content)
    if match is None:
        return None

    pokemon_names = [
        unicodedata.normalize("NFC", name.strip())
        for name in match.group(1).split(",")
    ]
    if any(
        not name or len(name) > 60 or not is_valid_pokemon_name(name)
        for name in pokemon_names
    ):
        return None

    unique_names: list[str] = []
    seen_names: set[str] = set()
    for name in pokemon_names:
        normalized_name = name.casefold()
        if normalized_name not in seen_names:
            unique_names.append(name)
            seen_names.add(normalized_name)
    target_id = int(match.group(2)) if match.group(2) else None
    return unique_names, target_id


def reserved_pokemon_for_user(
    reservations: dict[str, list[int]],
    guild_id: int,
    user_id: int,
) -> list[str]:
    guild_prefix = f"{guild_id}:"
    names = []
    for key, user_ids in reservations.items():
        if not key.startswith(guild_prefix) or user_id not in user_ids:
            continue
        name = key.removeprefix(guild_prefix)
        names.extend(format_reserved_pokemon_names(name))
    return sorted(set(names))


def remove_reservation(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
    user_id: int | None = None,
) -> tuple[dict[str, list[int]], bool]:
    updated_reservations = {
        key: list(user_ids) for key, user_ids in reservations.items()
    }
    all_forms_prefix = "all "
    if pokemon_name.casefold().startswith(all_forms_prefix):
        base_name = pokemon_name[len(all_forms_prefix) :].strip()
        guild_prefix = f"{guild_id}:"
        removed = False
        for key, reserved_user_ids in list(updated_reservations.items()):
            if not key.startswith(guild_prefix):
                continue
            reserved_name = key.removeprefix(guild_prefix)
            if reserved_name.startswith("*:"):
                reserved_name = reserved_name.removeprefix("*:")
            if not pokemon_matches_all_forms_reservation(
                reserved_name, base_name
            ):
                continue
            if user_id is None:
                del updated_reservations[key]
                removed = True
            elif user_id in reserved_user_ids:
                reserved_user_ids.remove(user_id)
                if not reserved_user_ids:
                    del updated_reservations[key]
                removed = True
        return updated_reservations, removed

    key = reservation_key_for_command(guild_id, pokemon_name)
    reserved_user_ids = updated_reservations.get(key)
    if reserved_user_ids is None:
        return updated_reservations, False

    if user_id is None:
        del updated_reservations[key]
        return updated_reservations, True

    if user_id not in reserved_user_ids:
        return updated_reservations, False

    reserved_user_ids.remove(user_id)
    if not reserved_user_ids:
        del updated_reservations[key]
    return updated_reservations, True


def remove_reservations(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_names: list[str],
    user_id: int | None = None,
) -> tuple[dict[str, list[int]], list[str], list[str]]:
    updated_reservations = {
        key: list(user_ids) for key, user_ids in reservations.items()
    }
    removed_names: list[str] = []
    missing_names: list[str] = []
    for pokemon_name in pokemon_names:
        updated_reservations, removed = remove_reservation(
            updated_reservations,
            guild_id,
            pokemon_name,
            user_id,
        )
        (removed_names if removed else missing_names).append(pokemon_name)
    return updated_reservations, removed_names, missing_names


EXCHANGE_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!r\s+(?:e|exchange)\s+<@!?(\d+)>\s*$",
    re.IGNORECASE,
)
EXCHANGE_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"<@!?(\d+)>\s*[-–—:]?\s*(.+)"
)


def message_list_texts(message: discord.Message) -> list[str]:
    """Text of a message and of any message it forwards."""
    sources: list[Any] = [message, *getattr(message, "message_snapshots", [])]
    texts: list[str] = []
    for source in sources:
        if source.content:
            texts.append(source.content)
        texts.extend(
            embed.description for embed in source.embeds if embed.description
        )
    return texts


def parse_exchange_list(text: str) -> list[tuple[int, list[str]]]:
    transfers: list[tuple[int, list[str]]] = []
    for line in text.splitlines():
        match = EXCHANGE_LINE_PATTERN.search(line)
        if match is None:
            continue
        names: list[str] = []
        for raw_name in match.group(2).split(","):
            name = unicodedata.normalize("NFC", raw_name.strip())
            if (
                name
                and len(name) <= 60
                and is_valid_pokemon_name(name)
                and name.casefold() not in {n.casefold() for n in names}
            ):
                names.append(name)
        if names:
            transfers.append((int(match.group(1)), names))
    return transfers


REGIONAL_MARKER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:alola|alolan|galar|galarian|hisui|hisuian|paldea|paldean)\b",
    re.IGNORECASE,
)


def pokemon_matches_exchange_all_forms(pokemon_name: str, base_name: str) -> bool:
    # Exchanges treat "all <pokemon>" as every form, regional forms included.
    if pokemon_matches_all_forms_reservation(pokemon_name, base_name):
        return True
    stripped_name = " ".join(REGIONAL_MARKER_PATTERN.sub(" ", pokemon_name).split())
    return bool(stripped_name) and pokemon_matches_all_forms_reservation(
        stripped_name, base_name
    )


def exchange_reservations(
    reservations: dict[str, list[int]],
    guild_id: int,
    source_id: int,
    transfers: list[tuple[int, list[str]]],
) -> tuple[dict[str, list[int]], list[tuple[int, str]], list[tuple[int, str]]]:
    updated = {key: list(user_ids) for key, user_ids in reservations.items()}
    moved: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    for recipient_id, names in transfers:
        for name in names:
            keys = [reservation_key_for_command(guild_id, name)]
            if name.casefold().startswith("all "):
                base_name = name[4:].strip()
                prefix = f"{guild_id}:"
                keys.extend(
                    key
                    for key in updated
                    if key.startswith(prefix)
                    and not key.startswith(f"{prefix}*:")
                    and key not in keys
                    and pokemon_matches_exchange_all_forms(
                        key.removeprefix(prefix), base_name
                    )
                )
            held_keys = [
                key for key in keys if source_id in updated.get(key, [])
            ]
            if recipient_id == source_id or not held_keys:
                skipped.append((recipient_id, name))
                continue
            for key in held_keys:
                user_ids = updated[key]
                user_ids.remove(source_id)
                if recipient_id not in user_ids:
                    user_ids.append(recipient_id)
            moved.append((recipient_id, name))
    return updated, moved, skipped


def format_exchange_embed(
    reservations: dict[str, list[int]],
    guild_id: int,
    source_id: int,
    transfers: list[tuple[int, list[str]]],
    skipped: list[tuple[int, str]],
) -> discord.Embed:
    lines = [
        f"You want to exchange from <@{source_id}> to those users:",
        "",
        *(
            f"<@{recipient_id}> - "
            + ", ".join(
                form_name
                for name in names
                for form_name in (
                    all_forms_display_names(name[4:].strip())
                    if name.casefold().startswith("all ")
                    else []
                )
                or [name]
            )
            for recipient_id, names in transfers
        ),
    ]
    if skipped:
        missing = list(dict.fromkeys(name for _, name in skipped))
        holders: list[int] = []
        for name in missing:
            key = reservation_key_for_command(guild_id, name)
            for user_id in reservations.get(key, []):
                if user_id != source_id and user_id not in holders:
                    holders.append(user_id)
        lines.append("")
        lines.append(
            f"-# <@{source_id}> doesn't have reserved: {', '.join(missing)}"
        )
        if holders:
            lines.append(
                "-# Do you mean " + ", ".join(f"<@{user_id}>" for user_id in holders) + "?"
            )
    return discord.Embed(
        title="Exchange reserves",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )


def format_remove_confirmation(pokemon_name: str, member_mention: str | None) -> str:
    display_names = ", ".join(
        (
            f"All forms of {name[len('all '):]}"
            if name.casefold().startswith("all ")
            else name[0].upper() + name[1:]
        )
        for name in pokemon_name.split(", ")
    )
    if member_mention is None:
        return f"{display_names} removed"
    return f"{display_names} removed from {member_mention} Reserves"


def format_reservation_embeds(
    display_name: str,
    pokemon_names: list[str],
) -> list[discord.Embed]:
    heading = f"Pokémon reserved by {display_name}"
    if not pokemon_names:
        return [
            discord.Embed(
                title=heading,
                description="This member has no Pokémon reservations.",
                color=discord.Color.blurple(),
            )
        ]

    display_names = [name[0].upper() + name[1:] for name in pokemon_names]
    pages = [
        display_names[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(display_names), RESERVATION_EMBED_PAGE_SIZE)
    ]

    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_names in enumerate(pages, start=1):
        embed = discord.Embed(
            title=heading,
            description="\n".join(page_names),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def format_collection_embeds(pokemon_names: list[str]) -> list[discord.Embed]:
    title = "Your Pokémon Collection"
    if not pokemon_names:
        return [
            discord.Embed(
                title=title,
                description="You have no Pokémon in your collection yet.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        pokemon_names[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(pokemon_names), RESERVATION_EMBED_PAGE_SIZE)
    ]
    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_names in enumerate(pages, start=1):
        embed = discord.Embed(
            title=title,
            description="\n".join(page_names),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def format_server_reservation_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
) -> list[discord.Embed]:
    guild_prefix = f"{guild_id}:"
    entries = sorted(
        (
            f"{pokemon_name} <@{user_id}>"
            for key, user_ids in reservations.items()
            if key.startswith(guild_prefix)
            for pokemon_name in format_reserved_pokemon_names(
                key.removeprefix(guild_prefix)
            )
            for user_id in set(user_ids)
        ),
        key=str.casefold,
    )
    if not entries:
        return [
            discord.Embed(
                title="Server Pokémon Reserves",
                description="There are no Pokémon reservations in this server.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(entries), RESERVATION_EMBED_PAGE_SIZE)
    ]

    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title="Server Pokémon Reserves",
            description="\n".join(page_entries),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def custom_forms_for_species(species_name: str) -> list[str]:
    species_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(species_name)
    ).casefold()
    return [
        custom_name
        for custom_name, custom_species in CUSTOM_FORM_SPECIES.items()
        if custom_species.casefold() == species_name
    ]


def all_forms_display_names(species_name: str) -> list[str]:
    species_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(species_name)
    ).casefold()
    forms = POKEMON_FORMS.get(species_name, [])
    display_names = [form["display_name"] for form in forms]
    names: list[str] = []
    for form, display_name in zip(forms, display_names):
        name = display_name
        if display_names.count(display_name) > 1:
            suffix = form["identifier"].removeprefix(f"{species_name}-")
            name = f"{suffix.replace('-', ' ')} {species_name}"
        if name not in names:
            names.append(name)
    custom_forms = [name.casefold() for name in custom_forms_for_species(species_name)]
    if custom_forms:
        if not names:
            names.append(species_name)
        names.extend(
            custom_name
            for custom_name in custom_forms
            if custom_name not in {name.casefold() for name in names}
        )
    return names


def format_reserved_pokemon_names(stored_name: str) -> list[str]:
    stored_name = canonicalize_pokemon_name(stored_name)
    if stored_name.casefold().startswith("all "):
        stored_name = "*:" + stored_name[4:].strip()
    if stored_name.startswith("*:"):
        species_name = stored_name.removeprefix("*:")
        return all_forms_display_names(species_name) or [
            f"all forms of {species_name}"
        ]
    return [stored_name]


def format_reserved_pokemon_name(stored_name: str) -> str:
    return ", ".join(format_reserved_pokemon_names(stored_name))


def format_pokemon_reserver_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[discord.Embed]:
    user_ids = reserved_user_ids_for_pokemon(
        reservations,
        guild_id,
        pokemon_name,
    )
    if not user_ids:
        return [
            discord.Embed(
                title=f"Reserve search: {pokemon_name}",
                description=f"No one has {pokemon_name} reserved.",
                color=discord.Color.blurple(),
            )
        ]

    entries = [f"{pokemon_name} <@{user_id}>" for user_id in user_ids]
    pages = [
        entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(entries), RESERVATION_EMBED_PAGE_SIZE)
    ]

    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title=f"Reserve search: {pokemon_name}",
            description="\n".join(page_entries),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def format_all_forms_reservation_embeds(
    reservations: dict[str, list[int]],
    guild_id: int,
    pokemon_name: str,
) -> list[discord.Embed]:
    base_name = unicodedata.normalize(
        "NFC", canonicalize_pokemon_name(pokemon_name)
    ).casefold()
    guild_prefix = f"{guild_id}:"
    wildcard_key = all_forms_reservation_key(guild_id, base_name)
    wildcard_user_ids = set(reservations.get(wildcard_key, []))
    form_definitions = POKEMON_FORMS.get(base_name, [])
    known_alias_keys: set[str] = set()
    entries: list[str] = []
    for form_index, form in enumerate(form_definitions):
        aliases = pokemon_form_reservation_aliases(
            base_name,
            form,
            is_default=form_index == 0,
        )
        alias_keys = {
            reservation_key(guild_id, alias)
            for alias in aliases
        }
        known_alias_keys.update(alias_keys)
        form_user_ids = set(wildcard_user_ids)
        for alias_key in alias_keys:
            form_user_ids.update(reservations.get(alias_key, []))
        if form_user_ids:
            entries.extend(
                f"{form['display_name']} <@{user_id}>"
                for user_id in sorted(form_user_ids)
            )
        else:
            entries.append(form["display_name"])

    custom_forms = custom_forms_for_species(base_name)
    if not form_definitions and custom_forms:
        base_key = reservation_key(guild_id, base_name)
        known_alias_keys.add(base_key)
        base_user_ids = wildcard_user_ids | set(reservations.get(base_key, []))
        if base_user_ids:
            entries.extend(
                f"{base_name} <@{user_id}>"
                for user_id in sorted(base_user_ids)
            )
        else:
            entries.append(base_name)
    for custom_name in custom_forms:
        custom_key = reservation_key(guild_id, custom_name)
        if custom_key in known_alias_keys:
            continue
        known_alias_keys.add(custom_key)
        form_user_ids = wildcard_user_ids | set(reservations.get(custom_key, []))
        if form_user_ids:
            entries.extend(
                f"{custom_name.casefold()} <@{user_id}>"
                for user_id in sorted(form_user_ids)
            )
        else:
            entries.append(custom_name.casefold())

    for key, user_ids in reservations.items():
        if (
            not key.startswith(guild_prefix)
            or key.startswith(f"{guild_id}:*:")
            or key in known_alias_keys
        ):
            continue
        reserved_name = key.removeprefix(guild_prefix)
        if pokemon_matches_all_forms_reservation(reserved_name, base_name):
            entries.extend(
                f"{reserved_name} <@{user_id}>"
                for user_id in sorted(set(user_ids) | wildcard_user_ids)
            )

    if not form_definitions and not entries and wildcard_user_ids:
        entries = [
            f"{format_reserved_pokemon_name(f'*:{base_name}')} <@{user_id}>"
            for user_id in sorted(wildcard_user_ids)
        ]
    elif not entries:
        return [
            discord.Embed(
                title=f"Reserve search: all forms of {pokemon_name}",
                description=f"No forms of {pokemon_name} are reserved.",
                color=discord.Color.blurple(),
            )
        ]

    pages = [
        entries[index : index + RESERVATION_EMBED_PAGE_SIZE]
        for index in range(0, len(entries), RESERVATION_EMBED_PAGE_SIZE)
    ]
    embeds: list[discord.Embed] = []
    total_pages = len(pages)
    for page_number, page_entries in enumerate(pages, start=1):
        embed = discord.Embed(
            title=f"Reserve search: all forms of {pokemon_name}",
            description="\n".join(page_entries),
            color=discord.Color.blurple(),
        )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number} of {total_pages}")
        embeds.append(embed)
    return embeds


def pokemon_form_reservation_aliases(
    species_name: str,
    form: dict[str, str],
    *,
    is_default: bool,
) -> set[str]:
    identifier = form["identifier"]
    display_name = form["display_name"]
    aliases = {identifier, identifier.replace("-", " "), display_name}
    if identifier.startswith(f"{species_name}-"):
        suffix = identifier.removeprefix(f"{species_name}-")
        aliases.update(
            {
                f"{species_name} {suffix}",
                f"{species_name} ({suffix})",
                f"{suffix} {species_name}",
            }
        )
    if is_default:
        aliases.add(species_name)
    return aliases


class ReservationPagesView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], guild_id: int) -> None:
        super().__init__(timeout=300)
        self.embeds = embeds
        self.guild_id = guild_id
        self.current_page = 0
        self.message: discord.Message | None = None
        self.update_buttons()

    def update_buttons(self) -> None:
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if child.custom_id == "reserve_pages:previous":
                child.disabled = self.current_page == 0
            elif child.custom_id == "reserve_pages:next":
                child.disabled = self.current_page == len(self.embeds) - 1

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.warning("Could not disable expired reserve-page buttons")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These reserve pages can only be used in their original server.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
        custom_id="reserve_pages:previous",
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page],
            view=self,
        )

    @discord.ui.button(
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
        custom_id="reserve_pages:next",
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.embeds[self.current_page],
            view=self,
        )


class TypePingSelect(discord.ui.Select):
    def __init__(self, type_ping_view: "TypePingView") -> None:
        self.type_ping_view = type_ping_view
        enabled_types = type_ping_view.bot.type_pings_for_user(
            type_ping_view.guild_id,
            type_ping_view.user_id,
        )
        super().__init__(
            placeholder="Select type(s) to receive pings...",
            options=[
                discord.SelectOption(
                    label=type_name.title(),
                    value=type_name,
                    emoji=TYPE_EMOJIS[type_name],
                    default=type_name in enabled_types,
                )
                for type_name in TYPE_PING_TYPES
            ],
            min_values=0,
            max_values=len(TYPE_PING_TYPES),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.type_ping_view.update_type_pings(interaction, self.values)


class TypePingView(discord.ui.View):
    def __init__(self, bot: "NamingBot", guild_id: int, user_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        enabled_types = bot.type_pings_for_user(guild_id, user_id)
        self.add_item(TypePingSelect(self))
        self.embed = format_type_ping_embed(enabled_types)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These type pings can only be used in their original server.",
                ephemeral=True,
            )
            return False
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the member who opened these type pings can edit them.",
                ephemeral=True,
            )
            return False
        return True

    async def update_type_pings(
        self,
        interaction: discord.Interaction,
        enabled_types: list[str],
    ) -> None:
        try:
            saved_types = self.bot.set_type_pings(
                self.guild_id,
                self.user_id,
                enabled_types,
            )
        except ValueError:
            logger.exception(
                "Could not save type pings for user %s in guild %s",
                self.user_id,
                self.guild_id,
            )
            await interaction.response.send_message(
                "I couldn't save your type pings. Check the bot logs.",
                ephemeral=True,
            )
            return

        updated_view = TypePingView(self.bot, self.guild_id, self.user_id)
        try:
            await interaction.response.edit_message(
                embed=updated_view.embed,
                view=updated_view,
            )
        except discord.HTTPException:
            logger.exception(
                "Could not refresh type pings for user %s in guild %s",
                self.user_id,
                self.guild_id,
            )
            await interaction.followup.send(
                "Your type pings were saved, but I couldn't refresh the display.",
                ephemeral=True,
            )
            return

        if len(saved_types) == len(TYPE_PING_TYPES):
            confirmation = "All type pings enabled."
        elif not saved_types:
            confirmation = "All type pings disabled."
        else:
            labels = " and ".join(type_name.title() for type_name in saved_types)
            confirmation = f"Type pings updated for {labels}."
        await interaction.followup.send(confirmation, ephemeral=True)

    @discord.ui.button(
        label="All On",
        style=discord.ButtonStyle.success,
        custom_id="type_pings:all_on",
        row=1,
    )
    async def enable_all(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.update_type_pings(interaction, list(TYPE_PING_TYPES))

    @discord.ui.button(
        label="All Off",
        style=discord.ButtonStyle.danger,
        custom_id="type_pings:all_off",
        row=1,
    )
    async def disable_all(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.update_type_pings(interaction, [])


@dataclass
class ChatEventSession:
    host_id: int
    channel: discord.abc.Messageable
    channel_id: int | None = None
    message: discord.Message | None = None
    participant_ids: set[int] = field(default_factory=set)
    sentence_counts: dict[int, int] = field(default_factory=dict)
    duration_seconds: float | None = None
    duration_label: str | None = None
    duration_selected: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    collecting: bool = False


def count_qualifying_sentences(content: str) -> int:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", content.strip())
    return sum(
        len(re.findall(r"\b[\w’'-]+\b", sentence)) >= 4
        for sentence in sentences
        if sentence
    )


def parse_chat_event_duration(value: str) -> tuple[float, str] | None:
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h)?\s*",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    amount = float(match.group(1))
    if not math.isfinite(amount) or amount <= 0:
        return None
    unit = (match.group(2) or "minutes").casefold()
    is_hours = unit.startswith("h")
    seconds = amount * (3600 if is_hours else 60)
    if not math.isfinite(seconds):
        return None
    normalized_unit = "hour" if is_hours else "minute"
    label = f"{amount:g} {normalized_unit}{'' if amount == 1 else 's'}"
    return seconds, label


class EventMenuView(discord.ui.View):
    def __init__(self, bot: "NamingBot", host_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.host_id = host_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "Only the person who started `v!event` can choose an event.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Chat event",
        style=discord.ButtonStyle.primary,
        custom_id="event_menu:chat",
    )
    async def chat_event(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.bot.start_chat_event(interaction, self.host_id)


class ChatEventDurationView(discord.ui.View):
    def __init__(self, session: ChatEventSession) -> None:
        super().__init__(timeout=300)
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.host_id:
            await interaction.response.send_message(
                "Only the event host can choose the duration.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.session.cancelled = True
        self.session.duration_selected.set()

    @discord.ui.button(
        label="Enter duration",
        style=discord.ButtonStyle.primary,
        custom_id="chat_event:enter_duration",
    )
    async def enter_duration(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.send_modal(ChatEventDurationModal(self.session))


class ChatEventDurationModal(discord.ui.Modal):
    def __init__(self, session: ChatEventSession) -> None:
        super().__init__(title="Chat event duration")
        self.session = session
        self.duration_input = discord.ui.TextInput(
            label="How long should the event last?",
            placeholder="For example: 7 minutes or 2 hours",
            required=True,
            max_length=32,
        )
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.host_id:
            await interaction.response.send_message(
                "Only the event host can choose the duration.",
                ephemeral=True,
            )
            return
        parsed_duration = parse_chat_event_duration(self.duration_input.value)
        if parsed_duration is None:
            await interaction.response.send_message(
                "Enter a positive duration in minutes or hours, such as `7 minutes` "
                "or `2 hours`. A number by itself is treated as minutes.",
                ephemeral=True,
            )
            return
        self.session.duration_seconds, self.session.duration_label = parsed_duration
        self.session.duration_selected.set()
        await interaction.response.send_message(
            f"Chat event duration set to {self.session.duration_label}.",
            ephemeral=True,
        )


class InertSettingsButton(discord.ui.Button):
    def __init__(self, section: str) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id=f"server_settings:open:{section}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class NamingSectionButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id="server_settings:open:naming",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=NamingSettingsView(self.bot, self.guild_id)
        )


class NamingSettingToggleButton(discord.ui.Button):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        setting: str,
        enabled: bool,
    ) -> None:
        if setting == "assisted":
            label = "Assisted" if enabled else "Name only"
        else:
            label = "On" if enabled else "Off"
        super().__init__(
            label=label,
            style=(
                discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.secondary
            ),
            custom_id=f"server_settings:naming:{setting}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.setting = setting

    async def callback(self, interaction: discord.Interaction) -> None:
        if (
            interaction.guild_id != self.guild_id
            or not has_manage_server_access(
                self.bot,
                self.guild_id,
                interaction.user,
            )
        ):
            await interaction.response.send_message(
                "Only members with Manage Server permission or the configured "
                "command role can change these settings.",
                ephemeral=True,
            )
            return
        try:
            self.bot.toggle_naming_setting(self.guild_id, self.setting)
        except ValueError:
            logger.exception("Could not save naming settings for guild %s", self.guild_id)
            await interaction.response.send_message(
                "I couldn't save these settings. Check the bot logs.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=NamingSettingsView(self.bot, self.guild_id)
        )


class AFKSettingToggleButton(discord.ui.Button):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        user_id: int,
        setting: str,
        enabled: bool,
    ) -> None:
        super().__init__(
            label="On" if enabled else "Off",
            style=(
                discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.danger
            ),
            custom_id=f"afk_settings:{setting}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.setting = setting

    async def callback(self, interaction: discord.Interaction) -> None:
        if (
            interaction.guild_id != self.guild_id
            or interaction.user.id != self.user_id
        ):
            await interaction.response.send_message(
                "Only the member who opened these AFK settings can change them.",
                ephemeral=True,
            )
            return
        try:
            self.bot.toggle_afk_setting(
                self.guild_id, self.user_id, self.setting
            )
        except ValueError:
            logger.exception(
                "Could not save AFK settings for guild %s user %s",
                self.guild_id,
                self.user_id,
            )
            await interaction.response.send_message(
                "I couldn't save your AFK settings. Check the bot logs.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=AFKSettingsView(self.bot, self.guild_id, self.user_id)
        )


class AFKSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int, user_id: int) -> None:
        super().__init__(timeout=300)
        settings = bot.afk_settings_for_user(guild_id, user_id)
        status = (
            "🟢 Receiving pings"
            if all(settings.values())
            else "🔴 AFK (muted)"
        )
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# AFK Settings\n"
                f"{status}\n"
                "Choose which Pokémon notifications you want to receive."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Shiny Hunt\n"
                    f"{'Receiving pings' if settings['shinyhunt'] else 'AFK (muted)'}"
                ),
                accessory=AFKSettingToggleButton(
                    bot, guild_id, user_id, "shinyhunt", settings["shinyhunt"]
                ),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Collection\n"
                    f"{'Receiving pings' if settings['collection'] else 'AFK (muted)'}"
                ),
                accessory=AFKSettingToggleButton(
                    bot, guild_id, user_id, "collection", settings["collection"]
                ),
            ),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


class NamingSettingsBackButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="server_settings:naming:back",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(self.bot, self.guild_id)
        )


class StarboardSectionButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id="server_settings:open:starboard",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.bot, self.guild_id)
        )


class ServerSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        settings = bot.naming_settings_for_guild(guild_id)
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# ⚙️ Vivillon Control Panel\n"
                "Choose a section below. Changes save instantly."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### 🏷️ Naming\n"
                    f"{'🟢 On' if settings['enabled'] else '🔴 Off'}  •  "
                    f"{'Assisted' if settings['assisted'] else 'Name only'}"
                ),
                accessory=NamingSectionButton(bot, guild_id),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### 🔔 Roles & Pings\n"
                    "Ping roles plus rare, regional, hunt, collection, "
                    "reserve and quest output."
                ),
                accessory=InertSettingsButton("roles"),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### ⭐ Starboard\n"
                    "Vivillon, Shiny, and Normal Starboard channels."
                ),
                accessory=StarboardSectionButton(bot, guild_id),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### 🎨 Appearance\n"
                    "Server profile, banner and embed color."
                ),
                accessory=AppearanceSectionButton(bot, guild_id),
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "-# Settings are stored for this server. To have them removed, "
                "open a ticket in the support server:\n"
                "-# https://discord.gg/5XurUaW8"
            ),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


async def starboard_settings_guard(
    interaction: discord.Interaction,
    guild_id: int,
    bot: "NamingBot",
) -> bool:
    if interaction.guild_id != guild_id:
        await interaction.response.send_message(
            "These settings can only be used in their original server.",
            ephemeral=True,
        )
        return False
    if not has_manage_server_access(bot, guild_id, interaction.user):
        await interaction.response.send_message(
            "You need Manage Server permission or the configured command role "
            "to change starboards.",
            ephemeral=True,
        )
        return False
    return True


class StarboardChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot: "NamingBot", guild_id: int, board: str) -> None:
        placeholders = {
            "normal": "Choose the Vivillon Starboard channel",
            "shiny": "Choose the shinyboard channel",
            "normal_pokemon": "Choose the Normal Starboard channel",
        }
        super().__init__(
            channel_types=[discord.ChannelType.text],
            placeholder=placeholders[board],
            custom_id=f"server_settings:starboard:select:{board}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.board = board

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await starboard_settings_guard(interaction, self.guild_id, self.bot):
            return
        channel = self.values[0]
        if getattr(getattr(channel, "guild", None), "id", None) != self.guild_id:
            await interaction.response.send_message(
                "Choose a channel from this server.",
                ephemeral=True,
            )
            return
        try:
            self.bot.set_starboard_channel(
                self.guild_id,
                self.board,
                channel.id,
                getattr(channel, "name", None),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.bot, self.guild_id)
        )


class StarboardClearButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int, board: str) -> None:
        labels = {
            "normal": "Clear Vivillon",
            "shiny": "Clear Shiny",
            "normal_pokemon": "Clear Normal",
        }
        super().__init__(
            label=labels[board],
            style=discord.ButtonStyle.secondary,
            custom_id=f"server_settings:starboard:clear:{board}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.board = board

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await starboard_settings_guard(interaction, self.guild_id, self.bot):
            return
        try:
            self.bot.set_starboard_channel(self.guild_id, self.board, None)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.bot, self.guild_id)
        )


class StarboardBackButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="server_settings:starboard:back",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(self.bot, self.guild_id)
        )


class StarboardSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        settings = bot.starboard_settings_for_guild(guild_id)
        vivillon_channel = settings["normal_channel"]
        shiny_channel = settings["shiny_channel"]
        normal_channel = settings["normal_pokemon_channel"]
        shiny_count = settings["shiny_count"]
        vivillon_text = (
            f"<#{vivillon_channel}>" if vivillon_channel else "`Not set`"
        )
        shiny_text = f"<#{shiny_channel}>" if shiny_channel else "`Not set`"
        normal_text = f"<#{normal_channel}>" if normal_channel else "`Not set`"
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# ⭐ Catch Starboards\n"
                "Choose where special catches are posted. Changes save instantly."
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "### Vivillon Starboard\n"
                f"Current channel: {vivillon_text}\n"
                "Receives shiny, high-IV (90%+), low-IV (under 10%), "
                "MissingNo., and Gigantamax catches."
            ),
            discord.ui.ActionRow(
                StarboardChannelSelect(bot, guild_id, "normal")
            ),
            discord.ui.TextDisplay(
                "### Shinyboard\n"
                f"Current channel: {shiny_text} · Caught shinies: {shiny_count}\n"
                "Receives shiny catches and increments the channel suffix "
                "(for example, `shiny-board-1`). The bot needs Manage Channels "
                "permission to rename it. A shiny catch is also posted to the "
                "Vivillon Starboard."
            ),
            discord.ui.ActionRow(
                StarboardChannelSelect(bot, guild_id, "shiny")
            ),
            discord.ui.TextDisplay(
                "### Normal Starboard\n"
                f"Current channel: {normal_text}\n"
                "Receives catches for the configured regional forms and "
                "featured Pokémon."
            ),
            discord.ui.ActionRow(
                StarboardChannelSelect(bot, guild_id, "normal_pokemon")
            ),
            discord.ui.ActionRow(
                StarboardClearButton(bot, guild_id, "normal"),
                StarboardClearButton(bot, guild_id, "shiny"),
                StarboardClearButton(bot, guild_id, "normal_pokemon"),
            ),
            discord.ui.Separator(),
            discord.ui.ActionRow(StarboardBackButton(bot, guild_id)),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


DEFAULT_EMBED_COLOR: Final[int] = 0x5865F2
APPEARANCE_MAX_BYTES: Final[int] = 10 * 1024 * 1024
APPEARANCE_IMAGE_TYPES: Final[tuple[str, ...]] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
)


def load_appearance(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_appearance(path: Path, data: dict[str, dict]) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save appearance to {path}") from error


def parse_hex_color(text: str) -> int | None:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", text.strip())
    return int(match.group(1), 16) if match else None


async def appearance_guard(
    interaction: discord.Interaction,
    guild_id: int,
    bot: "NamingBot",
) -> bool:
    if interaction.guild_id != guild_id:
        await interaction.response.send_message(
            "These settings can only be used in their original server.",
            ephemeral=True,
        )
        return False
    if not has_manage_server_access(bot, guild_id, interaction.user):
        await interaction.response.send_message(
            "You need Manage Server permission or the configured command role "
            "to change appearance.",
            ephemeral=True,
        )
        return False
    return True


class AppearanceSectionButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Open",
            style=discord.ButtonStyle.primary,
            custom_id="server_settings:open:appearance",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=AppearanceSettingsView(self.bot, self.guild_id)
        )


class AppearanceActionButton(discord.ui.Button):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        action: str,
        label: str,
        style: discord.ButtonStyle,
    ) -> None:
        super().__init__(
            label=label,
            style=style,
            custom_id=f"server_settings:appearance:{action}",
        )
        self.bot = bot
        self.guild_id = guild_id
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await appearance_guard(interaction, self.guild_id, self.bot):
            return
        if self.action == "color":
            await interaction.response.send_modal(
                AppearanceTextModal(self.bot, self.guild_id, "color")
            )
        elif self.action == "name":
            await interaction.response.send_modal(
                AppearanceTextModal(self.bot, self.guild_id, "name")
            )
        elif self.action in ("avatar", "banner"):
            await interaction.response.send_modal(
                AppearanceUploadModal(self.bot, self.guild_id, self.action)
            )
        else:
            await self.bot.reset_appearance(
                interaction, self.guild_id, self.action
            )


class AppearanceTextModal(discord.ui.Modal):
    def __init__(self, bot: "NamingBot", guild_id: int, field: str) -> None:
        super().__init__(
            title="Set Embed Color" if field == "color" else "Set Bot Name"
        )
        self.bot = bot
        self.guild_id = guild_id
        self.field = field
        self.value = discord.ui.TextInput(
            label="Hex color (e.g. #FCE5E7)" if field == "color" else "Bot name",
            placeholder="#FCE5E7" if field == "color" else "Leave empty to reset",
            required=field == "color",
            max_length=7 if field == "color" else 32,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await appearance_guard(interaction, self.guild_id, self.bot):
            return
        text = self.value.value.strip()
        if self.field == "color":
            color = parse_hex_color(text)
            if color is None:
                await interaction.response.send_message(
                    "That isn't a valid hex color. Use six digits like `#FCE5E7`.",
                    ephemeral=True,
                )
                return
            self.bot.update_appearance(self.guild_id, color=color)
        else:
            guild = interaction.guild
            member = guild.me if guild is not None else None
            if member is None:
                await interaction.response.send_message(
                    "I couldn't find my server member to change the bot name.",
                    ephemeral=True,
                )
                return
            try:
                await member.edit(nick=text or None)
            except discord.HTTPException as error:
                await interaction.response.send_message(
                    f"I couldn't change my name: {error}", ephemeral=True
                )
                return
            self.bot.update_appearance(self.guild_id, name=text or None)
        await interaction.response.edit_message(
            view=AppearanceSettingsView(self.bot, self.guild_id)
        )


class AppearanceUploadModal(discord.ui.Modal):
    def __init__(self, bot: "NamingBot", guild_id: int, field: str) -> None:
        label = "Bot Profile Image" if field == "avatar" else "Bot Server Banner"
        super().__init__(title=f"Upload {label}")
        self.bot = bot
        self.guild_id = guild_id
        self.field = field
        self.upload = discord.ui.FileUpload(min_values=1, max_values=1)
        self.add_item(
            discord.ui.Label(
                text="Profile Image" if field == "avatar" else "Server Banner",
                description="PNG, JPEG, GIF, or WEBP; maximum 10 MB.",
                component=self.upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await appearance_guard(interaction, self.guild_id, self.bot):
            return
        if not self.upload.values:
            await interaction.response.send_message(
                "No file was uploaded.", ephemeral=True
            )
            return
        await self.bot.apply_appearance_image(
            interaction, self.guild_id, self.field, self.upload.values[0]
        )


class AppearanceBackButton(discord.ui.Button):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="server_settings:appearance:back",
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message(
                "These settings can only be used in their original server.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(self.bot, self.guild_id)
        )


class AppearanceSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        data = bot.appearance.get(str(guild_id), {})
        color = data.get("color")
        primary = discord.ButtonStyle.primary
        danger = discord.ButtonStyle.danger

        def action(name: str, label: str, style: discord.ButtonStyle):
            return AppearanceActionButton(bot, guild_id, name, label, style)

        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# Server Settings · Appearance\n"
                "-# Configure this section, then use Back to choose another."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Profile Image**\n"
                    f"`{'Custom' if data.get('avatar') else 'Default'}`\n"
                    "Upload a PNG, JPEG, GIF, or WEBP image up to 10 MB."
                ),
                accessory=action("avatar", "Upload", primary),
            ),
            discord.ui.ActionRow(action("avatar_reset", "Reset Profile Image", danger)),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Server Banner**\n"
                    f"`{'Custom' if data.get('banner') else 'Default'}`\n"
                    "The banner appears only on Vivillon's profile in this server."
                ),
                accessory=action("banner", "Upload", primary),
            ),
            discord.ui.ActionRow(action("banner_reset", "Reset Server Banner", danger)),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Embed Color**\n"
                    f"`#{(color if color is not None else DEFAULT_EMBED_COLOR):06X}`"
                    f" · {'Custom' if color is not None else 'Default'}\n"
                    "Replaces Vivillon's default blue on embeds in this server."
                ),
                accessory=action("color", "Set Color", primary),
            ),
            discord.ui.ActionRow(action("color_reset", "Reset Embed Color", danger)),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "**Bot Name**\n"
                    f"`{data.get('name') or 'Default'}`\n"
                    "Changes Vivillon's nickname in this server."
                ),
                accessory=action("name", "Set Name", primary),
            ),
            discord.ui.ActionRow(action("name_reset", "Reset Bot Name", danger)),
            discord.ui.Separator(),
            discord.ui.ActionRow(AppearanceBackButton(bot, guild_id)),
            accent_color=discord.Color(
                color if color is not None else DEFAULT_EMBED_COLOR
            ),
        )
        self.add_item(container)


class NamingSettingsView(discord.ui.LayoutView):
    def __init__(self, bot: "NamingBot", guild_id: int) -> None:
        super().__init__(timeout=None)
        settings = bot.naming_settings_for_guild(guild_id)
        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "# 🏷️ Naming Settings\n"
                "Tap a button to switch a setting. Use Back when you're done."
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Naming\n"
                    f"{'🟢 On' if settings['enabled'] else '🔴 Off'}\n"
                    "Allow Vivillon to send Pokémon predictions."
                ),
                accessory=NamingSettingToggleButton(
                    bot, guild_id, "enabled", settings["enabled"]
                ),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Naming Mode\n"
                    f"{'🟢 Assisted' if settings['assisted'] else '⚪ Name only'}\n"
                    "Assisted mode adds copy-ready catch commands."
                ),
                accessory=NamingSettingToggleButton(
                    bot, guild_id, "assisted", settings["assisted"]
                ),
            ),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "### Only Pings\n"
                    f"{'🟢 On' if settings['only_pings'] else '🔴 Off'}\n"
                    "Only send ordinary naming replies when a reserve, shiny hunt, "
                    "collection, or type ping matches."
                ),
                accessory=NamingSettingToggleButton(
                    bot, guild_id, "only_pings", settings["only_pings"]
                ),
            ),
            discord.ui.Separator(),
            discord.ui.Section(
                discord.ui.TextDisplay("↩️ Back to the Control Panel."),
                accessory=NamingSettingsBackButton(bot, guild_id),
            ),
            accent_color=discord.Color(0x9B59F5),
        )
        self.add_item(container)


RESERVE_LIST_CACHE: Final[OrderedDict[int, list[str]]] = OrderedDict()
MENTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"<@!?(\d+)>")
GRAB_PAGE_CHARS: Final[int] = 3800


def remember_reserve_list(message_id: int, embeds: list[discord.Embed]) -> None:
    RESERVE_LIST_CACHE[message_id] = [
        embed.description for embed in embeds if embed.description
    ]
    while len(RESERVE_LIST_CACHE) > 300:
        RESERVE_LIST_CACHE.popitem(last=False)


def load_known_pokemon_names() -> list[str]:
    names: set[str] = {"Missingno"}
    try:
        data = json.loads(
            data_path("pokemon_names.json").read_text(encoding="utf-8")
        )
        names.update(name for name in data if isinstance(name, str))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load pokemon_names.json; v!grab will be limited")
    for forms in POKEMON_FORMS.values():
        names.update(form["display_name"] for form in forms)
    names.update(POKEMON_FORMS)
    names.update(CUSTOM_FORM_SPECIES)
    return sorted(
        (name.replace("’", "'") for name in names), key=len, reverse=True
    )


NAME_SUGGESTION_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "all", "normal", "mega", "alolan", "galarian", "hisuian", "paldean",
        "gmax", "gigantamax", "primal",
    }
)
POKEMON_NAME_ALIASES: Final[dict[str, str]] = {
    "riffex": "toxtricity",
    "madusa simipour": "medusa simipour",
    "misipour": "simipour",
}
NAME_SUGGESTION_CUTOFF: Final[float] = 0.6
NAME_SUGGESTION_TIMEOUT_SECONDS: Final[int] = 60


def canonicalize_pokemon_name(name: str) -> str:
    name = canonicalize_regional_name(name)
    words = normalize_pokemon_alias(name.replace("’", "'")).split()
    prefix_count = 0
    while (
        prefix_count < len(words) - 1
        and words[prefix_count] in NAME_SUGGESTION_PREFIXES
    ):
        prefix_count += 1
    alias = POKEMON_NAME_ALIASES.get(" ".join(words[prefix_count:]))
    if alias is None:
        return name
    return " ".join((*words[:prefix_count], alias))


@lru_cache(maxsize=1)
def known_name_lookup() -> dict[str, str]:
    return {
        normalize_pokemon_alias(name): name for name in load_known_pokemon_names()
    }


def strip_name_prefixes(name: str) -> tuple[list[str], list[str]]:
    words = normalize_pokemon_alias(name.replace("’", "'")).split(" ")
    prefix_count = 0
    while (
        prefix_count < len(words) - 1
        and words[prefix_count] in NAME_SUGGESTION_PREFIXES
    ):
        prefix_count += 1
    return words[:prefix_count], words[prefix_count:]


@lru_cache(maxsize=1)
def known_name_word_sets() -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(sorted(name.split(" "))) for name in known_name_lookup())


def is_known_pokemon_name(name: str) -> bool:
    name = canonicalize_pokemon_name(name)
    lookup = known_name_lookup()
    words = normalize_pokemon_alias(name.replace("’", "'")).split(" ")
    if " ".join(words) in lookup or tuple(sorted(words)) in known_name_word_sets():
        return True
    prefix_count = 0
    while prefix_count < len(words) - 1 and words[prefix_count] in NAME_SUGGESTION_PREFIXES:
        prefix_count += 1
    base = " ".join(words[prefix_count:])
    return base in lookup or is_missingno_name(base)


def suggest_pokemon_name(name: str) -> str | None:
    """Return a corrected name when `name` looks like a misspelled Pokémon."""
    import difflib

    name = canonicalize_pokemon_name(name)
    lookup = known_name_lookup()
    words = normalize_pokemon_alias(name.replace("’", "'")).split(" ")
    prefix_count = 0
    while prefix_count < len(words) - 1 and words[prefix_count] in NAME_SUGGESTION_PREFIXES:
        prefix_count += 1
    base = " ".join(words[prefix_count:])
    if not base or base in lookup or is_missingno_name(base):
        return None
    matches = difflib.get_close_matches(
        base, list(lookup), n=1, cutoff=NAME_SUGGESTION_CUTOFF
    )
    if not matches:
        return None
    suggestion = lookup[matches[0]]
    prefix = " ".join(words[:prefix_count])
    original_prefix = " ".join(name.split()[:prefix_count])
    return f"{original_prefix} {suggestion}".strip() if prefix else suggestion


def add_activity_routes(app: web.Application, client_id: int) -> None:
    """Serve the Discord Activity that loops the profile song."""
    index = (ACTIVITY_DIR / "index.html").read_text(encoding="utf-8").replace(
        "__CLIENT_ID__", str(client_id)
    )

    async def serve_index(request: web.Request) -> web.Response:
        del request
        return web.Response(text=index, content_type="text/html")

    app.router.add_get("/", serve_index)
    app.router.add_get("/index.html", serve_index)
    app.router.add_static("/", ACTIVITY_DIR, follow_symlinks=False)


def create_activity_app(client_id: int) -> web.Application:
    app = web.Application()
    add_activity_routes(app, client_id)
    return app


def _org_api_port_from_environment() -> int:
    for variable in ("ORG_API_PORT", "SERVER_PORT", "PORT"):
        value = os.environ.get(variable)
        if value:
            try:
                return int(value)
            except ValueError as error:
                raise ValueError(f"{variable} must be a valid port number") from error
    return 8080


GRAB_NAME_PREFIXES: Final[str] = (
    r"(?:(?:all\s+forms\s+of|all|mega|alolan|galarian|hisuian|paldean|gmax|"
    r"gigantamax|primal)\s+)*"
)
GRAB_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w'])"
    + GRAB_NAME_PREFIXES
    + "(?:"
    + "|".join(re.escape(name) for name in load_known_pokemon_names())
    + r")(?![\w'])",
    re.IGNORECASE,
)


def parse_grab_entries(texts: list[str]) -> list[tuple[str, list[int]]]:
    entries: list[tuple[str, list[int]]] = []
    for text in texts:
        for line in text.replace("’", "'").splitlines():
            previous_user: int | None = None
            for group in line.split("|"):
                mentions = [
                    (m.start(), int(user_id))
                    for m in MENTION_PATTERN.finditer(group)
                    for user_id in MENTION_PATTERN.findall(m.group())[:1]
                ]
                blanked = MENTION_PATTERN.sub(lambda m: " " * len(m.group()), group)
                for match in GRAB_NAME_PATTERN.finditer(blanked):
                    name = " ".join(
                        unicodedata.normalize("NFC", match.group()).split()
                    )
                    if name.casefold().startswith("all forms of "):
                        name = "all " + name[len("all forms of ") :]
                    # Only the nearest mention before the name gets it.
                    before = [uid for pos, uid in mentions if pos < match.start()]
                    if before:
                        owner = before[-1]
                    elif mentions:
                        owner = mentions[0][1]
                    else:
                        owner = previous_user
                    entries.append((name, [] if owner is None else [owner]))
                    if owner is not None:
                        previous_user = owner
    return entries


def grab_entry_name(name: str, all_forms: bool) -> str:
    if name.casefold().startswith("all "):
        return name if all_forms else name[4:].strip()
    return name


def build_grab_lines(
    entries: list[tuple[str, list[int]]],
    *,
    ordered: bool,
    all_forms: bool,
    emojis: list[str],
) -> list[str]:
    names = [grab_entry_name(name, all_forms) for name, _ in entries]
    if ordered:
        names.sort(key=lambda name: name.casefold().removeprefix("all "))
    lines: list[str] = []
    for index, name in enumerate(names):
        line = name[0].upper() + name[1:]
        if emojis:
            line = f"{emojis[index % len(emojis)]} {line}"
        lines.append(line)
    return lines


def paginate_grab_lines(
    lines: list[str], limit: int = GRAB_PAGE_CHARS
) -> list[str]:
    pages: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        if current and length + len(line) + 1 > limit:
            pages.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        pages.append("\n".join(current))
    return pages or ["No Pokémon."]


def grab_reserve_pairs(
    entries: list[tuple[str, list[int]]],
    all_forms: bool,
) -> list[tuple[str, int]]:
    return [
        (grab_entry_name(name, all_forms), user_id)
        for name, user_ids in entries
        for user_id in user_ids
    ]


def grab_display_name(name: str) -> str:
    if name.casefold().startswith("all "):
        return f"all forms of {name[4:]}".capitalize()
    return name[0].upper() + name[1:]


def add_reservations_bulk(
    reservations: dict[str, list[int]],
    guild_id: int,
    pairs: list[tuple[str, int]],
) -> dict[str, list[int]]:
    updated = {key: list(user_ids) for key, user_ids in reservations.items()}
    for name, user_id in pairs:
        user_ids = updated.setdefault(reservation_key_for_command(guild_id, name), [])
        if user_id not in user_ids:
            user_ids.append(user_id)
    return updated


async def reply_with_reservation_embeds(
    message: discord.Message,
    embeds: list[discord.Embed],
) -> None:
    view = (
        ReservationPagesView(embeds, message.guild.id)
        if len(embeds) > 1 and message.guild is not None
        else None
    )
    if view is None:
        response = await message.reply(
            embed=embeds[0],
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    else:
        response = await message.reply(
            embed=embeds[0],
            view=view,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    if view is not None:
        view.message = response
    remember_reserve_list(response.id, embeds)


async def reply_with_spawn_media(
    message: discord.Message,
    content: str,
    *,
    embed: discord.Embed | None,
    files: list[discord.File],
) -> discord.Message:
    if embed is None:
        if files:
            return await message.reply(
                content,
                files=files,
                mention_author=False,
            )
        return await message.reply(content, mention_author=False)
    if files:
        return await message.reply(
            content,
            embed=embed,
            files=files,
            mention_author=False,
        )
    return await message.reply(
        content,
        embed=embed,
        mention_author=False,
    )


def load_reservations(path: Path) -> dict[str, list[int]]:
    table = pg_store.table_for(path)
    if table:
        return pg_store.load(table)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read reserve data from {path}") from error
    if not isinstance(data, dict) or any(
        not isinstance(key, str)
        or not isinstance(user_ids, list)
        or any(
            isinstance(user_id, bool) or not isinstance(user_id, int)
            for user_id in user_ids
        )
        for key, user_ids in data.items()
    ):
        raise ValueError(f"Reserve data in {path} has an invalid format")
    return data


def save_reservations(path: Path, reservations: dict[str, list[int]]) -> None:
    table = pg_store.table_for(path)
    if table:
        pg_store.save(table, reservations)
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(reservations, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save reserve data to {path}") from error


def load_reserve_categories(
    path: Path,
) -> dict[str, dict[str, list[str]]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read reserve categories from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Reserve categories in {path} have an invalid format")

    categories: dict[str, dict[str, list[str]]] = {}
    for guild_id, server_categories in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(server_categories, dict)
        ):
            raise ValueError(f"Reserve categories in {path} have an invalid format")
        validated_categories: dict[str, list[str]] = {}
        for category_name, pokemon_names in server_categories.items():
            if (
                not isinstance(category_name, str)
                or re.fullmatch(r"[a-z0-9_-]{1,32}", category_name, re.IGNORECASE)
                is None
                or not isinstance(pokemon_names, list)
                or any(
                    not isinstance(name, str)
                    or not is_valid_pokemon_name(name)
                    for name in pokemon_names
                )
            ):
                raise ValueError(
                    f"Reserve categories in {path} have an invalid format"
                )
            category_key = reserve_category_storage_key(category_name)
            if category_key in validated_categories:
                raise ValueError(
                    f"Reserve categories in {path} have duplicate category names"
                )
            validated_categories[category_key] = [
                canonicalize_pokemon_name(name) for name in pokemon_names
            ]
        categories[guild_id] = validated_categories
    return categories


def save_reserve_categories(
    path: Path,
    categories: dict[str, dict[str, list[str]]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(categories, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save reserve categories to {path}") from error


SERVER_NAMING_DEFAULTS: Final[dict[str, bool]] = {
    "enabled": True,
    "assisted": True,
    "only_pings": False,
}
SERVER_NAMING_SETTING_KEYS: Final[frozenset[str]] = frozenset(
    SERVER_NAMING_DEFAULTS
)
LEGACY_SERVER_NAMING_SETTING_KEYS: Final[frozenset[str]] = frozenset({"pings"})


def load_server_settings(path: Path) -> dict[str, dict[str, bool]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read server settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Server settings in {path} have an invalid format")

    settings: dict[str, dict[str, bool]] = {}
    for guild_id, guild_settings in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(guild_settings, dict)
            or any(
                key not in SERVER_NAMING_SETTING_KEYS
                and key not in LEGACY_SERVER_NAMING_SETTING_KEYS
                or not isinstance(value, bool)
                for key, value in guild_settings.items()
            )
        ):
            raise ValueError(f"Server settings in {path} have an invalid entry")
        settings[guild_id] = {
            **SERVER_NAMING_DEFAULTS,
            **{
                key: value
                for key, value in guild_settings.items()
                if key in SERVER_NAMING_SETTING_KEYS
            },
        }
    return settings


def save_server_settings(
    path: Path,
    settings: dict[str, dict[str, bool]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save server settings to {path}") from error


STARBOARD_DEFAULTS: Final[dict[str, int | str | None]] = {
    "normal_channel": None,
    "shiny_channel": None,
    "normal_pokemon_channel": None,
    "shiny_base_name": None,
    "shiny_count": 0,
}


class StarboardSettings(TypedDict):
    normal_channel: int | None
    shiny_channel: int | None
    normal_pokemon_channel: int | None
    shiny_base_name: str | None
    shiny_count: int


class ActiveIncense(TypedDict):
    guild: str
    channel: str
    guild_id: int
    expires_at: int


STARBOARD_SETTING_KEYS: Final[frozenset[str]] = frozenset(STARBOARD_DEFAULTS)
STARBOARD_CHANNEL_SETTING_KEYS: Final[dict[str, str]] = {
    "normal": "normal_channel",
    "shiny": "shiny_channel",
    "normal_pokemon": "normal_pokemon_channel",
}


def split_channel_counter(channel_name: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)-(\d+)", channel_name.strip())
    if match is None:
        return channel_name.strip(), 0
    return match.group(1), int(match.group(2))


def load_starboard_settings(
    path: Path,
) -> dict[str, dict[str, int | str | None]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read starboard settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Starboard settings in {path} have an invalid format")

    settings: dict[str, dict[str, int | str | None]] = {}
    for guild_id, guild_settings in data.items():
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdecimal()
            or not isinstance(guild_settings, dict)
            or any(
                key not in STARBOARD_SETTING_KEYS or not valid_starboard_setting(key, value)
                for key, value in guild_settings.items()
            )
        ):
            raise ValueError(f"Starboard settings in {path} have an invalid entry")
        settings[guild_id] = {
            **STARBOARD_DEFAULTS,
            **guild_settings,
        }
    return settings


def save_starboard_settings(
    path: Path,
    settings: dict[str, dict[str, int | str | None]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save starboard settings to {path}") from error


def valid_starboard_setting(key: str, value: object) -> bool:
    if key in STARBOARD_CHANNEL_SETTING_KEYS.values():
        return value is None or (
            isinstance(value, int) and not isinstance(value, bool) and value > 0
        )
    if key == "shiny_base_name":
        return value is None or (
            isinstance(value, str) and bool(value.strip()) and len(value) <= 100
        )
    if key == "shiny_count":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return False


AFK_DEFAULTS: Final[dict[str, bool]] = {
    "shinyhunt": True,
    "collection": True,
}
AFK_SETTING_KEYS: Final[frozenset[str]] = frozenset(AFK_DEFAULTS)


def load_afk_settings(path: Path) -> dict[str, dict[str, bool]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read AFK settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"AFK settings in {path} have an invalid format")

    settings: dict[str, dict[str, bool]] = {}
    for user_key, user_settings in data.items():
        ids = user_key.split(":") if isinstance(user_key, str) else []
        if (
            len(ids) != 2
            or any(not identifier.isdecimal() for identifier in ids)
            or not isinstance(user_settings, dict)
            or any(
                key not in AFK_SETTING_KEYS or not isinstance(value, bool)
                for key, value in user_settings.items()
            )
        ):
            raise ValueError(f"AFK settings in {path} have an invalid entry")
        settings[user_key] = {**AFK_DEFAULTS, **user_settings}
    return settings


def save_afk_settings(
    path: Path,
    settings: dict[str, dict[str, bool]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save AFK settings to {path}") from error


def load_type_pings(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read type ping settings from {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Type ping settings in {path} have an invalid format")

    type_pings: dict[str, list[str]] = {}
    for user_key, enabled_types in data.items():
        ids = user_key.split(":") if isinstance(user_key, str) else []
        if (
            len(ids) != 2
            or any(not identifier.isdecimal() for identifier in ids)
            or not isinstance(enabled_types, list)
            or any(
                not isinstance(type_name, str)
                or type_name not in TYPE_PING_TYPES
                for type_name in enabled_types
            )
        ):
            raise ValueError(f"Type ping settings in {path} have an invalid entry")
        type_pings[user_key] = list(dict.fromkeys(enabled_types))
    return type_pings


def save_type_pings(path: Path, type_pings: dict[str, list[str]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(type_pings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save type ping settings to {path}") from error


def clear_guild_type_pings(
    type_pings: dict[str, list[str]],
    guild_id: int,
) -> dict[str, list[str]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(enabled_types)
        for key, enabled_types in type_pings.items()
        if not key.startswith(guild_prefix)
    }


def valid_profile_setting(setting: str, value: object) -> bool:
    if setting == "catches":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    choices = PROFILE_SETTING_CHOICES.get(setting)
    legacy_choices = PROFILE_LEGACY_CHOICES.get(setting, frozenset())
    return (
        isinstance(value, str)
        and choices is not None
        and (value in choices or value in legacy_choices)
    )


def load_profile_data(
    path: Path,
) -> tuple[
    dict[str, dict[str, int | str]],
    dict[str, dict[str, int]],
    dict[str, dict[str, ProfileIvRecord]],
    list[int],
]:
    if not path.exists():
        return {}, {}, {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read profile data from {path}") from error
    legacy_keys = {"users", "seen_catch_message_ids"}
    current_keys = legacy_keys | {"server_stats"}
    record_keys = current_keys | {"server_records"}
    if (
        not isinstance(data, dict)
        or set(data) not in (legacy_keys, current_keys, record_keys)
        or not isinstance(data["users"], dict)
        or not isinstance(data["seen_catch_message_ids"], list)
        or (
            "server_stats" in data
            and not isinstance(data["server_stats"], dict)
        )
        or (
            "server_records" in data
            and not isinstance(data["server_records"], dict)
        )
    ):
        raise ValueError(f"Profile data in {path} has an invalid format")

    profiles: dict[str, dict[str, int | str]] = {}
    for user_id, stored_settings in data["users"].items():
        if isinstance(stored_settings, dict) and stored_settings.get("frame") == "gardevoir":
            stored_settings["frame"] = "magic"
        if (
            not isinstance(user_id, str)
            or not user_id.isdecimal()
            or not isinstance(stored_settings, dict)
            or any(
                setting not in PROFILE_DEFAULTS and setting != "catches"
                or not valid_profile_setting(setting, value)
                for setting, value in stored_settings.items()
            )
        ):
            raise ValueError(f"Profile data in {path} has an invalid user entry")
        profile = {
            **PROFILE_DEFAULTS,
            **{
                setting: value
                for setting, value in stored_settings.items()
                if setting != "catches"
            },
        }
        for setting, legacy_choices in PROFILE_LEGACY_CHOICES.items():
            if profile[setting] in legacy_choices:
                profile[setting] = PROFILE_DEFAULTS[setting]
        for owner_id, owner_choices in PROFILE_USER_ONLY_CHOICES.items():
            if user_id != str(owner_id) and int(user_id) not in PROFILE_ALL_ACCESS_USER_IDS:
                for setting, restricted_choices in owner_choices.items():
                    if profile[setting] in restricted_choices:
                        profile[setting] = PROFILE_DEFAULTS[setting]
        profiles[user_id] = profile

    profile_stats: dict[str, dict[str, int]] = {}
    for user_key, stored_stats in data.get("server_stats", {}).items():
        ids = user_key.split(":") if isinstance(user_key, str) else []
        if (
            len(ids) != 2
            or any(not identifier.isdecimal() for identifier in ids)
            or not isinstance(stored_stats, dict)
            or any(
                stat not in PROFILE_STAT_DEFAULTS
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for stat, value in stored_stats.items()
            )
        ):
            raise ValueError(f"Profile data in {path} has an invalid server stat")
        profile_stats[user_key] = {
            **PROFILE_STAT_DEFAULTS,
            **stored_stats,
        }

    profile_records: dict[str, dict[str, ProfileIvRecord]] = {}
    for user_key, stored_records in data.get("server_records", {}).items():
        ids = user_key.split(":") if isinstance(user_key, str) else []
        if (
            len(ids) != 2
            or any(not identifier.isdecimal() for identifier in ids)
            or not isinstance(stored_records, dict)
        ):
            raise ValueError(f"Profile data in {path} has an invalid server record")
        records: dict[str, ProfileIvRecord] = {}
        for record_name, record in stored_records.items():
            if (
                record_name not in PROFILE_RECORD_LABELS
                or not isinstance(record, dict)
                or set(record) not in (
                    {"pokemon", "iv"},
                    {"pokemon", "iv", "level", "gender"},
                )
                or not isinstance(record["pokemon"], str)
                or not record["pokemon"]
                or isinstance(record["iv"], bool)
                or not isinstance(record["iv"], (int, float))
                or not 0 <= record["iv"] <= 100
                or (
                    "level" in record
                    and (
                        not isinstance(record["level"], str)
                        or not record["level"]
                    )
                )
                or (
                    "gender" in record
                    and record["gender"] not in (None, "Male", "Female")
                )
            ):
                raise ValueError(f"Profile data in {path} has an invalid IV record")
            records[record_name] = ProfileIvRecord(
                pokemon=record["pokemon"],
                iv=float(record["iv"]),
                level=record.get("level", "???"),
                gender=record.get("gender"),
            )
        profile_records[user_key] = records

    seen_catch_ids = data["seen_catch_message_ids"]
    if any(
        isinstance(message_id, bool)
        or not isinstance(message_id, int)
        or message_id <= 0
        for message_id in seen_catch_ids
    ):
        raise ValueError(f"Profile data in {path} has invalid catch message IDs")
    return profiles, profile_stats, profile_records, seen_catch_ids[-10000:]


def save_profile_data(
    path: Path,
    profiles: dict[str, dict[str, int | str]],
    profile_stats: dict[str, dict[str, int]],
    profile_records: dict[str, dict[str, ProfileIvRecord]],
    seen_catch_ids: list[int],
) -> None:
    data = {
        "users": profiles,
        "server_stats": profile_stats,
        "server_records": {
            user_key: {
                name: {
                    "pokemon": record.pokemon,
                    "iv": record.iv,
                    "level": record.level,
                    "gender": record.gender,
                }
                for name, record in records.items()
            }
            for user_key, records in profile_records.items()
        },
        "seen_catch_message_ids": seen_catch_ids[-10000:],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save profile data to {path}") from error


def dye_gradient(size: tuple[int, int], dye: dict[str, str]) -> Image.Image:
    first = Image.new("RGB", size, dye["color"])
    if dye["rarity"] == "normal" or "color2" not in dye:
        return first
    second = Image.new("RGB", size, dye["color2"])
    ramp = Image.linear_gradient("L")
    vertical = ramp.resize(size)
    horizontal = ramp.transpose(Image.Transpose.ROTATE_90).transpose(Image.Transpose.FLIP_TOP_BOTTOM).resize(size)
    mask = ImageChops.add(vertical, horizontal, scale=2)
    return Image.composite(second, first, mask)


def dye_glow_color(dye: dict[str, str]) -> tuple[int, int, int]:
    first, second = (
        ImageColor.getrgb(dye.get(key, dye["color"])) for key in ("color", "color2")
    )
    return tuple((a + b) // 2 for a, b in zip(first, second))


def add_dye_sparkles(
    image: Image.Image, dye: dict[str, str], count: int, mask: Image.Image | None = None
) -> None:
    rng = random.Random(dye.get("code", dye.get("name", "")))
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for _ in range(count * 4):
        x, y = rng.randrange(width), rng.randrange(height)
        if mask is not None and mask.getpixel((x, y)) < 200:
            continue
        reach = rng.choice((2, 3, 4))
        draw.line((x - reach, y, x + reach, y), fill=(255, 255, 255, 255))
        draw.line((x, y - reach, x, y + reach), fill=(255, 255, 255, 255))
        count -= 1
        if count <= 0:
            break


def apply_background_dye(image: Image.Image, dye: dict[str, str]) -> Image.Image:
    result = Image.blend(image.convert("RGB"), dye_gradient(image.size, dye), 0.3)
    if dye["rarity"] == "normal":
        return result
    add_dye_sparkles(result, dye, 40)
    if dye["rarity"] == "glow":
        bloom = result.filter(ImageFilter.GaussianBlur(24))
        result = Image.blend(result, ImageChops.screen(result, bloom), 0.6)
    return result


def profile_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    font_path = Path("/usr/share/fonts/truetype/dejavu") / filename
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        return ImageFont.load_default(size=size)


def draw_profile_stat_icon(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    name: str,
    position: tuple[int, int],
    emoji_assets: dict[str, bytes],
) -> None:
    x, y = position
    asset = emoji_assets.get(name)
    if asset is not None:
        try:
            with Image.open(BytesIO(asset)) as emoji:
                emoji_image = emoji.convert("RGBA")
            emoji_image.thumbnail((36, 36), Image.Resampling.LANCZOS)
            image.paste(emoji_image, (x, y), emoji_image)
            return
        except OSError as error:
            logger.warning("Could not render profile emoji %s: %s", name, error)

    if name == "shiny":
        draw.polygon(
            [
                (x + 17, y),
                (x + 22, y + 12),
                (x + 35, y + 17),
                (x + 22, y + 22),
                (x + 17, y + 35),
                (x + 12, y + 22),
                (x, y + 17),
                (x + 12, y + 12),
            ],
            fill="#F4D06F",
        )
    elif name in {"low_iv", "high_iv"}:
        color = "#F05B63" if name == "low_iv" else "#52C788"
        points = (
            [(x + 3, y + 5), (x + 12, y + 13), (x + 21, y + 18), (x + 32, y + 29)]
            if name == "low_iv"
            else [(x + 3, y + 29), (x + 12, y + 21), (x + 21, y + 15), (x + 32, y + 4)]
        )
        draw.line(points, fill=color, width=4)
        end_x, end_y = points[-1]
        direction = 1 if name == "low_iv" else -1
        draw.polygon(
            [
                (end_x, end_y),
                (end_x - 10, end_y - 2 * direction),
                (end_x - 3, end_y - 10 * direction),
            ],
            fill=color,
        )
    elif name == "gmax":
        draw.ellipse((x + 2, y + 2, x + 34, y + 34), fill="#E84B4B")
        draw.rectangle((x + 3, y + 15, x + 33, y + 21), fill="#FFFFFF")
        draw.ellipse((x + 12, y + 12, x + 24, y + 24), fill="#FFFFFF")
        draw.ellipse((x + 15, y + 15, x + 21, y + 21), fill="#303036")
    else:
        draw.rectangle((x + 3, y + 3, x + 33, y + 33), fill="#9A72B8")
        draw.text((x + 8, y + 3), "?", font=profile_font(27, bold=True), fill="#FFFFFF")


def format_profile_iv_record(record: ProfileIvRecord) -> tuple[str, str]:
    return (
        f"Level {record.level} {record.pokemon}",
        f"{record.gender or 'Gender unknown'} | {record.iv:.2f}%",
    )


def profile_background_tint(image: Image.Image) -> tuple[int, int, int]:
    left_color = ImageStat.Stat(image.crop((0, 0, 430, image.height))).mean
    right_color = ImageStat.Stat(
        image.crop((950, 0, image.width, image.height))
    ).mean
    return (
        round((left_color[0] + right_color[0]) / 2),
        round((left_color[1] + right_color[1]) / 2),
        round((left_color[2] + right_color[2]) / 2),
    )


def render_profile_image(
    settings: dict[str, int | str],
    stats: dict[str, int],
    emoji_assets: dict[str, bytes] | None = None,
    records: dict[str, ProfileIvRecord] | None = None,
    *,
    username: str | None = None,
    avatar: bytes | None = None,
    level: int = 0,
    dyes: dict[str, dict[str, str]] | None = None,
) -> BytesIO:
    width, height = 1400, 825
    background_key = str(settings["background"])
    middle_key = str(settings["middle_background"])
    text_color_key = str(settings["text_color"])
    text_color = PROFILE_TEXT_COLORS[text_color_key][1]

    background_image_path = PROFILE_BACKGROUND_IMAGES.get(background_key)
    if background_image_path is None:
        image = Image.new(
            "RGB",
            (width, height),
            PROFILE_BACKGROUNDS[background_key][1],
        )
    else:
        with Image.open(background_image_path) as background_image:
            background = background_image.convert("RGB")
            if background_key == "eevee":
                background = background.transpose(Image.Transpose.ROTATE_90)
                image = background.resize(
                    (width, height),
                    Image.Resampling.LANCZOS,
                )
            else:
                image = ImageOps.fit(background, (width, height))
        image = image.filter(ImageFilter.GaussianBlur(radius=12))
    background_dye = (dyes or {}).get("background")
    if background_dye is not None:
        image = apply_background_dye(image, background_dye)
    draw = ImageDraw.Draw(image)
    middle_background_image_path = PROFILE_MIDDLE_BACKGROUND_IMAGES.get(
        middle_key
    )
    if middle_background_image_path is None:
        draw.rectangle(
            (430, 0, 949, height - 1),
            fill=PROFILE_MIDDLE_BACKGROUNDS[middle_key][1],
        )
    else:
        with Image.open(middle_background_image_path) as middle_background_image:
            middle_background = ImageOps.fit(
                middle_background_image.convert("RGB"),
                (520, height),
            )
        middle_background = Image.blend(
            middle_background,
            Image.new(
                "RGB",
                middle_background.size,
                profile_background_tint(image),
            ),
            0.4,
        )
        image.paste(middle_background, (430, 0))
    heading_font = profile_font(36, bold=True)
    stat_font = profile_font(30)
    if username is not None:
        if avatar is not None:
            try:
                with Image.open(BytesIO(avatar)) as source:
                    avatar_image = ImageOps.fit(source.convert("RGB"), (110, 110))
                mask = Image.new("L", (110, 110), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, 109, 109), fill=255)
                image.paste(avatar_image, (64, 55), mask)
            except OSError:
                logger.warning("Could not render profile avatar", exc_info=True)
        username_font = profile_font(25, bold=True)
        display_name = username
        while display_name and draw.textlength(display_name, font=username_font) > 225:
            display_name = display_name[:-1]
        if display_name != username:
            display_name = display_name[: max(0, len(display_name) - 1)] + "…"
        draw.text((190, 80), display_name, font=username_font, fill=text_color)
        draw.text((64, 185), f"Level {level}", font=profile_font(25, bold=True), fill=text_color)
    draw.text((64, 245), "Pokemon Catches", font=heading_font, fill=text_color)
    rows = (
        ("Total", "total", None),
        ("Shiny", "shiny", "shiny"),
        ("Low IV", "low_iv", "low_iv"),
        ("High IV", "high_iv", "high_iv"),
        ("Gmax", "gmax", "gmax"),
        ("Missingno", "missingno", "missingno"),
    )
    for index, (label, stat, icon) in enumerate(rows):
        y = 310 + index * 50
        text_x = 110 if icon is not None else 64
        if icon is not None:
            draw_profile_stat_icon(
                image,
                draw,
                icon,
                (64, y - 2),
                emoji_assets or {},
            )
        draw.text(
            (text_x, y),
            f"{label}: {stats[stat]:,}",
            font=stat_font,
            fill=text_color,
        )

    record_label_font = profile_font(27, bold=True)
    record_value_font = profile_font(18)
    for index, (record_name, (label, icon)) in enumerate(
        PROFILE_RECORD_LABELS.items()
    ):
        y = 245 + index * 135
        draw_profile_stat_icon(
            image,
            draw,
            icon,
            (980, y - 2),
            emoji_assets or {},
        )
        draw.text(
            (1025, y),
            f"{label}:",
            font=record_label_font,
            fill=text_color,
        )
        record = (records or {}).get(record_name)
        if record is None:
            draw.text(
                (1025, y + 42),
                "None yet",
                font=record_value_font,
                fill=text_color,
            )
        else:
            pokemon_line, details_line = format_profile_iv_record(record)
            draw.text(
                (1025, y + 42),
                pokemon_line,
                font=record_value_font,
                fill=text_color,
            )
            draw.text(
                (1025, y + 64),
                details_line,
                font=record_value_font,
                fill=text_color,
            )
    box_shiny_y = 735 if settings["frame"] == "pink_ninetales" else 760
    draw_profile_stat_icon(
        image,
        draw,
        "shiny",
        (980, box_shiny_y - 2),
        emoji_assets or {},
    )
    draw.text(
        (1025, box_shiny_y),
        f"Box Shiny: {stats.get('box_shiny', 0):,}",
        font=record_label_font,
        fill=text_color,
    )

    frame_key = str(settings["frame"])
    frame_image_path = PROFILE_FRAME_IMAGES.get(frame_key)
    if frame_image_path is not None:
        profile_opening_size: tuple[int, int] | None = None
        with Image.open(frame_image_path) as frame_image:
            opening = PROFILE_FRAME_OPENINGS.get(frame_key)
            if opening is None:
                scale = PROFILE_FRAME_SCALES[frame_key]
                frame_size = (
                    round(PROFILE_FRAME_CANVAS_SIZE[0] * scale),
                    round(PROFILE_FRAME_CANVAS_SIZE[1] * scale),
                )
                frame = frame_image.convert("RGBA").resize(
                    frame_size,
                    Image.Resampling.LANCZOS,
                )
                profile_position = (
                    (frame.width - width) // 2,
                    (frame.height - height) // 2,
                )
            elif frame_key in {"celestial", "ocean"}:
                left, top, right, bottom = opening
                frame_scale = width / (right - left)
                frame = frame_image.convert("RGBA").resize(
                    (
                        round(frame_image.width * frame_scale),
                        round(frame_image.height * frame_scale),
                    ),
                    Image.Resampling.LANCZOS,
                )
                profile_position = (
                    round(left * frame_scale),
                    round(top * frame_scale),
                )
            elif frame_key == "amethyst":
                left, top, right, bottom = opening
                frame_scale = min(
                    width / (right - left),
                    height / (bottom - top),
                )
                frame = frame_image.convert("RGBA").resize(
                    (
                        round(frame_image.width * frame_scale),
                        round(frame_image.height * frame_scale),
                    ),
                    Image.Resampling.LANCZOS,
                )
                opening_width = round((right - left) * frame_scale)
                opening_height = round((bottom - top) * frame_scale)
                profile_position = (
                    round(left * frame_scale),
                    round(top * frame_scale),
                )
                profile_opening_size = (opening_width, opening_height)
            else:
                left, top, right, bottom = opening
                scale_x = width / (right - left)
                scale_y = height / (bottom - top)
                frame = frame_image.convert("RGBA").resize(
                    (
                        round(frame_image.width * scale_x),
                        round(frame_image.height * scale_y),
                    ),
                    Image.Resampling.LANCZOS,
                )
                profile_position = (
                    round(left * scale_x),
                    round(top * scale_y),
                )
        alpha_lut = [
            round(255 * (alpha / 255) ** PROFILE_FRAME_ALPHA_GAMMA)
            for alpha in range(256)
        ]
        if frame_key not in {"celestial", "ocean"}:
            frame.putalpha(frame.getchannel("A").point(alpha_lut))
        frame_dye = (dyes or {}).get("frame")
        if frame_dye is not None:
            alpha = frame.getchannel("A")
            colored = ImageChops.multiply(
                dye_gradient(frame.size, frame_dye),
                ImageOps.grayscale(frame).convert("RGB"),
            ).convert("RGBA")
            colored.putalpha(alpha)
            if frame_dye["rarity"] != "normal":
                add_dye_sparkles(colored, frame_dye, 28, alpha)
            frame = colored
            if frame_dye["rarity"] == "glow":
                glow = Image.new("RGBA", frame.size, dye_glow_color(frame_dye))
                glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(16)).point(lambda value: min(255, value * 3 // 4)))
                glow.alpha_composite(frame)
                frame = glow
        framed_image = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        if frame_key in {"celestial", "ocean"}:
            profile_card = image.convert("RGBA")
            card_position = profile_position
        elif profile_opening_size is not None:
            profile_card = image.convert("RGBA").resize(
                profile_opening_size,
                Image.Resampling.LANCZOS,
            )
            card_position = profile_position
        else:
            profile_scale = PROFILE_CARD_SCALES[frame_key]
            profile_card = image.convert("RGBA").resize(
                (round(width * profile_scale), round(height * profile_scale)),
                Image.Resampling.LANCZOS,
            )
            card_mask = Image.new("L", profile_card.size, 0)
            ImageDraw.Draw(card_mask).rounded_rectangle(
                (0, 0, profile_card.width - 1, profile_card.height - 1),
                radius=round(PROFILE_FRAME_CORNER_RADIUS * profile_scale),
                fill=255,
            )
            profile_card.putalpha(card_mask)
            card_position = (
                profile_position[0] - (profile_card.width - width) // 2,
                profile_position[1] - (profile_card.height - height) // 2,
            )
        framed_image.alpha_composite(profile_card, dest=card_position)
        framed_image.alpha_composite(frame)
        image = framed_image

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


PROFILE_SHOP_CATEGORIES: Final[dict[str, str]] = {
    "frame": "Frames",
    "background": "Backgrounds",
    "middle_background": "Middle backgrounds",
}


def profile_asset_display(asset_id: str) -> str:
    setting, separator, key = asset_id.partition(":")
    if not separator:
        return asset_id
    choice = PROFILE_SETTING_CHOICES.get(setting, {}).get(key)
    return choice[0] if choice is not None else key.replace("_", " ").title()


def profile_currency_icon_files() -> list[discord.File]:
    if not PROFILE_SHOP_CURRENCY_ICON.is_file():
        return []
    return [
        discord.File(
            PROFILE_SHOP_CURRENCY_ICON,
            filename=PROFILE_SHOP_CURRENCY_ICON_FILENAME,
        )
    ]


def set_profile_inventory_balance(embed: discord.Embed, amount: int) -> None:
    balance_line = f"{amount:,} {PROFILE_SHOP_CURRENCY}"
    existing_description = embed.description or ""
    if PROFILE_SHOP_CURRENCY_ICON.is_file():
        embed.set_author(
            name=balance_line,
            icon_url=f"attachment://{PROFILE_SHOP_CURRENCY_ICON_FILENAME}",
        )
        embed.description = existing_description
    else:
        embed.description = (
            f"{balance_line}\n\n{existing_description}"
            if existing_description
            else balance_line
        )


class ProfileShopCategoryButton(discord.ui.Button):
    def __init__(self, shop_view: "ProfileShopView", setting: str, row: int) -> None:
        super().__init__(
            label=PROFILE_SHOP_CATEGORIES[setting],
            style=discord.ButtonStyle.primary,
            custom_id=f"profile_shop:category:{setting}",
            row=row,
        )
        self.shop_view = shop_view
        self.setting = setting

    async def callback(self, interaction: discord.Interaction) -> None:
        self.shop_view.category = self.setting
        self.shop_view.page = 0
        self.shop_view.refresh()
        await interaction.response.edit_message(
            embed=self.shop_view.embed,
            view=self.shop_view,
        )


class ProfileShopPageButton(discord.ui.Button):
    def __init__(self, shop_view: "ProfileShopView", direction: int) -> None:
        super().__init__(
            label="Previous" if direction < 0 else "Next",
            style=discord.ButtonStyle.secondary,
            custom_id=f"profile_shop:page:{'previous' if direction < 0 else 'next'}",
            row=1,
        )
        self.shop_view = shop_view
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        self.shop_view.page += self.direction
        self.shop_view.refresh()
        await interaction.response.edit_message(
            embed=self.shop_view.embed,
            view=self.shop_view,
        )


class ProfileShopView(discord.ui.View):
    def __init__(self, bot: "NamingBot", user_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.category: str | None = None
        self.page = 0
        self.message: discord.Message | None = None
        for setting in ("frame", "background", "middle_background"):
            self.add_item(ProfileShopCategoryButton(self, setting, 0))
        self.add_item(ProfileShopPageButton(self, -1))
        self.add_item(ProfileShopPageButton(self, 1))
        self.refresh()

    def refresh(self) -> None:
        embed = discord.Embed(title="Profile Shop", color=discord.Color.gold())
        if self.category is None:
            embed.description = "Choose frames, backgrounds, or middle backgrounds."
            self.embed = embed
            self._update_page_buttons(1)
            return

        items = sorted(
            (
                (asset_id, item)
                for asset_id, item in self.bot.profile_shop.items()
                if item["type"] == self.category
            ),
            key=lambda entry: profile_asset_display(entry[0]).casefold(),
        )
        page_count = max(
            1,
            (len(items) + PROFILE_SHOP_PAGE_SIZE - 1) // PROFILE_SHOP_PAGE_SIZE,
        )
        self.page = min(max(self.page, 0), page_count - 1)
        page_items = items[
            self.page * PROFILE_SHOP_PAGE_SIZE :
            (self.page + 1) * PROFILE_SHOP_PAGE_SIZE
        ]
        if not page_items:
            embed.description = f"No {PROFILE_SHOP_CATEGORIES[self.category].lower()} are in the shop yet."
        else:
            lines = []
            for asset_id, item in page_items:
                name = profile_asset_display(asset_id)
                price = int(item["price"])
                currency = str(item["currency"])
                category = str(item["type"]).replace("_", " ")
                lines.append(
                    f"**{name}** ({price:,} {currency})\n"
                    f"`v!buy {category} {name}` | "
                    f"`v!shop preview {category} {name}`"
                )
            embed.description = "\n\n".join(lines)
        embed.set_footer(text=f"Page {self.page + 1} of {page_count}")
        self.embed = embed
        self._update_page_buttons(page_count)

    def _update_page_buttons(self, page_count: int) -> None:
        for child in self.children:
            if isinstance(child, ProfileShopPageButton):
                child.disabled = (
                    page_count <= 1
                    or (child.direction < 0 and self.page == 0)
                    or (child.direction > 0 and self.page >= page_count - 1)
                )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the member who opened this shop can use its buttons.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.warning("Could not disable expired profile shop buttons")


class ProfileInventoryView(discord.ui.View):
    def __init__(self, bot: "NamingBot", user_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.page = 0
        self.entries = self._entries()
        self.embed = discord.Embed(title="Inventory", color=discord.Color.gold())
        self.previous_button = discord.ui.Button(
            label="Previous", style=discord.ButtonStyle.secondary, row=0, disabled=True
        )
        self.next_button = discord.ui.Button(
            label="Next", style=discord.ButtonStyle.secondary, row=0
        )
        self.previous_button.callback = self.previous_page
        self.next_button.callback = self.next_page
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
        self.refresh()

    def _entries(self) -> list[str]:
        entries: list[str] = []
        inventory = self.bot.profile_inventory.get(str(self.user_id), {})
        assets = sorted(
            inventory.get("assets", []),
            key=lambda asset: profile_asset_display(
                profile_asset_id(str(asset["type"]), str(asset["key"]))
            ).casefold(),
        )
        entries.extend(
            f"{asset['code']} - {profile_asset_display(profile_asset_id(asset['type'], asset['key']))}"
            for asset in assets
        )
        return entries

    def refresh(self) -> None:
        page_count = max(
            1,
            (len(self.entries) + PROFILE_SHOP_PAGE_SIZE - 1)
            // PROFILE_SHOP_PAGE_SIZE,
        )
        start = self.page * PROFILE_SHOP_PAGE_SIZE
        page_entries = self.entries[start : start + PROFILE_SHOP_PAGE_SIZE]
        self.embed.description = "\n".join(page_entries) or "Your inventory is empty."
        balance = self.bot.profile_balances_for_user(self.user_id).get(
            PROFILE_SHOP_CURRENCY,
            0,
        )
        set_profile_inventory_balance(self.embed, balance)
        self.embed.set_footer(
            text=f"Showing items {start + 1}-{start + len(page_entries)} of {len(self.entries)}"
        )
        self.previous_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= page_count - 1

    async def previous_page(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self.refresh()
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def next_page(self, interaction: discord.Interaction) -> None:
        page_count = max(
            1,
            (len(self.entries) + PROFILE_SHOP_PAGE_SIZE - 1)
            // PROFILE_SHOP_PAGE_SIZE,
        )
        self.page = min(page_count - 1, self.page + 1)
        self.refresh()
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the member who opened this inventory can use its buttons.",
                ephemeral=True,
            )
            return False
        return True


class ProfilePurchaseView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        user_id: int,
        asset_id: str,
        item: dict[str, str | int],
    ) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.asset_id = asset_id
        self.item = item
        self.completed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the member who started this purchase can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.completed:
            await interaction.response.send_message(
                "This purchase has already been completed.", ephemeral=True
            )
            return
        try:
            name = self.bot.buy_profile_asset(self.user_id, self.asset_id)
        except ValueError as error:
            self.completed = True
            await interaction.response.edit_message(
                content=str(error), embed=None, view=None
            )
            return
        self.completed = True
        await interaction.response.edit_message(
            content=(
                f"Purchased **{name}** and equipped it on your profile. "
                "Find this copy's unique code in `v!inv`."
            ),
            embed=None,
            view=None,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.completed = True
        await interaction.response.edit_message(
            content="Purchase cancelled.", embed=None, view=None
        )


class ProfileEditSelect(discord.ui.Select):
    def __init__(
        self,
        profile_view: "ProfileView",
        setting: str,
        row: int,
    ) -> None:
        self.profile_view = profile_view
        self.setting = setting
        current_value = profile_view.settings_for_display()[setting]
        choices = profile_view.bot.profile_choices_for_user(
            profile_view.user_id,
            setting,
        )
        super().__init__(
            placeholder=PROFILE_SETTING_LABELS[setting],
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    description=description,
                    default=value == current_value,
                )
                for value, (label, description) in choices.items()
            ],
            min_values=1,
            max_values=1,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.profile_view.can_edit(interaction.user.id):
            await interaction.response.send_message(
                (
                    "Only the bot owner who opened this preview can edit it."
                    if self.profile_view.preview_settings is not None
                    else "Only the member who opened this profile can edit it."
                ),
                ephemeral=True,
            )
            return
        try:
            if self.profile_view.preview_settings is not None:
                choices = self.profile_view.bot.profile_choices_for_user(
                    self.profile_view.user_id,
                    self.setting,
                )
                if self.values[0] not in choices:
                    raise ValueError(f"Invalid profile setting: {self.setting}")
                self.profile_view.preview_settings[self.setting] = self.values[0]
            else:
                self.profile_view.bot.set_profile_setting(
                    self.profile_view.user_id,
                    self.setting,
                    self.values[0],
                )
        except ValueError:
            logger.exception(
                "Could not update profile settings for user %s",
                self.profile_view.user_id,
            )
            await interaction.response.send_message(
                (
                    "I couldn't update the profile preview. Check the bot logs."
                    if self.profile_view.preview_settings is not None
                    else "I couldn't save your profile settings. Check the bot logs."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            await self.profile_view.refresh()
            if interaction.message is None:
                logger.warning(
                    "Could not update profile display for user %s: "
                    "interaction message is unavailable",
                    self.profile_view.user_id,
                )
                await interaction.followup.send(
                    "Your setting was saved, but I couldn't refresh the profile display.",
                    ephemeral=True,
                )
                return
            await interaction.message.edit(
                view=ProfileEditView(self.profile_view)
            )
        except discord.HTTPException:
            logger.exception(
                "Could not update profile display for user %s",
                self.profile_view.user_id,
            )
            await interaction.followup.send(
                (
                    "Your preview changed, but I couldn't refresh the profile image."
                    if self.profile_view.preview_settings is not None
                    else "Your setting was saved, but I couldn't refresh the profile image."
                ),
                ephemeral=True,
            )


async def send_profile_music_dm(interaction: discord.Interaction) -> bool:
    """DM the user the song as an audio file, which persists."""
    try:
        audio = await asyncio.to_thread(PROFILE_MUSIC_FILE.read_bytes)
        dm_channel = await interaction.user.create_dm()
    except (OSError, discord.HTTPException):
        logger.exception("Could not prepare the profile music DM")
        return False
    form = aiohttp.FormData()
    form.add_field(
        "files[0]",
        audio,
        filename="return_to_me.ogg",
        content_type="audio/ogg",
    )
    url = f"https://discord.com/api/v10/channels/{dm_channel.id}/messages"
    headers = {"Authorization": f"Bot {interaction.client.http.token}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, headers=headers) as response:
                if response.status < 300:
                    return True
                logger.warning(
                    "Discord rejected the profile music DM (%s): %s",
                    response.status,
                    (await response.text())[:300],
                )
    except aiohttp.ClientError:
        logger.exception("Could not send the profile music DM")
    return False


class ProfileMusicSelect(discord.ui.Select):
    def __init__(self, profile_view: "ProfileView", row: int) -> None:
        self.profile_view = profile_view
        super().__init__(
            placeholder="Music",
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    description=description,
                )
                for value, (label, description, _) in (
                    PROFILE_RETURN_TO_ME.items()
                )
            ],
            min_values=1,
            max_values=1,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        track = PROFILE_RETURN_TO_ME.get(self.values[0])
        if interaction.user.id != self.profile_view.user_id or track is None:
            await interaction.response.send_message(
                "Only the owner of this profile can play its music.",
                ephemeral=True,
            )
            return
        _, _, path = track
        launched = False
        try:
            await interaction.response.launch_activity()
            launched = True
        except discord.HTTPException as error:
            logger.warning(
                "Could not launch the music Activity (HTTP %s, code %s): %s",
                error.status,
                error.code,
                error.text,
            )
        if not launched:
            await self._send_fallback_music(interaction, path)
        try:
            view = ProfileEditView(self.profile_view)
            if launched and interaction.message is not None:
                # Launching an Activity creates no interaction response to edit.
                await interaction.message.edit(view=view)
            else:
                await interaction.edit_original_response(view=view)
        except discord.HTTPException:
            logger.warning("Could not reset the profile music selector", exc_info=True)

    async def _send_fallback_music(
        self,
        interaction: discord.Interaction,
        path: Path,
    ) -> None:
        # The DM uses the bot token, so it still works if the interaction expired.
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            logger.warning("Music interaction already expired", exc_info=True)
        if await send_profile_music_dm(interaction):
            return
        try:
            await interaction.followup.send(
                "I couldn't DM you, so here is the song as a file. "
                "Open your DMs from server members to get the audio.",
                file=discord.File(path, filename=path.name),
                ephemeral=True,
            )
        except (OSError, discord.HTTPException):
            logger.warning("Could not send profile music %s", path, exc_info=True)


class ProfileEditView(discord.ui.View):
    def __init__(self, profile_view: "ProfileView") -> None:
        super().__init__(timeout=300)
        for row, setting in enumerate(PROFILE_SETTING_LABELS):
            self.add_item(ProfileEditSelect(profile_view, setting, row))
        if profile_view.preview_settings is None:
            self.add_item(
                ProfileMusicSelect(profile_view, len(PROFILE_SETTING_LABELS))
            )


class ProfileEditButton(discord.ui.Button):
    def __init__(self, profile_view: "ProfileView") -> None:
        super().__init__(
            label="Edit",
            style=discord.ButtonStyle.secondary,
            custom_id="profile:edit",
        )
        self.profile_view = profile_view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.profile_view.can_edit(interaction.user.id):
            await interaction.response.send_message(
                (
                    "Only the bot owner who opened this preview can edit it."
                    if self.profile_view.preview_settings is not None
                    else "Only the member who opened this profile can edit it."
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            (
                "Choose appearance settings to preview. Changes won't be saved."
                if self.profile_view.preview_settings is not None
                else "Choose your profile colors and appearance."
            ),
            view=ProfileEditView(self.profile_view),
            ephemeral=self.profile_view.preview_settings is not None,
        )


class ProfileView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        user_id: int,
        guild_id: int,
        *,
        preview_owner_id: int | None = None,
        username: str | None = None,
        avatar: bytes | None = None,
    ) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.preview_owner_id = preview_owner_id
        self.username = username
        self.avatar = avatar
        self.preview_settings = (
            dict(bot.profile_settings_for_user(user_id))
            if preview_owner_id is not None
            else None
        )
        self.message: discord.Message | None = None
        self.add_item(ProfileEditButton(self))

    def settings_for_display(self) -> dict[str, int | str]:
        if self.preview_settings is not None:
            return self.preview_settings
        return self.bot.profile_settings_for_user(self.user_id)

    async def can_edit(self, user_id: int) -> bool:
        if self.preview_settings is None:
            return user_id == self.user_id
        return (
            user_id == self.preview_owner_id
            and await self.bot.is_application_owner(user_id)
        )

    async def refresh(self) -> None:
        if self.message is None:
            return
        settings = self.settings_for_display()
        stats = self.bot.profile_stats_for_user(self.guild_id, self.user_id)
        records = self.bot.profile_records_for_user(self.guild_id, self.user_id)
        emoji_assets = await self.bot.load_profile_emoji_assets()
        await self.message.edit(
            attachments=[
                discord.File(
                    render_profile_image(
                        settings,
                        stats,
                        emoji_assets,
                        records,
                        username=self.username,
                        avatar=self.avatar,
                        level=self.bot.pokeball_drops.level(self.user_id),
                        dyes=self.bot.pokeball_drops.appearance(self.user_id, settings),
                    ),
                    filename="profile.png",
                )
            ],
            view=self,
        )


def bingo_display_name(message: discord.Message, user_id: int) -> str:
    # Plain text instead of <@id> so Discord shows no mention highlight.
    guild = getattr(message, "guild", None)
    member = guild.get_member(user_id) if guild is not None else None
    name = getattr(member, "display_name", None)
    if not isinstance(name, str) or not name:
        return "Trainer"
    return discord.utils.escape_markdown(discord.utils.escape_mentions(name))


class NamingBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        # Only jishaku uses the commands framework; on_message routes just its commands.
        super().__init__(command_prefix="v!", intents=intents, help_command=None)
        self.config = config
        self.time_tasks: dict[int, asyncio.Task] = {}
        self.openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=config.openai_api_key, max_retries=1, timeout=10.0)
            if config.openai_api_key
            else None
        )
        self.vision_capacity_condition = asyncio.Condition()
        self.active_vision_requests_by_guild: dict[int, int] = {}
        self.premium_servers_path = Path(
            os.environ.get("PREMIUM_SERVERS_FILE", str(data_path("premium_servers.json")))
        )
        self.premium_servers = load_premium_servers(self.premium_servers_path)
        self.application_owner_ids: set[int] | None = None
        self.image_http: aiohttp.ClientSession | None = None
        image_bank_file = os.environ.get("IMAGE_BANK_FILE")
        self.image_matcher = ImageMatcher(
            Path(image_bank_file)
            if image_bank_file
            else Path(__file__).with_name("image_bank.npz")
        )
        self.image_corrections_path = Path(
            os.environ.get(
                "POKEMON_CORRECTIONS_FILE", str(data_path("pokemon_corrections.csv"))
            )
        )
        self.image_matcher.corrected_references.update(
            load_image_corrections(self.image_corrections_path)
        )
        self.handled_spawn_ids: dict[int, None] = {}
        self.handled_catch_ids: dict[int, None] = {}
        self.handled_bingo_reward_ids: dict[int, None] = {}
        self.bingo_reward_in_progress: set[int] = set()
        self.muted_poketwo_channels: set[int] = set()
        self.incense_path = Path(
            os.environ.get("INCENSE_TRACKING_FILE", str(data_path("incenses.json")))
        )
        self.active_incenses = self.load_active_incenses()
        self.auto_pause_incense_settings_path = Path(
            os.environ.get(
                "AUTO_PAUSE_INCENSE_SETTINGS_FILE",
                str(data_path("auto_pause_incense_settings.json")),
            )
        )
        self.auto_pause_incense_settings = load_auto_pause_incense_settings(
            self.auto_pause_incense_settings_path
        )
        self.pokemon_named_count = 0
        self.failed_recognition_count = 0
        self.active_vision_requests = 0
        self.pending_vision_requests = 0
        self.recognition_durations: deque[tuple[float, float, float]] = deque(
            maxlen=1000
        )
        self.org_runner: web.AppRunner | None = None
        self.activity_runner: web.AppRunner | None = None
        self.org_reserves: OrgReserves | None = None
        self.org_rpc: org_rpc.OrgRpc | None = None
        self.reserve_path = Path(os.environ.get("RESERVES_FILE", str(data_path("reserves.json"))))
        self.reservations = load_reservations(self.reserve_path)
        self.reserve_categories_path = Path(
            os.environ.get(
                "RESERVE_CATEGORIES_FILE",
                str(data_path("reserve_categories.json")),
            )
        )
        self.reserve_categories = load_reserve_categories(
            self.reserve_categories_path
        )
        self.shinyhunt_path = Path(
            os.environ.get("SHINYHUNTS_FILE", str(data_path("shinyhunts.json")))
        )
        pg_store.register(self.shinyhunt_path, "shiny_hunts")
        self.shinyhunters = load_reservations(self.shinyhunt_path)
        self.collection_path = Path(
            os.environ.get("COLLECTIONS_FILE", str(data_path("collections.json")))
        )
        pg_store.register(self.collection_path, "collections")
        self.collections = migrate_legacy_all_keys(
            load_reservations(self.collection_path)
        )
        self.type_ping_path = Path(
            os.environ.get("TYPE_PINGS_FILE", str(data_path("type_pings.json")))
        )
        self.type_pings = load_type_pings(self.type_ping_path)
        self.server_settings_path = Path(
            os.environ.get("SERVER_SETTINGS_FILE", str(data_path("server_settings.json")))
        )
        self.server_settings = load_server_settings(self.server_settings_path)
        self.command_permissions_path = Path(
            os.environ.get("COMMAND_PERMISSIONS_FILE", str(data_path("command_permissions.json")))
        )
        self.command_permissions = load_command_permissions(
            self.command_permissions_path
        )
        self.command_locks_path = Path(
            os.environ.get("COMMAND_LOCKS_FILE", str(data_path("command_locks.json")))
        )
        self.command_locks = load_command_locks(self.command_locks_path)
        self.starboard_settings_path = Path(
            os.environ.get("STARBOARD_SETTINGS_FILE", str(data_path("starboard_settings.json")))
        )
        self.starboard_settings = load_starboard_settings(
            self.starboard_settings_path
        )
        self.afk_settings_path = Path(
            os.environ.get("AFK_SETTINGS_FILE", str(data_path("afk_settings.json")))
        )
        self.afk_settings = load_afk_settings(self.afk_settings_path)
        self.profile_data_path = Path(
            os.environ.get("PROFILE_DATA_FILE", str(data_path("profile_data.json")))
        )
        (
            self.profiles,
            self.profile_stats,
            self.profile_records,
            self.profile_seen_catch_ids,
        ) = load_profile_data(
            self.profile_data_path
        )
        self.profile_shop_path = Path(
            os.environ.get("PROFILE_SHOP_FILE", str(data_path("profile_shop.json")))
        )
        self.profile_shop = load_profile_shop(self.profile_shop_path)
        self.profile_inventory_path = Path(
            os.environ.get(
                "PROFILE_INVENTORY_FILE",
                str(data_path("profile_inventory.json")),
            )
        )
        self.profile_inventory = load_profile_inventory(
            self.profile_inventory_path,
            self.profiles,
        )
        self.pokeball_drops = PokeballDrops(
            self,
            Path(os.environ.get("POKEBALL_DATA_FILE", str(data_path("pokeball_drops.json")))),
            Path(os.environ.get("DYE_CATALOG_FILE", str(data_path("dyes.json")))),
            save_profile_inventory,
        )
        self.profile_backfills_in_progress: set[int] = set()
        self.profile_backfill_stop_requests: set[int] = set()
        self.profile_emoji_cache: dict[str, bytes] | None = None
        self.appearance_path = Path(
            os.environ.get("APPEARANCE_FILE", str(data_path("appearance.json")))
        )
        self.appearance = load_appearance(self.appearance_path)
        self.low_accuracy_path = Path(
            os.environ.get("LOW_ACCURACY_FILE", str(data_path("low_accuracy.json")))
        )
        self.pokemon_confidence_path = Path(__file__).with_name(
            "pokemon_confidence.csv"
        )
        self.pokemon_confidence_review_dir = Path(__file__).with_name(
            "pokemon_confidence_review"
        )
        self.low_accuracy_channels = load_low_accuracy_channels(
            self.low_accuracy_path
        )
        self.chat_events: dict[int, ChatEventSession] = {}
        self.daycare = DaycareFeature(
            Path(os.environ.get("BOXES_FILE", str(data_path("boxes.json")))),
            config.poketwo_bot_id,
        )

    def profile_settings_for_user(self, user_id: int) -> dict[str, int | str]:
        settings = {
            **PROFILE_DEFAULTS,
            **self.profiles.get(str(user_id), {}),
        }
        for owner_id, owner_choices in PROFILE_USER_ONLY_CHOICES.items():
            if user_id != owner_id and user_id not in PROFILE_ALL_ACCESS_USER_IDS:
                for setting, restricted_choices in owner_choices.items():
                    if settings[setting] in restricted_choices:
                        settings[setting] = PROFILE_DEFAULTS[setting]
        return settings

    def profile_assets_for_user(self, user_id: int) -> set[str]:
        inventory = self.profile_inventory.get(str(user_id), {})
        assets = {
            profile_asset_id(str(asset["type"]), str(asset["key"]))
            for asset in inventory.get("assets", [])
        }
        settings = self.profile_settings_for_user(user_id)
        for setting in PROFILE_ASSET_SETTINGS:
            key = settings[setting]
            if key != PROFILE_DEFAULT_ASSETS[setting]:
                assets.add(profile_asset_id(setting, str(key)))
        return assets

    def profile_balances_for_user(self, user_id: int) -> dict[str, int]:
        inventory = self.profile_inventory.get(str(user_id), {})
        return dict(inventory.get("balances", {}))

    def profile_choices_for_user(
        self,
        user_id: int,
        setting: str,
    ) -> dict[str, tuple[str, str]]:
        choices = profile_setting_choices_for_user(user_id, setting)
        owned_assets = self.profile_assets_for_user(user_id)
        for asset_id, item in self.profile_shop.items():
            if item["type"] == setting and asset_id not in owned_assets:
                choices.pop(str(item["key"]), None)
        return choices

    def profile_shop_items_for_query(
        self,
        query: str,
    ) -> list[tuple[str, dict[str, str | int]]]:
        normalized_query = unicodedata.normalize("NFC", query).strip().casefold()
        matches = []
        for asset_id, item in self.profile_shop.items():
            setting = str(item["type"])
            key = str(item["key"])
            label = unicodedata.normalize(
                "NFC", PROFILE_SETTING_CHOICES[setting][key][0]
            ).casefold()
            category = setting.replace("_", " ")
            names = {label, key.casefold()}
            if normalized_query in names or any(
                normalized_query == f"{prefix} {name}"
                for prefix in {category, setting, category.replace(" ", "")}
                for name in names
            ):
                matches.append((asset_id, item))
        return matches

    def buy_profile_asset(self, user_id: int, asset_id: str) -> str:
        item = self.profile_shop.get(asset_id)
        if item is None:
            raise ValueError("That profile asset is no longer available in the shop.")
        setting = str(item["type"])
        key = str(item["key"])
        if key not in profile_setting_choices_for_user(user_id, setting):
            raise ValueError("This profile asset is not available to your account.")

        currency = str(item["currency"])
        price = int(item["price"])
        current_inventory = self.profile_inventory.get(str(user_id), {
            "balances": {},
            "assets": [],
        })
        balances = dict(current_inventory.get("balances", {}))
        balance = balances.get(currency, 0)
        if balance < price:
            raise ValueError(f"You don't have enough {currency}.")

        updated_profiles = {
            profile_user_id: dict(profile)
            for profile_user_id, profile in self.profiles.items()
        }
        updated_profiles.setdefault(str(user_id), dict(PROFILE_DEFAULTS))[setting] = key
        updated_inventory = {
            profile_user_id: {
                "balances": dict(inventory.get("balances", {})),
                "assets": list(inventory.get("assets", [])),
            }
            for profile_user_id, inventory in self.profile_inventory.items()
        }
        user_inventory = updated_inventory.setdefault(
            str(user_id), {"balances": {}, "assets": []}
        )
        user_balances = user_inventory["balances"]
        user_balances[currency] = balance - price
        current_assets = user_inventory["assets"]
        copy_number = 1 + sum(
            1
            for asset in current_assets
            if profile_asset_id(str(asset["type"]), str(asset["key"])) == asset_id
        )
        used_codes = set(profile_asset_codes().values())
        for inventory in updated_inventory.values():
            used_codes.update(asset["code"] for asset in inventory["assets"])
        code = profile_inventory_code(
            str(user_id),
            asset_id,
            copy_number,
            used_codes,
        )
        current_assets.append(profile_inventory_item(asset_id, code))

        previous_drop_data = self.pokeball_drops.select_purchased_copy(user_id, setting, code)
        try:
            save_profile_data(
                self.profile_data_path,
                updated_profiles,
                self.profile_stats,
                self.profile_records,
                self.profile_seen_catch_ids,
            )
            try:
                save_profile_inventory(self.profile_inventory_path, updated_inventory)
            except ValueError:
                try:
                    save_profile_data(
                        self.profile_data_path,
                        self.profiles,
                        self.profile_stats,
                        self.profile_records,
                        self.profile_seen_catch_ids,
                    )
                except ValueError:
                    logger.exception("Could not roll back profile after inventory save failure")
                    raise ValueError(
                        "Purchase failed and the profile could not be rolled back"
                    )
                raise
        except ValueError:
            if previous_drop_data is not None:
                try:
                    self.pokeball_drops.save(previous_drop_data)
                except ValueError:
                    logger.exception("Could not roll back selected profile asset")
                    raise ValueError("Purchase failed and the selected asset could not be rolled back")
            raise

        self.profiles = updated_profiles
        self.profile_inventory = updated_inventory
        return PROFILE_SETTING_CHOICES[setting][key][0]

    def profile_stats_for_user(
        self,
        guild_id: int,
        user_id: int,
    ) -> dict[str, int]:
        return {
            **PROFILE_STAT_DEFAULTS,
            **self.profile_stats.get(f"{guild_id}:{user_id}", {}),
        }

    def profile_records_for_user(
        self,
        guild_id: int,
        user_id: int,
    ) -> dict[str, ProfileIvRecord]:
        return {
            **self.profile_records.get(f"{guild_id}:{user_id}", {})
        }

    async def load_profile_emoji_assets(self) -> dict[str, bytes]:
        if self.profile_emoji_cache is not None:
            return self.profile_emoji_cache
        emoji_assets: dict[str, bytes] = {}
        if self.image_http is not None:
            for name, url in PROFILE_EMOJI_URLS.items():
                try:
                    async with self.image_http.get(url) as response:
                        if response.status != 200:
                            logger.warning(
                                "Could not load profile emoji %s (HTTP %s)",
                                name,
                                response.status,
                            )
                            continue
                        asset = await response.read()
                    with Image.open(BytesIO(asset)) as emoji:
                        emoji.verify()
                    emoji_assets[name] = asset
                except (aiohttp.ClientError, OSError) as error:
                    logger.warning(
                        "Could not load profile emoji %s: %s",
                        name,
                        error,
                    )
        self.profile_emoji_cache = emoji_assets
        return emoji_assets

    def set_profile_setting(self, user_id: int, setting: str, value: str) -> None:
        choices = self.profile_choices_for_user(user_id, setting)
        if choices is None or value not in choices:
            raise ValueError(f"Invalid profile setting: {setting}")
        profiles = {key: dict(profile) for key, profile in self.profiles.items()}
        updated = profiles.setdefault(str(user_id), dict(PROFILE_DEFAULTS))
        updated[setting] = value
        save_profile_data(
            self.profile_data_path,
            profiles,
            self.profile_stats,
            self.profile_records,
            self.profile_seen_catch_ids,
        )
        self.profiles = profiles
        try:
            self.persist_equipped_assets(user_id)
        except ValueError:
            logger.exception(
                "Could not save equipped assets to inventory for user %s",
                user_id,
            )

    def persist_equipped_assets(self, user_id: int) -> None:
        updated_inventory = {
            profile_user_id: {
                "balances": dict(inventory.get("balances", {})),
                "assets": list(inventory.get("assets", [])),
            }
            for profile_user_id, inventory in self.profile_inventory.items()
        }
        user_inventory = updated_inventory.setdefault(
            str(user_id), {"balances": {}, "assets": []}
        )
        owned_asset_ids = {
            profile_asset_id(str(asset["type"]), str(asset["key"]))
            for asset in user_inventory["assets"]
        }
        used_codes = set(profile_asset_codes().values())
        for inventory in updated_inventory.values():
            used_codes.update(asset["code"] for asset in inventory["assets"])
        settings = self.profile_settings_for_user(user_id)
        for setting in PROFILE_ASSET_SETTINGS:
            key = str(settings[setting])
            if key == PROFILE_DEFAULT_ASSETS[setting]:
                continue
            asset_id = profile_asset_id(setting, key)
            if asset_id in owned_asset_ids:
                continue
            copy_number = 1 + sum(
                1
                for asset in user_inventory["assets"]
                if profile_asset_id(str(asset["type"]), str(asset["key"])) == asset_id
            )
            code = profile_inventory_code(
                str(user_id),
                asset_id,
                copy_number,
                used_codes,
            )
            user_inventory["assets"].append(profile_inventory_item(asset_id, code))
            owned_asset_ids.add(asset_id)
        save_profile_inventory(self.profile_inventory_path, updated_inventory)
        self.profile_inventory = updated_inventory

    def track_profile_catch(
        self,
        message: discord.Message,
        *,
        persist: bool = True,
    ) -> None:
        guild = getattr(message, "guild", None)
        message_id = getattr(message, "id", None)
        if (
            guild is None
            or isinstance(message_id, bool)
            or not isinstance(message_id, int)
            or message_id <= 0
        ):
            return
        already_seen = message_id in self.profile_seen_catch_ids
        user_id = profile_catch_user_id(message)
        details = parse_catch_details(
            message_text(message),
            user_id=user_id,
        )
        if details is None:
            details = parse_catch_detection_details(message)
        if user_id is None and details is not None:
            user_id = details.user_id
        if user_id is None:
            return
        if already_seen and (
            details is None or details.iv_value is None
        ):
            return

        profile_stats = {
            key: dict(stats) for key, stats in self.profile_stats.items()
        }
        profile_records: dict[str, dict[str, ProfileIvRecord]] = {
            key: dict(records)
            for key, records in self.profile_records.items()
        }
        user_stats = profile_stats.setdefault(
            f"{guild.id}:{user_id}",
            dict(PROFILE_STAT_DEFAULTS),
        )
        if not already_seen:
            user_stats["total"] += 1
        user_records = profile_records.setdefault(f"{guild.id}:{user_id}", {})
        if details is not None:
            if not already_seen:
                if details.shiny:
                    user_stats["shiny"] += 1
                if details.iv_value is not None and details.iv_value < 10:
                    user_stats["low_iv"] += 1
                if details.iv_value is not None and details.iv_value >= 90:
                    user_stats["high_iv"] += 1
                if details.gigantamax:
                    user_stats["gmax"] += 1
                if details.missingno:
                    user_stats["missingno"] += 1
            if details.iv_value is not None:
                record_candidates = (
                    ("highest_iv", False, True),
                    ("lowest_iv", False, False),
                    ("highest_shiny_iv", True, True),
                    ("lowest_shiny_iv", True, False),
                )
                for record_name, shiny_only, highest in record_candidates:
                    if shiny_only and not details.shiny:
                        continue
                    existing = user_records.get(record_name)
                    if existing is None or (
                        details.iv_value > existing.iv
                        if highest
                        else details.iv_value < existing.iv
                    ):
                        user_records[record_name] = ProfileIvRecord(
                            pokemon=details.pokemon,
                            iv=details.iv_value,
                            level=details.level,
                            gender=details.gender,
                        )
        seen_catch_ids = (
            self.profile_seen_catch_ids
            if already_seen
            else [*self.profile_seen_catch_ids, message_id][-10000:]
        )
        if persist:
            try:
                save_profile_data(
                    self.profile_data_path,
                    self.profiles,
                    profile_stats,
                    profile_records,
                    seen_catch_ids,
                )
            except ValueError:
                logger.exception(
                    "Could not record catch %s for profile user %s",
                    message_id,
                    user_id,
                )
                return
        self.profile_stats = profile_stats
        self.profile_records = profile_records
        self.profile_seen_catch_ids = seen_catch_ids

    async def track_profile_box_shiny(
        self,
        message: discord.Message,
        *,
        persist: bool = True,
    ) -> None:
        guild = getattr(message, "guild", None)
        message_id = getattr(message, "id", None)
        author = getattr(message, "author", None)
        if (
            guild is None
            or getattr(author, "id", None) != self.config.poketwo_bot_id
            or isinstance(message_id, bool)
            or not isinstance(message_id, int)
            or message_id <= 0
        ):
            return
        box_shiny_count = parse_box_shiny_count(message_text(message))
        if box_shiny_count == 0 or message_id in self.profile_seen_catch_ids:
            return

        reference = getattr(message, "reference", None)
        referenced_message = getattr(reference, "resolved", None)
        if referenced_message is None:
            reference_id = getattr(reference, "message_id", None)
            channel = getattr(message, "channel", None)
            if (
                isinstance(reference_id, int)
                and not isinstance(reference_id, bool)
                and isinstance(
                    channel,
                    (discord.TextChannel, discord.Thread, discord.DMChannel),
                )
            ):
                try:
                    referenced_message = await channel.fetch_message(reference_id)
                except discord.HTTPException as error:
                    logger.warning(
                        "Could not read the chest command for message %s: %s",
                        message_id,
                        error,
                    )
        command_author = getattr(referenced_message, "author", None)
        user_id = getattr(command_author, "id", None)
        if (
            isinstance(user_id, bool)
            or not isinstance(user_id, int)
            or getattr(command_author, "bot", False)
        ):
            logger.warning(
                "Could not determine the user for box-shiny message %s",
                message_id,
            )
            return

        profile_stats = {
            key: dict(stats) for key, stats in self.profile_stats.items()
        }
        user_key = f"{guild.id}:{user_id}"
        user_stats = profile_stats.setdefault(
            user_key,
            dict(PROFILE_STAT_DEFAULTS),
        )
        user_stats["box_shiny"] += box_shiny_count
        seen_catch_ids = [*self.profile_seen_catch_ids, message_id][-10000:]
        if persist:
            try:
                save_profile_data(
                    self.profile_data_path,
                    self.profiles,
                    profile_stats,
                    self.profile_records,
                    seen_catch_ids,
                )
            except ValueError:
                logger.exception(
                    "Could not record box-shiny message %s for profile user %s",
                    message_id,
                    user_id,
                )
                return
        self.profile_stats = profile_stats
        self.profile_seen_catch_ids = seen_catch_ids

    def update_appearance(self, guild_id: int, **changes) -> None:
        updated = {key: dict(value) for key, value in self.appearance.items()}
        guild = updated.setdefault(str(guild_id), {})
        for key, value in changes.items():
            if value is None:
                guild.pop(key, None)
            else:
                guild[key] = value
        save_appearance(self.appearance_path, updated)
        self.appearance = updated

    async def reset_appearance(
        self, interaction: discord.Interaction, guild_id: int, action: str
    ) -> None:
        guild = interaction.guild
        member = guild.me if guild is not None else None
        if member is None:
            await interaction.response.send_message(
                "I couldn't find my server member to reset that setting.",
                ephemeral=True,
            )
            return
        field = action.removesuffix("_reset")
        try:
            if field == "avatar":
                await member.edit(avatar=None)
            elif field == "banner":
                await member.edit(banner=None)
            elif field == "name":
                await member.edit(nick=None)
            self.update_appearance(guild_id, **{field: None})
        except (discord.HTTPException, ValueError) as error:
            await interaction.response.send_message(
                f"I couldn't reset that: {error}", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            view=AppearanceSettingsView(self, guild_id)
        )

    async def apply_appearance_image(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        field: str,
        attachment: discord.Attachment,
    ) -> None:
        content_type = (attachment.content_type or "").split(";")[0]
        if (
            content_type not in APPEARANCE_IMAGE_TYPES
            or attachment.size > APPEARANCE_MAX_BYTES
        ):
            await interaction.response.send_message(
                "That file must be a PNG, JPEG, GIF or WEBP image up to 10 MB.",
                ephemeral=True,
            )
            return
        guild = interaction.guild
        member = guild.me if guild is not None else None
        if member is None:
            await interaction.response.send_message(
                "I couldn't find my server member to update the appearance.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            image = await attachment.read()
            if field == "avatar":
                member = await member.edit(avatar=image)
            elif field == "banner":
                member = await member.edit(banner=image)
            else:
                raise ValueError(f"Unknown appearance image field: {field}")
        except (discord.HTTPException, ValueError) as error:
            if "too fast" in str(error):
                message = (
                    "Discord limits how often an avatar or banner can change. "
                    "Wait 10-15 minutes, then upload once more."
                )
            else:
                message = f"Discord rejected the image: {error}"
            await interaction.followup.send(message, ephemeral=True)
            return
        label = "profile image" if field == "avatar" else "server banner"
        applied = member is not None and (
            member.guild_avatar if field == "avatar" else member.guild_banner
        )
        logger.info(
            "Appearance %s edit in guild %s applied=%s", field, guild_id, bool(applied)
        )
        if not applied:
            await interaction.followup.send(
                f"Discord accepted the request but did not apply the {label}. "
                "Make sure the bot is on the latest code and try a different image.",
                ephemeral=True,
            )
            return
        self.update_appearance(guild_id, **{field: True})
        await interaction.followup.send(
            f"Updated the {label}. Reopen Appearance to see it.", ephemeral=True
        )

    def tint_embeds(self, guild: discord.Guild | None, kwargs: dict) -> None:
        if guild is None:
            return
        color = self.appearance.get(str(guild.id), {}).get("color")
        if color is None:
            return
        embeds = list(kwargs.get("embeds") or [])
        if kwargs.get("embed") is not None:
            embeds.append(kwargs["embed"])
        for embed in embeds:
            if embed.color is None or embed.color.value == DEFAULT_EMBED_COLOR:
                embed.color = discord.Color(color)

    def naming_settings_for_guild(self, guild_id: int) -> dict[str, bool]:
        return {
            **SERVER_NAMING_DEFAULTS,
            **self.server_settings.get(str(guild_id), {}),
        }

    def auto_pause_incense_enabled_for_guild(self, guild_id: int) -> bool:
        return self.auto_pause_incense_settings.get(str(guild_id), True)

    def set_auto_pause_incense_enabled(
        self,
        guild_id: int,
        enabled: bool,
    ) -> None:
        if (
            isinstance(guild_id, bool)
            or not isinstance(guild_id, int)
            or guild_id <= 0
        ):
            raise ValueError("An auto-pause setting requires a positive server ID.")
        if not isinstance(enabled, bool):
            raise ValueError("An auto-pause setting must be a boolean.")
        updated_settings = dict(self.auto_pause_incense_settings)
        updated_settings[str(guild_id)] = enabled
        save_auto_pause_incense_settings(
            self.auto_pause_incense_settings_path,
            updated_settings,
        )
        self.auto_pause_incense_settings = updated_settings

    def commands_locked_for_guild(self, guild_id: int) -> bool:
        return self.command_locks.get(str(guild_id), False)

    def set_commands_locked(self, guild_id: int, locked: bool) -> None:
        if (
            isinstance(guild_id, bool)
            or not isinstance(guild_id, int)
            or guild_id <= 0
        ):
            raise ValueError("A command lock requires a positive server ID.")
        if not isinstance(locked, bool):
            raise ValueError("A command lock state must be a boolean.")
        updated_locks = dict(self.command_locks)
        guild_key = str(guild_id)
        if locked:
            updated_locks[guild_key] = True
        else:
            updated_locks.pop(guild_key, None)
        save_command_locks(self.command_locks_path, updated_locks)
        self.command_locks = updated_locks

    def starboard_settings_for_guild(
        self, guild_id: int
    ) -> StarboardSettings:
        settings = {
            **STARBOARD_DEFAULTS,
            **self.starboard_settings.get(str(guild_id), {}),
        }
        def channel_setting(key: str) -> int | None:
            channel_id = settings[key]
            if channel_id is None:
                return None
            if (
                isinstance(channel_id, bool)
                or not isinstance(channel_id, int)
                or channel_id <= 0
            ):
                raise ValueError(
                    f"Invalid starboard channel settings for guild {guild_id}"
                )
            return channel_id

        normal_channel = channel_setting("normal_channel")
        shiny_channel = channel_setting("shiny_channel")
        normal_pokemon_channel = channel_setting("normal_pokemon_channel")
        base_name = settings["shiny_base_name"]
        if base_name is not None and (
            not isinstance(base_name, str) or not base_name.strip()
        ):
            raise ValueError(f"Invalid shinyboard name for guild {guild_id}")
        shiny_count = settings["shiny_count"]
        if (
            isinstance(shiny_count, bool)
            or not isinstance(shiny_count, int)
            or shiny_count < 0
        ):
            raise ValueError(f"Invalid shinyboard count for guild {guild_id}")
        return {
            "normal_channel": normal_channel,
            "shiny_channel": shiny_channel,
            "normal_pokemon_channel": normal_pokemon_channel,
            "shiny_base_name": base_name,
            "shiny_count": shiny_count,
        }

    def set_starboard_channel(
        self,
        guild_id: int,
        board: str,
        channel_id: int | None,
        channel_name: str | None = None,
    ) -> StarboardSettings:
        setting_key = STARBOARD_CHANNEL_SETTING_KEYS.get(board)
        if setting_key is None:
            raise ValueError(f"Unknown starboard: {board}")
        if channel_id is not None and (
            isinstance(channel_id, bool)
            or not isinstance(channel_id, int)
            or channel_id <= 0
        ):
            raise ValueError("A starboard channel ID must be a positive integer.")
        updated_settings = {
            key: dict(settings) for key, settings in self.starboard_settings.items()
        }
        guild_key = str(guild_id)
        guild_settings = self.starboard_settings_for_guild(guild_id)
        previous_channel_id = guild_settings[setting_key]
        guild_settings[setting_key] = channel_id
        if board == "shiny":
            if channel_id is None:
                guild_settings["shiny_base_name"] = None
                guild_settings["shiny_count"] = 0
            elif channel_id != previous_channel_id:
                base_name, initial_count = (
                    split_channel_counter(channel_name)
                    if channel_name
                    else (None, 0)
                )
                guild_settings["shiny_base_name"] = base_name
                guild_settings["shiny_count"] = initial_count
            elif channel_name:
                channel_base_name, current_name_count = split_channel_counter(
                    channel_name
                )
                if guild_settings["shiny_base_name"] is None:
                    guild_settings["shiny_base_name"] = channel_base_name
                if guild_settings["shiny_base_name"] == channel_base_name:
                    guild_settings["shiny_count"] = max(
                        int(guild_settings["shiny_count"]),
                        current_name_count,
                    )
        settings_to_save: dict[str, int | str | None] = {
            "normal_channel": guild_settings["normal_channel"],
            "shiny_channel": guild_settings["shiny_channel"],
            "normal_pokemon_channel": guild_settings["normal_pokemon_channel"],
            "shiny_base_name": guild_settings["shiny_base_name"],
            "shiny_count": guild_settings["shiny_count"],
        }
        updated_settings[guild_key] = settings_to_save
        save_starboard_settings(self.starboard_settings_path, updated_settings)
        self.starboard_settings = updated_settings
        return guild_settings

    def increment_shinyboard_count(
        self,
        guild_id: int,
        channel_name: str | None,
    ) -> str | None:
        updated_settings = {
            key: dict(settings) for key, settings in self.starboard_settings.items()
        }
        guild_key = str(guild_id)
        guild_settings = self.starboard_settings_for_guild(guild_id)
        base_name = guild_settings["shiny_base_name"]
        count = int(guild_settings["shiny_count"])
        if channel_name:
            channel_base_name, current_name_count = split_channel_counter(
                channel_name
            )
            if base_name is None:
                base_name = channel_base_name
            if base_name == channel_base_name:
                count = max(count, current_name_count)
        count += 1
        guild_settings["shiny_base_name"] = base_name
        guild_settings["shiny_count"] = count
        settings_to_save: dict[str, int | str | None] = {
            "normal_channel": guild_settings["normal_channel"],
            "shiny_channel": guild_settings["shiny_channel"],
            "normal_pokemon_channel": guild_settings["normal_pokemon_channel"],
            "shiny_base_name": guild_settings["shiny_base_name"],
            "shiny_count": guild_settings["shiny_count"],
        }
        updated_settings[guild_key] = settings_to_save
        save_starboard_settings(self.starboard_settings_path, updated_settings)
        self.starboard_settings = updated_settings
        if base_name is None:
            return None
        suffix = f"-{count}"
        return f"{base_name[: 100 - len(suffix)]}{suffix}"

    def toggle_naming_setting(self, guild_id: int, setting: str) -> dict[str, bool]:
        if setting not in SERVER_NAMING_SETTING_KEYS:
            raise ValueError(f"Unknown server naming setting: {setting}")
        updated_settings = {
            guild_id: dict(settings)
            for guild_id, settings in self.server_settings.items()
        }
        guild_key = str(guild_id)
        guild_settings = self.naming_settings_for_guild(guild_id)
        guild_settings[setting] = not guild_settings[setting]
        updated_settings[guild_key] = guild_settings
        save_server_settings(self.server_settings_path, updated_settings)
        self.server_settings = updated_settings
        return guild_settings

    def afk_settings_for_user(
        self, guild_id: int, user_id: int
    ) -> dict[str, bool]:
        return {
            **AFK_DEFAULTS,
            **self.afk_settings.get(f"{guild_id}:{user_id}", {}),
        }

    def type_pings_for_user(self, guild_id: int, user_id: int) -> list[str]:
        return list(self.type_pings.get(f"{guild_id}:{user_id}", []))

    def set_type_pings(
        self,
        guild_id: int,
        user_id: int,
        enabled_types: list[str],
    ) -> list[str]:
        if any(type_name not in TYPE_PING_TYPES for type_name in enabled_types):
            raise ValueError("Type ping settings contain an unknown Pokémon type")
        selected_types = [
            type_name
            for type_name in TYPE_PING_TYPES
            if type_name in enabled_types
        ]
        updated_type_pings = dict(self.type_pings)
        user_key = f"{guild_id}:{user_id}"
        if selected_types:
            updated_type_pings[user_key] = selected_types
        else:
            updated_type_pings.pop(user_key, None)
        save_type_pings(self.type_ping_path, updated_type_pings)
        self.type_pings = updated_type_pings
        return selected_types

    def toggle_afk_setting(
        self, guild_id: int, user_id: int, setting: str
    ) -> dict[str, bool]:
        if setting not in AFK_SETTING_KEYS:
            raise ValueError(f"Unknown AFK setting: {setting}")
        updated_settings = {
            key: dict(settings) for key, settings in self.afk_settings.items()
        }
        user_key = f"{guild_id}:{user_id}"
        user_settings = self.afk_settings_for_user(guild_id, user_id)
        user_settings[setting] = not user_settings[setting]
        updated_settings[user_key] = user_settings
        save_afk_settings(self.afk_settings_path, updated_settings)
        self.afk_settings = updated_settings
        return user_settings

    def org_add_reserve(self, name: str, user_id: int) -> None:
        guild_id = int(os.environ["ORG_GUILD_ID"])
        updated = add_reservations_bulk(
            self.reservations, guild_id, [(name, user_id)]
        )
        save_reservations(self.reserve_path, updated)
        self.reservations = updated

    def org_add_category_reserves(self, names: list[str], user_id: int) -> None:
        guild_id = int(os.environ["ORG_GUILD_ID"])
        for name in names:
            key = reservation_key_for_command(guild_id, name)
            existing_users = self.reservations.get(key, [])
            if any(existing_user != user_id for existing_user in existing_users):
                raise OrgError(409, f"{name} is already reserved by another user")
        updated = add_reservations_bulk(
            self.reservations,
            guild_id,
            [(name, user_id) for name in names],
        )
        save_reservations(self.reserve_path, updated)
        self.reservations = updated

    def org_remove_reserve(self, name: str, user_id: int) -> bool:
        guild_id = int(os.environ["ORG_GUILD_ID"])
        updated, removed = remove_reservation(
            self.reservations, guild_id, name, user_id
        )
        if removed:
            save_reservations(self.reserve_path, updated)
            self.reservations = updated
        return removed

    def org_clear_reserves(self, guild_id: int) -> int:
        guild_prefix = f"{guild_id}:"
        cleared = sum(
            len(user_ids)
            for key, user_ids in self.reservations.items()
            if key.startswith(guild_prefix)
        )
        updated = clear_guild_reservations(self.reservations, guild_id)
        if cleared:
            save_reservations(self.reserve_path, updated)
            self.reservations = updated
        return cleared

    def org_store(self, restrictions_path: Path | None = None) -> OrgReserves:
        """The one shared org store, built once and reused by every transport.

        org_api.create_app and the Discord transport both read and write this
        same in-memory list, so org_reserves.json never drifts into two caches.
        """
        if self.org_reserves is None:
            if restrictions_path is None:
                restrictions_path = Path(
                    os.environ.get(
                        "ORG_RESTRICTIONS_FILE",
                        str(data_path("org_restrictions.json")),
                    )
                )
            self.org_reserves = OrgReserves(
                Path(os.environ.get("ORG_RESERVES_FILE", str(data_path("org_reserves.json")))),
                restrictions_path,
                load_known_pokemon_names(),
            )
        return self.org_reserves

    async def start_org_rpc(self) -> None:
        """Start the Discord org transport, or leave it off when unconfigured.

        from_environment returns None when neither ORG_DISCORD_RPC_CHANNEL_ID
        nor ORG_DISCORD_RPC_GUILD_ID is set, so the feature flag is the scope
        itself: on_message stays exactly as it was and nothing is listened for.
        """
        self.org_rpc = org_rpc.from_environment(
            self.org_store(),
            self.org_add_reserve,
            self.org_remove_reserve,
        )

    async def start_org_api(self) -> None:
        api_key = os.environ.get("ORG_BOT_API_KEY", "").strip()
        if not api_key:
            logger.info("Org API is disabled because ORG_BOT_API_KEY is not set")
            return
        try:
            guild_id = int(os.environ["ORG_GUILD_ID"])
        except (KeyError, ValueError):
            logger.error("ORG_GUILD_ID is required for the org API; API disabled")
            return
        restrictions_path = Path(
            os.environ.get(
                "ORG_RESTRICTIONS_FILE",
                str(data_path("org_restrictions.json")),
            )
        )
        if not restrictions_path.is_file():
            logger.warning(
                "Org restrictions file not found at %s; slots will have no restrictions",
                restrictions_path.resolve(),
            )
        org = self.org_store(restrictions_path)
        allowed_lists = [
            rule["allowed"]
            for rule in org.restrictions.values()
            if "allowed" in rule
        ]
        allowed_count = len(allowed_lists[0]) if allowed_lists else 0
        logger.info(
            "Loaded org restrictions from %s (%d slots, %d allowed names)",
            restrictions_path.resolve(),
            len(org.restrictions),
            allowed_count,
        )
        app = create_app(
            api_key,
            org,
            guild_id,
            self.org_add_reserve,
            self.org_remove_reserve,
            lambda: self.reserve_categories,
            self.org_add_category_reserves,
            self.org_clear_reserves,
            matches_all_forms=pokemon_matches_all_forms_reservation,
        )
        port = _org_api_port_from_environment()
        if (
            self.application_id is not None
            and os.environ.get("MUSIC_ACTIVITY_PORT", "").strip() == str(port)
        ):
            # The host exposes a single port, so the Activity shares the Org API.
            add_activity_routes(app, self.application_id)
            logger.info("Music Activity is served on the Org API port %s", port)
        self.org_runner = web.AppRunner(app)
        await self.org_runner.setup()
        try:
            await web.TCPSite(self.org_runner, "0.0.0.0", port).start()
        except OSError:
            logger.exception("Could not bind Org API on 0.0.0.0:%s", port)
            raise
        logger.info("Org API listening on port %s", port)

    async def start_music_activity(self) -> None:
        raw_port = os.environ.get("MUSIC_ACTIVITY_PORT", "").strip()
        if not raw_port:
            logger.info("Music Activity is disabled because MUSIC_ACTIVITY_PORT is not set")
            return
        try:
            port = int(raw_port)
        except ValueError:
            logger.error("MUSIC_ACTIVITY_PORT must be a valid port number")
            return
        if port == _org_api_port_from_environment():
            return
        if self.application_id is None:
            logger.error("Music Activity needs the bot's application ID")
            return
        self.activity_runner = web.AppRunner(create_activity_app(self.application_id))
        await self.activity_runner.setup()
        try:
            await web.TCPSite(self.activity_runner, "0.0.0.0", port).start()
        except OSError:
            logger.exception("Could not bind the Music Activity on port %s", port)
            await self.activity_runner.cleanup()
            self.activity_runner = None
            return
        logger.info("Music Activity listening on port %s", port)

    async def setup_hook(self) -> None:
        try:
            await self.load_extension("jishaku")
        except commands.ExtensionError:
            logger.exception("Could not load jishaku")
        await self.start_org_api()
        await self.start_music_activity()
        await self.start_org_rpc()
        self.image_http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            connector=aiohttp.TCPConnector(limit=0),
            headers={"User-Agent": "Vivillon-naming/1.0"},
        )

    async def close(self) -> None:
        self.pokeball_drops.close()
        for task in self.time_tasks.values():
            task.cancel()
        self.time_tasks.clear()
        if self.org_runner is not None:
            await self.org_runner.cleanup()
        if self.activity_runner is not None:
            await self.activity_runner.cleanup()
        if self.image_http is not None:
            await self.image_http.close()
        if self.openai is not None:
            await self.openai.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def _ping_loop(self, channel, mentions: str, allowed) -> None:
        try:
            while True:
                await asyncio.sleep(180)
                try:
                    await channel.send(mentions, allowed_mentions=allowed)
                except discord.HTTPException as error:
                    logger.warning("v!settime ping failed: %s", error)
        except asyncio.CancelledError:
            pass

    async def handle_settime_command(self, message: discord.Message) -> None:
        roles = message.role_mentions
        users = [user for user in message.mentions if not user.bot]
        if not roles and not users:
            await message.reply(
                "Usage: `v!settime @role [@role ...]`", mention_author=False
            )
            return
        mentions = " ".join([role.mention for role in roles] + [u.mention for u in users])
        allowed = discord.AllowedMentions(roles=list(roles), users=users, everyone=False)
        channel_id = message.channel.id
        old = self.time_tasks.pop(channel_id, None)
        if old is not None:
            old.cancel()
        self.time_tasks[channel_id] = asyncio.create_task(
            self._ping_loop(message.channel, mentions, allowed)
        )
        await message.reply(
            f"✅ Timer set! I'll ping {mentions} every 3 minutes "
            "(first ping in 3 minutes). Use `v!timereset` to stop.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def handle_timereset_command(self, message: discord.Message) -> None:
        task = self.time_tasks.pop(message.channel.id, None)
        if task is None:
            await message.reply("No timer is running.", mention_author=False)
            return
        task.cancel()
        await message.reply(
            "Timer stopped. Use `v!settime` with roles to start again.",
            mention_author=False,
        )

    async def set_poketwo_blocked(self, channel, blocked: bool) -> bool:
        """Deny (or restore) Pokétwo's Send Messages permission in a channel."""
        try:
            guild = channel.guild
            target = guild.get_member(self.config.poketwo_bot_id)
            if target is None:
                target = await guild.fetch_member(self.config.poketwo_bot_id)
            if blocked:
                await channel.set_permissions(
                    target,
                    send_messages=False,
                    reason="Missingno spawned; blocking Pokétwo until v!r",
                )
            else:
                await channel.set_permissions(
                    target, overwrite=None, reason="v!r: restoring Pokétwo"
                )
            return True
        except Exception as error:
            logger.warning("Could not change Pokétwo permissions: %s", error)
            return False

    async def pause_active_incense_channels(
        self,
        guild: discord.Guild,
    ) -> tuple[int, int]:
        self.current_active_incenses()
        paused = 0
        failed = await self.recover_active_incenses_from_history(guild)
        for channel_key, record in list(self.active_incenses.items()):
            if str(record["guild_id"]) != str(guild.id):
                continue
            try:
                channel_id = int(channel_key)
            except ValueError:
                logger.warning(
                    "Could not read active incense channel id %r in guild %s",
                    channel_key,
                    guild.id,
                )
                failed += 1
                continue
            channel = guild.get_channel(channel_id)
            if channel is None:
                channel = guild.get_thread(channel_id)
            if channel is None:
                logger.warning(
                    "Could not find active incense channel %s in guild %s",
                    channel_id,
                    guild.id,
                )
                failed += 1
                continue
            if channel_id in self.muted_poketwo_channels:
                paused += 1
                continue
            if await self.set_poketwo_blocked(channel, True):
                self.muted_poketwo_channels.add(channel_id)
                paused += 1
            else:
                failed += 1
        return paused, failed

    async def recover_active_incenses_from_history(
        self,
        guild: discord.Guild,
    ) -> int:
        now = int(time.time())
        recovered = False
        failed = 0
        for channel in guild.text_channels:
            channel_key = str(channel.id)
            if channel_key in self.active_incenses:
                continue
            try:
                async for message in channel.history(limit=100):
                    action = incense_action_from_message(
                        message,
                        self.config.poketwo_bot_id,
                    )
                    if action is None:
                        continue
                    if action != "stop":
                        expires_at = (
                            int(message.created_at.timestamp())
                            + INCENSE_DURATION_SECONDS
                        )
                        if expires_at > now:
                            self.active_incenses[channel_key] = {
                                "guild": guild.name,
                                "channel": getattr(
                                    channel,
                                    "name",
                                    f"channel-{channel.id}",
                                ),
                                "guild_id": guild.id,
                                "expires_at": expires_at,
                            }
                            recovered = True
                    break
            except (discord.Forbidden, discord.HTTPException) as error:
                logger.warning(
                    "Could not scan recent incense status in channel %s: %s",
                    channel.id,
                    error,
                )
                failed += 1
        if recovered:
            self.save_active_incenses()
        return failed

    async def bingo_user_fallback(
        self, message: discord.Message, source: discord.Message | None
    ) -> int | None:
        # Slash commands, replies to bot messages and mention-only messages have no human reply target.
        def human_id(user: object) -> int | None:
            user_id = getattr(user, "id", None)
            if getattr(user, "bot", False) or not isinstance(user_id, int) or isinstance(user_id, bool):
                return None
            return user_id

        for candidate in (message, source):
            if candidate is None:
                continue
            metadata = getattr(candidate, "interaction_metadata", None)
            interaction = getattr(candidate, "interaction", None)
            for user in (getattr(metadata, "user", None), getattr(interaction, "user", None)):
                if human_id(user) is not None:
                    return human_id(user)
        if source is not None:
            inner = getattr(getattr(source, "reference", None), "resolved", None)
            if human_id(getattr(inner, "author", None)) is not None:
                return human_id(inner.author)
            for user in getattr(source, "mentions", None) or []:
                if human_id(user) is not None:
                    return human_id(user)
        for user in getattr(message, "mentions", None) or []:
            if human_id(user) is not None:
                return human_id(user)
        return None

    async def handle_bingo_reward(self, message: discord.Message) -> None:
        message_id = getattr(message, "id", None)
        if isinstance(message_id, bool) or not isinstance(message_id, int):
            return
        if (
            message_id in self.handled_bingo_reward_ids
            or message_id in self.bingo_reward_in_progress
        ):
            return

        content = message_text(message)
        if re.search(r"\byour card is a blackout\b", content, re.IGNORECASE):
            reward = BINGO_BLACKOUT_REWARD
        elif re.search(r"\byou completed bingo quest\b", content, re.IGNORECASE):
            reward = BINGO_QUEST_REWARD
        else:
            return

        self.bingo_reward_in_progress.add(message_id)
        try:
            reference = getattr(message, "reference", None)
            source = getattr(reference, "resolved", None)
            source_author = getattr(source, "author", None)
            user_id = (
                None
                if getattr(source_author, "bot", False)
                else getattr(source_author, "id", None)
            )
            if not isinstance(user_id, int) or isinstance(user_id, bool):
                source_message_id = getattr(reference, "message_id", None)
                fetch_message = getattr(message.channel, "fetch_message", None)
                if (
                    isinstance(source_message_id, int)
                    and not isinstance(source_message_id, bool)
                    and callable(fetch_message)
                ):
                    try:
                        source = await fetch_message(source_message_id)
                    except discord.HTTPException:
                        logger.exception(
                            "Could not resolve the user for bingo message %s",
                            message_id,
                        )
                        return
                    source_author = getattr(source, "author", None)
                    user_id = (
                        None
                        if getattr(source_author, "bot", False)
                        else getattr(source_author, "id", None)
                    )
            if not isinstance(user_id, int) or isinstance(user_id, bool):
                user_id = await self.bingo_user_fallback(message, source)
            if not isinstance(user_id, int) or isinstance(user_id, bool):
                logger.warning(
                    "Skipping bingo reward for message %s: completing user "
                    "could not be resolved (reference=%s, source_author=%s, source_bot=%s)",
                    message_id,
                    getattr(reference, "message_id", None),
                    getattr(source_author, "id", None),
                    getattr(source_author, "bot", None),
                )
                return

            user_key = str(user_id)
            updated_inventory = {
                existing_user_id: {
                    "balances": dict(inventory.get("balances", {})),
                    "assets": list(inventory.get("assets", [])),
                }
                for existing_user_id, inventory in self.profile_inventory.items()
            }
            user_inventory = updated_inventory.setdefault(
                user_key,
                {"balances": {}, "assets": []},
            )
            balances = user_inventory["balances"]
            balances[PROFILE_SHOP_CURRENCY] = (
                balances.get(PROFILE_SHOP_CURRENCY, 0) + reward
            )
            try:
                save_profile_inventory(self.profile_inventory_path, updated_inventory)
            except ValueError:
                logger.exception(
                    "Could not save bingo reward for user %s from message %s",
                    user_id,
                    message_id,
                )
                return

            self.profile_inventory = updated_inventory
            self.handled_bingo_reward_ids[message_id] = None
            while len(self.handled_bingo_reward_ids) > 5000:
                del self.handled_bingo_reward_ids[
                    next(iter(self.handled_bingo_reward_ids))
                ]
            try:
                await message.reply(
                    f"{bingo_display_name(message, user_id)} you completed your bingo and got "
                    f"{reward} pokedollars!",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not announce bingo reward for user %s from message %s",
                    user_id,
                    message_id,
                )
        finally:
            self.bingo_reward_in_progress.discard(message_id)

    async def on_message(self, message: discord.Message) -> None:
        # The org transport runs first, before the bot-author guard below would
        # drop the org bot's own JSON requests, and before channel filtering.
        if self.org_rpc is not None and await self.org_rpc.handle_message(message):
            return
        if (
            not message.author.bot
            and re.match(r"^v!correct(?:\s|$)", message.content, re.IGNORECASE)
        ):
            await self.handle_image_correction(message)
            return
        if re.match(r"^v!(?:jsk|jishaku)(?:\s|$)", message.content, re.IGNORECASE):
            await self.process_commands(message)
            return
        if (
            not message.author.bot
            and re.match(r"^v!premium(?:\s|$)", message.content, re.IGNORECASE)
        ):
            await self.handle_premium_command(message)
            return
        poketwo_catch = message.author.id == self.config.poketwo_bot_id
        if poketwo_catch:
            await self.handle_bingo_reward(message)
        catch_detection_report = has_catch_detection_embed(message)
        parsed_catch_report = (
            is_automated_message(message)
            and not poketwo_catch
            and profile_catch_user_id(message) is not None
        )
        if (
            message.author.bot
            and not poketwo_catch
            and not catch_detection_report
            and not parsed_catch_report
        ):
            return
        if poketwo_catch or catch_detection_report or parsed_catch_report:
            self.track_profile_catch(message)
            await self.track_profile_box_shiny(message)
            await self.handle_catch_starboard(message)
        incense_action = self.track_incense_command(message)
        if incense_action == "buy":
            await self.pause_confirmed_incense_purchase(message)
        if not self.is_allowed_channel(message.channel):
            return
        channel_id = getattr(message.channel, "id", None)
        self.track_chat_event_message(message)

        text = message_text(message)
        if re.fullmatch(r"v!poff\s*", message.content, re.IGNORECASE):
            if message.guild is None:
                await message.reply(
                    "This command can only be used in a server channel.",
                    mention_author=False,
                )
                return
            self.set_auto_pause_incense_enabled(message.guild.id, False)
            await message.reply(
                "Automatic incense pausing is now off for this server.",
                mention_author=False,
            )
            return
        if re.fullmatch(r"v!pon\s*", message.content, re.IGNORECASE):
            if message.guild is None:
                await message.reply(
                    "This command can only be used in a server channel.",
                    mention_author=False,
                )
                return
            self.set_auto_pause_incense_enabled(message.guild.id, True)
            await message.reply(
                "Automatic incense pausing is now on for this server.",
                mention_author=False,
            )
            return
        if re.fullmatch(r"v!(?:p|pause)\s+all", message.content, re.IGNORECASE):
            if message.guild is None:
                await message.reply(
                    "This command can only be used in a server channel.",
                    mention_author=False,
                )
                return
            paused, failed = await self.pause_active_incense_channels(message.guild)
            if not paused and not failed:
                response = "No active incense channels in this server."
            else:
                response = f"Incense paused in {paused} channel(s)."
                if failed:
                    response += (
                        f" Couldn't scan or pause {failed} channel(s); "
                        "check Read Message History, Manage Permissions, and logs."
                    )
            await message.reply(response, mention_author=False)
            return
        if re.fullmatch(r"v!(?:p|pause)", message.content, re.IGNORECASE):
            if channel_id is None or not await self.set_poketwo_blocked(
                message.channel,
                True,
            ):
                await message.reply(
                    "I couldn't pause Pokétwo in this channel. "
                    "Check the bot's channel permissions.",
                    mention_author=False,
                )
                return
            self.muted_poketwo_channels.add(channel_id)
            await message.reply("Incense paused.", mention_author=False)
            return
        if re.fullmatch(r"v!r", message.content, re.IGNORECASE):
            if channel_id not in self.muted_poketwo_channels:
                await message.reply("This channel is not paused.", mention_author=False)
                return
            if not await self.set_poketwo_blocked(message.channel, False):
                await message.reply(
                    "I couldn't resume Pokétwo in this channel. "
                    "Check the bot's channel permissions.",
                    mention_author=False,
                )
                return
            self.muted_poketwo_channels.discard(channel_id)
            await message.reply("Incense resumed.", mention_author=False)
            return
        if message.author.id != self.config.poketwo_bot_id:
            if COMMANDS_OFF_PATTERN.fullmatch(message.content):
                await self.handle_command_lock_command(message, locked=True)
                return
            if COMMANDS_ON_PATTERN.fullmatch(message.content):
                await self.handle_command_lock_command(message, locked=False)
                return
            if (
                message.guild is not None
                and self.commands_locked_for_guild(message.guild.id)
                and re.match(r"^\s*(?:v!|h!grab\s*$)", message.content, re.IGNORECASE)
            ):
                await message.reply(
                    "Commands are currently disabled for this server.",
                    mention_author=False,
                )
                return
            if re.match(r"^v!permission(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_permission_command(message)
                return
            permission_group = command_permission_group(message.content)
            if (
                permission_group is not None
                and message.guild is not None
                and not can_use_permission_group(
                    self,
                    permission_group,
                    message.guild.id,
                    message.author,
                )
            ):
                role_id = command_role_id_for_guild(self, message.guild.id)
                await message.reply(
                    f"You need the configured role <@&{role_id}> to use this command.",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            if (
                message.guild is not None
                and is_premium_only_command(message.content)
                and self.premium_tier_for_guild(message.guild.id) is None
            ):
                await message.reply(
                    "This command requires a premium tier. Run `v!premium` "
                    "to check this server's access.",
                    mention_author=False,
                )
                return
            if PROFILE_COMMAND_PATTERN.fullmatch(message.content):
                await self.handle_profile_command(message)
                return
            if re.fullmatch(r"v!report\s*", message.content, re.IGNORECASE):
                await self.handle_reserve_report(message)
                return
            if re.match(r"^v!droplog(?:\s|$)", message.content, re.IGNORECASE):
                try:
                    await self.pokeball_drops.configure_log(message)
                except ValueError:
                    logger.exception("Could not save Pokéball log settings")
                    await message.reply("I couldn't save the drop log settings. Check the bot logs.", mention_author=False)
                return
            if re.match(r"^v!drops(?:\s|$)", message.content, re.IGNORECASE):
                try:
                    await self.pokeball_drops.configure(message)
                except ValueError:
                    logger.exception("Could not save Pokéball drop settings")
                    await message.reply("I couldn't save the drop settings. Check the bot logs.", mention_author=False)
                return
            if re.fullmatch(r"v!dyeinv\s*", message.content, re.IGNORECASE):
                await self.pokeball_drops.dye_inventory(message)
                return
            if re.fullmatch(r"v!useddyes?\s*", message.content, re.IGNORECASE):
                await self.pokeball_drops.used_dyes(message)
                return
            if re.match(r"^v!dye(?:\s|$)", message.content, re.IGNORECASE):
                try:
                    await self.pokeball_drops.dye(message)
                except ValueError:
                    logger.exception("Could not apply profile dye")
                    await message.reply("I couldn't save the dye. Check the bot logs.", mention_author=False)
                return
            if re.match(r"^v!equip(?:\s|$)", message.content, re.IGNORECASE):
                try:
                    await self.pokeball_drops.equip(message)
                except ValueError:
                    logger.exception("Could not equip profile asset")
                    await message.reply("I couldn't equip that asset. Check the bot logs.", mention_author=False)
                return
            if re.match(r"^v!shop(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_profile_shop_command(message)
                return
            if re.fullmatch(r"v!inv\s*", message.content, re.IGNORECASE):
                await self.handle_profile_inventory_command(message)
                return
            if re.match(r"^v!buy(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_profile_buy_command(message)
                return
            if PROFILE_BACKFILL_COMMAND_PATTERN.fullmatch(message.content):
                await self.handle_profile_backfill_command(message)
                return
            if re.fullmatch(r"v!event\s*", message.content, re.IGNORECASE):
                await self.handle_event_command(message)
                return
            if re.match(
                r"^v!(?:addcategory|categorycreate|categorylist|categorydelete|cd)(?:\s|$)",
                message.content,
                re.IGNORECASE,
            ):
                await self.handle_reserve_category_command(message)
                return
            if re.match(r"^v!r(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_reserve_command(message)
                return
            if is_image_test_command(message.content):
                if image_url(message) is None:
                    await message.reply(
                        "Attach an image to `v!test` or `v!test shiny` "
                        "to test spawn recognition.",
                        mention_author=False,
                    )
                    return
                shiny_test_mode = (
                    re.fullmatch(
                        r"v!test\s+shiny\s*",
                        message.content,
                        re.IGNORECASE,
                    )
                    is not None
                )
                await self.handle_spawn(
                    message,
                    test_mode=True,
                    shiny_test_mode=shiny_test_mode,
                )
                return
            if re.fullmatch(r"v!support\s*", message.content, re.IGNORECASE):
                donation_url = "https://gofund.me/a71832b06"
                description = (
                    "<a:emoji_27:1534340529192697959> "
                    "Running and developing Vivillon costs money. "
                    "Donations are completely optional, but every bit of support "
                    "helps keep the bot running. Thank you!"
                )
                embed = discord.Embed(
                    title="Support Vivillon",
                    description=description,
                    color=discord.Color.blurple(),
                )
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(label="Donate on GoFundMe", url=donation_url))
                try:
                    await message.reply(embed=embed, view=view, mention_author=False)
                except discord.Forbidden:
                    await message.reply(
                        f"{description}\nDonate on GoFundMe: {donation_url}",
                        mention_author=False,
                    )
                return
            if re.fullmatch(HELP_COMMAND_PATTERN, message.content, re.IGNORECASE):
                try:
                    help_embeds = build_help_menu_embeds()
                    if len(help_embeds) > 1:
                        help_view = HelpMenuView(help_embeds, message.author.id)
                        help_view.message = await message.reply(
                            embed=help_embeds[0],
                            view=help_view,
                            mention_author=False,
                        )
                    else:
                        await message.reply(
                            embed=help_embeds[0], mention_author=False
                        )
                except discord.Forbidden:
                    await message.reply(
                        "I need the Embed Links permission in this channel to "
                        "show the help list.",
                        mention_author=False,
                    )
                return
            if await self.daycare.handle_message(message):
                return
            if re.match(r"^v!settime(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_settime_command(message)
                return
            if re.fullmatch(r"v!timereset\s*", message.content, re.IGNORECASE):
                await self.handle_timereset_command(message)
                return
            grab_match = re.fullmatch(r"([vh])!grab\s*", message.content, re.IGNORECASE)
            if grab_match:
                await self.handle_grab_command(
                    message, silent_h_mode=grab_match.group(1).lower() == "h"
                )
                return
            if re.fullmatch(r"v!ping\s*", message.content, re.IGNORECASE):
                await self.handle_ping_command(message)
                return
            if re.fullmatch(r"v!settings\s*", message.content, re.IGNORECASE):
                await self.handle_settings_command(message)
                return
            if re.match(r"^v!lowaccuracy(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_low_accuracy_command(message)
                return
            if re.fullmatch(r"v!afk\s*", message.content, re.IGNORECASE):
                await self.handle_afk_command(message)
                return
            if API_STATUS_COMMAND_PATTERN.fullmatch(message.content):
                await self.handle_api_status(message)
                return
            if re.match(r"^v!sh(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_shinyhunt_command(message)
                return
            if re.match(r"^v!(?:tp|typeping)(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_type_ping_command(message)
                return
            if re.match(r"^v!cl(?:\s|$)", message.content, re.IGNORECASE):
                await self.handle_collection_command(message)
                return
            if re.match(
                r"^v!r\s+(?:add|list|search|remove|clear|e|exchange)(?:\s|$)",
                message.content,
                re.IGNORECASE,
            ):
                await self.handle_reserve_command(message)
            return

        if SPAWN_PATTERN.search(text):
            self.pokeball_drops.record_spawn(message)
            await self.handle_spawn(message)

    async def is_application_owner(self, user_id: int) -> bool:
        if self.application_owner_ids is None:
            application = await self.application_info()
            owner_ids: set[int] = set()
            if application.owner is not None:
                owner_ids.add(application.owner.id)
            if (
                application.team is not None
                and application.team.owner_id is not None
            ):
                owner_ids.add(application.team.owner_id)
            self.application_owner_ids = owner_ids
        return user_id in self.application_owner_ids

    async def handle_image_correction(self, message: discord.Message) -> None:
        try:
            owner = await self.is_application_owner(message.author.id)
        except discord.HTTPException:
            logger.exception("Could not verify the bot owner for image correction")
            await message.reply("I couldn't verify the bot owner. Check the logs.", mention_author=False)
            return
        if not owner:
            await message.reply("Only the bot owner can correct images.", mention_author=False)
            return
        match = re.fullmatch(r"v!correct\s+(.+?)\s*", message.content, re.IGNORECASE)
        if match is None or message.guild is None or message.reference is None:
            await message.reply(
                "Reply to a recognition alert with `v!correct <correct Pokémon name>`.",
                mention_author=False,
            )
            return
        channels = {RECOGNITION_ALERT_CHANNEL_ID, *self.low_accuracy_channels.values()}
        if message.channel.id not in channels:
            await message.reply("Use this command in a recognition alert channel.", mention_author=False)
            return
        lookup = known_name_lookup().copy()
        lookup.update({normalize_pokemon_alias(name): name for name in self.image_matcher.entries})
        lookup.update(
            {normalize_pokemon_alias(display): form for form, display in FORM_DISPLAY_NAMES.items()}
        )
        name = lookup.get(normalize_pokemon_alias(canonicalize_pokemon_name(match.group(1))))
        if name is None:
            await message.reply("I don't recognize that Pokémon name. Check its spelling.", mention_author=False)
            return
        if name.islower():
            name = name.title()
        reference_id = message.reference.message_id
        if reference_id is None:
            await message.reply("I couldn't read the alert you replied to.", mention_author=False)
            return
        try:
            alert = await message.channel.fetch_message(reference_id)
        except discord.HTTPException:
            logger.exception("Could not fetch recognition alert %s", reference_id)
            await message.reply("I couldn't read the alert. Check my channel permissions.", mention_author=False)
            return
        if self.user is None or alert.author.id != self.user.id:
            await message.reply("Please reply to an alert sent by this bot.", mention_author=False)
            return
        low_alert = re.fullmatch(
            rf"<@{RECOGNITION_ALERT_USER_ID}> ⚠️ Low accuracy: "
            r"\*\*(.+?)\*\* at (\d+(?:\.\d+)?)% \(below 50%\)\n"
            r"https://discord\.com/channels/(\d+)/(\d+)/(\d+)",
            alert.content,
        )
        failure_alert = re.fullmatch(
            rf"<@{RECOGNITION_ALERT_USER_ID}> Vivillon couldn't confidently identify "
            r"the spawn in <#\d+>\.\nJump to the spawn: "
            r"https://discord\.com/channels/(\d+)/(\d+)/(\d+)",
            alert.content,
        )
        if low_alert:
            previous_guess, previous_confidence, guild_id, channel_id, spawn_id = low_alert.groups()
        elif failure_alert:
            guild_id, channel_id, spawn_id = failure_alert.groups()
            previous_guess, previous_confidence = "", ""
        else:
            await message.reply("Please reply to a recognition alert from this bot.", mention_author=False)
            return
        try:
            channel = self.get_channel(int(channel_id))
            if channel is None:
                channel = await self.fetch_channel(int(channel_id))
            if not isinstance(channel, discord.abc.Messageable):
                raise ValueError("Spawn channel cannot be read")
            source = await channel.fetch_message(int(spawn_id))
            if (
                source.guild is None
                or source.guild.id != int(guild_id)
                or source.author.id != self.config.poketwo_bot_id
            ):
                raise ValueError("Alert does not point to a Pokétwo spawn")
            url = image_url(source)
            if url is None or self.image_http is None:
                raise ValueError("Spawn image or HTTP client is unavailable")
            image, _ = await download_image(self.image_http, url)
            digest = hashlib.sha256(image).hexdigest()
            append_image_correction(
                self.image_corrections_path,
                {
                    "image_sha256": digest,
                    "correct_name": name,
                    "source_message_id": spawn_id,
                    "previous_guess": previous_guess,
                    "previous_confidence": previous_confidence,
                    "corrected_by": str(message.author.id),
                    "alert_message_id": str(reference_id),
                },
            )
        except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            logger.exception("Could not save image correction for alert %s", reference_id)
            await message.reply(
                "I couldn't save that correction. The original spawn or image may be unavailable; check the logs.",
                mention_author=False,
            )
            return
        self.image_matcher.corrected_references[digest] = name
        await message.reply(
            f"Saved **{display_pokemon_name(name)}** for this exact image. "
            "Future identical images will use this name.",
            mention_author=False,
        )

    async def handle_premium_command(self, message: discord.Message) -> None:
        match = PREMIUM_COMMAND_PATTERN.fullmatch(message.content.strip())
        if match is None:
            await message.reply(
                "Usage: `v!premium` or "
                "`v!premium add bronze|silver|gold <server id>`.",
                mention_author=False,
            )
            return

        tier = match.group("tier")
        if tier is not None:
            if message.guild is None or message.guild.id != SERVER_ID:
                await message.reply(
                    "Premium can only be granted from the main server.",
                    mention_author=False,
                )
                return
            try:
                is_owner = await self.is_application_owner(message.author.id)
            except discord.HTTPException:
                logger.exception("Could not verify the bot owner for premium access")
                await message.reply(
                    "I couldn't verify premium management access. Try again later.",
                    mention_author=False,
                )
                return
            if not is_owner:
                await message.reply(
                    "Only the bot owner can grant premium access.",
                    mention_author=False,
                )
                return

            guild_id = int(match.group("guild_id"))
            if guild_id <= 0:
                await message.reply(
                    "The server ID must be a positive number.",
                    mention_author=False,
                )
                return
            normalized_tier = tier.casefold()
            updated_premium_servers = dict(self.premium_servers)
            updated_premium_servers[str(guild_id)] = normalized_tier
            try:
                save_premium_servers(
                    self.premium_servers_path,
                    updated_premium_servers,
                )
            except ValueError:
                logger.exception("Could not save premium access for server %s", guild_id)
                await message.reply(
                    "I couldn't save that premium tier. Check the bot logs.",
                    mention_author=False,
                )
                return
            self.premium_servers = updated_premium_servers
            async with self.vision_capacity_condition:
                self.vision_capacity_condition.notify_all()
            await message.reply(
                f"**{normalized_tier.title()}** access is active for server "
                f"`{guild_id}`: up to "
                f"{PREMIUM_TIER_LIMITS[normalized_tier]} simultaneous spawn "
                "recognitions.",
                mention_author=False,
            )
            return

        if message.guild is None:
            await message.reply(
                "Use `v!premium` in a server to check that server's tier.",
                mention_author=False,
            )
            return
        current_tier = self.premium_tier_for_guild(message.guild.id)
        files = premium_status_files(current_tier)
        try:
            await message.reply(
                embeds=build_premium_status_embeds(current_tier),
                files=files,
                mention_author=False,
            )
        finally:
            for file in files:
                file.close()

    def premium_tier_for_guild(self, guild_id: int) -> str | None:
        return self.premium_servers.get(str(guild_id))

    def premium_limit_for_guild(self, guild_id: int) -> int:
        tier = self.premium_tier_for_guild(guild_id)
        if tier is None:
            return 0
        return PREMIUM_TIER_LIMITS.get(tier, 0)

    async def acquire_vision_capacity(self, guild_id: int) -> None:
        guild_limit = self.premium_limit_for_guild(guild_id)
        if guild_limit == 0:
            raise ValueError(f"Server {guild_id} has no premium spawn-naming tier")
        async with self.vision_capacity_condition:
            await self.vision_capacity_condition.wait_for(
                lambda: (
                    self.active_vision_requests
                    < self.config.max_concurrent_vision_requests
                    and self.active_vision_requests_by_guild.get(guild_id, 0)
                    < self.premium_limit_for_guild(guild_id)
                )
            )
            self.active_vision_requests += 1
            self.active_vision_requests_by_guild[guild_id] = (
                self.active_vision_requests_by_guild.get(guild_id, 0) + 1
            )

    async def release_vision_capacity(self, guild_id: int) -> None:
        async with self.vision_capacity_condition:
            active_for_guild = self.active_vision_requests_by_guild.get(guild_id, 0)
            if active_for_guild == 0 or self.active_vision_requests == 0:
                raise RuntimeError("Released a vision slot that was not acquired")
            if active_for_guild == 1:
                del self.active_vision_requests_by_guild[guild_id]
            else:
                self.active_vision_requests_by_guild[guild_id] = active_for_guild - 1
            self.active_vision_requests -= 1
            self.vision_capacity_condition.notify_all()

    def is_allowed_channel(self, channel: discord.abc.Messageable) -> bool:
        return getattr(channel, "guild", None) is not None

    def load_active_incenses(self) -> dict[str, ActiveIncense]:
        if not self.incense_path.is_file():
            return {}
        try:
            data = json.loads(self.incense_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning(
                "Could not load incense tracking from %s: %s",
                self.incense_path,
                error,
            )
            return {}
        if not isinstance(data, dict):
            logger.warning(
                "Incense tracking file %s has an invalid format", self.incense_path
            )
            return {}
        now = int(time.time())
        records: dict[str, ActiveIncense] = {}
        for channel_id, record in data.items():
            if (
                not isinstance(channel_id, str)
                or not isinstance(record, dict)
                or not isinstance(record.get("guild"), str)
                or not isinstance(record.get("channel"), str)
                or isinstance(record.get("expires_at"), bool)
                or not isinstance(record.get("expires_at"), int)
                or isinstance(record.get("guild_id"), bool)
                or not isinstance(record.get("guild_id"), int)
            ):
                logger.warning(
                    "Incense tracking file %s has an invalid entry",
                    self.incense_path,
                )
                return {}
            if record["expires_at"] > now:
                records[channel_id] = {
                    "guild": record["guild"],
                    "channel": record["channel"],
                    "guild_id": record["guild_id"],
                    "expires_at": record["expires_at"],
                }
        return records

    def save_active_incenses(self) -> None:
        try:
            self.incense_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.incense_path.with_name(
                f"{self.incense_path.name}.tmp"
            )
            temporary_path.write_text(
                json.dumps(self.active_incenses, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.incense_path)
        except OSError:
            logger.exception("Could not save incense tracking to %s", self.incense_path)

    def track_incense_command(self, message: discord.Message) -> str | None:
        guild = message.guild
        channel = message.channel
        if guild is None:
            return None
        action = incense_action_from_message(
            message,
            self.config.poketwo_bot_id,
        )
        if action is None:
            return None
        if action == "buy" and message.author.id != self.config.poketwo_bot_id:
            return action
        channel_id = str(channel.id)
        if action == "stop":
            self.active_incenses.pop(channel_id, None)
        else:
            self.active_incenses[channel_id] = {
                "guild": guild.name,
                "channel": getattr(channel, "name", f"channel-{channel.id}"),
                "guild_id": guild.id,
                "expires_at": int(time.time()) + INCENSE_DURATION_SECONDS,
            }
        self.save_active_incenses()
        return action

    async def pause_confirmed_incense_purchase(
        self,
        message: discord.Message,
    ) -> None:
        if message.author.id != self.config.poketwo_bot_id:
            return
        if message.guild is None or not self.auto_pause_incense_enabled_for_guild(
            message.guild.id
        ):
            return
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return
        if await self.set_poketwo_blocked(message.channel, True):
            self.muted_poketwo_channels.add(channel_id)
            await message.reply(
                "Incense has been paused.",
                mention_author=False,
            )
        else:
            await message.reply(
                "I couldn't pause incense in this channel. "
                "Check the bot permissions.",
                mention_author=False,
            )

    def current_active_incenses(self) -> list[ActiveIncense]:
        now = int(time.time())
        expired = [
            channel_id
            for channel_id, record in self.active_incenses.items()
            if record["expires_at"] <= now
        ]
        if expired:
            for channel_id in expired:
                del self.active_incenses[channel_id]
            self.save_active_incenses()
        return sorted(
            self.active_incenses.values(),
            key=lambda record: (
                str(record["guild"]).casefold(),
                str(record["channel"]).casefold(),
            ),
        )

    async def handle_profile_backfill_command(
        self,
        message: discord.Message,
    ) -> None:
        command_match = PROFILE_BACKFILL_COMMAND_PATTERN.fullmatch(message.content)
        if command_match is None:
            return
        guild = message.guild
        if guild is None:
            await message.reply(
                "Profile backfill is only available in a server.",
                mention_author=False,
            )
            return
        if (
            not member_is_administrator(message.author)
            and not member_has_command_role(self, guild.id, message.author)
        ):
            await message.reply(
                "Only server administrators or members with the configured "
                "command role can backfill profile catches.",
                mention_author=False,
            )
            return
        if command_match.group("stop") is not None:
            if guild.id not in self.profile_backfills_in_progress:
                await message.reply(
                    "No profile backfill is running.",
                    mention_author=False,
                )
                return
            self.profile_backfill_stop_requests.add(guild.id)
            await message.reply(
                "Backfill stop requested. It will stop as soon as possible.",
                mention_author=False,
            )
            return
        if guild.id in self.profile_backfills_in_progress:
            await message.reply(
                "A profile backfill is already running.",
                mention_author=False,
            )
            return

        bot_member = guild.me
        if bot_member is None:
            await message.reply(
                "I could not verify my server permissions, so the backfill cannot start.",
                mention_author=False,
            )
            return

        guild_key_prefix = f"{guild.id}:"

        def guild_catch_total() -> int:
            return sum(
                stats["total"]
                for key, stats in self.profile_stats.items()
                if key.startswith(guild_key_prefix)
            )

        def guild_box_shiny_total() -> int:
            return sum(
                stats.get("box_shiny", 0)
                for key, stats in self.profile_stats.items()
                if key.startswith(guild_key_prefix)
            )

        total_before = guild_catch_total()
        box_shiny_before = guild_box_shiny_total()
        scanned_messages = 0
        failed_channels = 0
        channels_done = 0
        progress_reporting_failed = False
        stopped = False
        skipped_channels = 0
        self.profile_backfill_stop_requests.discard(guild.id)
        self.profile_backfills_in_progress.add(guild.id)
        try:
            progress = await message.reply(
                "Preparing profile backfill and checking channel permissions.",
                mention_author=False,
            )
            all_channels = [*guild.text_channels, *guild.threads]
            category_name = None
            channel_argument = command_match.group("channel")
            continue_argument = command_match.group("continue_from")
            continue_start_name = None
            if continue_argument is not None:
                start_id = int(re.sub(r"\D", "", continue_argument))
                ordered_channels = [
                    channel
                    for _, grouped in guild.by_category()
                    for channel in grouped
                    if isinstance(channel, discord.TextChannel)
                ]
                start_index = next(
                    (
                        index
                        for index, channel in enumerate(ordered_channels)
                        if channel.id == start_id
                    ),
                    None,
                )
                if start_index is None:
                    await progress.edit(
                        content="I couldn't find that text channel in this server."
                    )
                    return
                continue_start_name = ordered_channels[start_index].name
                ordered_channels = ordered_channels[start_index:]
                included_ids = {channel.id for channel in ordered_channels}
                all_channels = [
                    *ordered_channels,
                    *(
                        thread
                        for thread in guild.threads
                        if thread.parent_id in included_ids
                    ),
                ]
            elif channel_argument is not None:
                channel_id_match = re.fullmatch(
                    r"<#(\d+)>|(\d+)",
                    channel_argument,
                )
                if channel_id_match is None:
                    await progress.edit(
                        content="Use a channel mention or channel ID with `v!backfill`."
                    )
                    return
                requested_channel_id = int(
                    channel_id_match.group(1) or channel_id_match.group(2)
                )
                selected_category = next(
                    (
                        category
                        for category in guild.categories
                        if category.id == requested_channel_id
                    ),
                    None,
                )
                if selected_category is not None:
                    all_channels = [
                        channel
                        for channel in all_channels
                        if channel.category_id == selected_category.id
                        or getattr(channel, "parent", None) is not None
                        and channel.parent.category_id == selected_category.id
                    ]
                    category_name = selected_category.name
                    if not all_channels:
                        await progress.edit(
                            content=(
                                f"There are no text channels in the category "
                                f"{category_name}."
                            )
                        )
                        return
                else:
                    selected_channel = next(
                        (
                            channel
                            for channel in all_channels
                            if channel.id == requested_channel_id
                        ),
                        None,
                    )
                    if selected_channel is None:
                        await progress.edit(
                            content=(
                                "I couldn't find that category, text channel "
                                "or active thread in this server."
                            )
                        )
                        return
                    all_channels = [selected_channel]
            channels = []
            for channel in all_channels:
                if guild.id in self.profile_backfill_stop_requests:
                    stopped = True
                    break
                permissions = channel.permissions_for(bot_member)
                if permissions.view_channel and permissions.read_message_history:
                    channels.append(channel)
                else:
                    skipped_channels += 1
            if stopped:
                await progress.edit(
                    content="Backfill stopped before scanning any messages."
                )
                return
            if not channels:
                await progress.edit(
                    content=(
                        "I need View Channel and Read Message History "
                        "permissions to backfill catches."
                    )
                )
                return
            await progress.edit(
                content=(
                    (
                        f"Continuing profile backfill from #{continue_start_name} "
                        f"through the last channel ({len(channels)} readable "
                        "channels and threads)."
                        if continue_start_name is not None
                        else f"Backfilling profile data in #{channels[0].name}."
                        if channel_argument is not None and category_name is None
                        else (
                            f"Backfilling profile data across {len(channels)} "
                            f"readable channels in the category {category_name}."
                            if category_name is not None
                            else (
                                f"Backfilling profile data across {len(channels)} "
                                "readable channels and active threads."
                            )
                        )
                    )
                    + " This may take a while."
                )
            )
            for channel in channels:
                if guild.id in self.profile_backfill_stop_requests:
                    stopped = True
                    break
                channel_scanned_messages = 0
                channel_status = "complete"
                try:
                    async for historical_message in channel.history(
                        limit=None,
                        oldest_first=True,
                    ):
                        if guild.id in self.profile_backfill_stop_requests:
                            stopped = True
                            break
                        self.track_profile_catch(
                            historical_message,
                            persist=False,
                        )
                        await self.track_profile_box_shiny(
                            historical_message,
                            persist=False,
                        )
                        scanned_messages += 1
                        channel_scanned_messages += 1
                except discord.Forbidden:
                    failed_channels += 1
                    channel_status = "inaccessible"
                    logger.warning(
                        "Profile backfill cannot read channel %s (%s)",
                        channel.id,
                        channel.name,
                    )
                except discord.HTTPException as error:
                    failed_channels += 1
                    channel_status = "failed"
                    logger.warning(
                        "Profile backfill failed in channel %s (%s): %s",
                        channel.id,
                        channel.name,
                        error,
                    )
                if stopped:
                    channel_status = "stopped"
                else:
                    channels_done += 1
                catches_recorded = guild_catch_total() - total_before
                channel_word = "channel" if channels_done == 1 else "channels"
                for update in (
                    (
                        f"progress: {scanned_messages:,} messages scanned, "
                        f"{catches_recorded:,} catches recorded, "
                        f"{channels_done} {channel_word} done."
                    ),
                    (
                        f"#{channel.name}: scanned "
                        f"{channel_scanned_messages:,} messages "
                        f"({channel_status})."
                    ),
                ):
                    try:
                        await message.channel.send(content=update)
                    except discord.HTTPException as error:
                        progress_reporting_failed = True
                        logger.warning(
                            "Could not post backfill progress for channel "
                            "%s (%s): %s",
                            channel.id,
                            channel.name,
                            error,
                        )
                if stopped:
                    break
            stopped = stopped or guild.id in self.profile_backfill_stop_requests

            try:
                save_profile_data(
                    self.profile_data_path,
                    self.profiles,
                    self.profile_stats,
                    self.profile_records,
                    self.profile_seen_catch_ids,
                )
            except ValueError as error:
                logger.exception("Could not save profile data after backfill")
                await progress.edit(
                    content=(
                        "Backfill could not save profile data. "
                        f"Check the bot logs. ({error})"
                    )
                )
                return

            total_after = guild_catch_total()
            box_shiny_after = guild_box_shiny_total()
            result = (
                f"Backfill {'stopped' if stopped else 'finished'}: "
                f"scanned {scanned_messages:,} messages "
                f"and added {total_after - total_before:,} catches and "
                f"{box_shiny_after - box_shiny_before:,} Box Shinies to profiles."
            )
            incomplete_channels = skipped_channels + failed_channels
            if incomplete_channels:
                result += (
                    f" I could not read {incomplete_channels} channel(s), "
                    "so totals may be incomplete. Grant me View Channel and "
                    "Read Message History permissions, then rerun `v!backfill`."
                )
            if progress_reporting_failed:
                result += " Some per-channel progress updates could not be posted."
            await progress.edit(content=result)
        finally:
            self.profile_backfill_stop_requests.discard(guild.id)
            self.profile_backfills_in_progress.discard(guild.id)

    async def handle_profile_shop_command(
        self,
        message: discord.Message,
    ) -> None:
        if message.guild is None:
            await message.reply("The profile shop is only available in a server.", mention_author=False)
            return
        if not re.fullmatch(r"v!shop\s*", message.content, re.IGNORECASE):
            match = PROFILE_SHOP_PREVIEW_PATTERN.fullmatch(message.content)
            query = match.group(1).strip() if match and match.group(1) else ""
            if not query:
                await message.reply(
                    "Usage: `v!shop preview <asset name>`.",
                    mention_author=False,
                )
                return
            matches = self.profile_shop_items_for_query(query)
            if len(matches) != 1:
                await message.reply(
                    "I couldn't find one matching shop item. Use its name from "
                    "`v!shop`; if names match, include `frame`, `background`, "
                    "or `middle background` before the name.",
                    mention_author=False,
                )
                return
            asset_id, item = matches[0]
            setting = str(item["type"])
            key = str(item["key"])
            if key not in profile_setting_choices_for_user(message.author.id, setting):
                await message.reply(
                    "This profile asset is not available to your account.",
                    mention_author=False,
                )
                return
            settings = self.profile_settings_for_user(message.author.id)
            settings[setting] = key
            dyes = self.pokeball_drops.appearance(message.author.id, settings)
            dyes.pop(setting, None)
            try:
                avatar = await message.author.display_avatar.read()
            except (discord.HTTPException, aiohttp.ClientError):
                logger.warning(
                    "Could not fetch profile avatar for %s",
                    message.author.id,
                    exc_info=True,
                )
                avatar = None
            profile_file = discord.File(
                render_profile_image(
                    settings,
                    self.profile_stats_for_user(message.guild.id, message.author.id),
                    await self.load_profile_emoji_assets(),
                    self.profile_records_for_user(message.guild.id, message.author.id),
                    username=message.author.display_name,
                    avatar=avatar,
                    level=self.pokeball_drops.level(message.author.id),
                    dyes=dyes,
                ),
                filename="profile-preview.png",
            )
            await message.reply(
                content=f"Shop preview: **{profile_asset_display(asset_id)}** (not purchased or equipped).",
                file=profile_file,
                mention_author=False,
            )
            return
        view = ProfileShopView(self, message.author.id)
        response = await message.reply(
            embed=view.embed,
            view=view,
            mention_author=False,
        )
        view.message = response

    async def handle_profile_inventory_command(
        self,
        message: discord.Message,
    ) -> None:
        view = ProfileInventoryView(self, message.author.id)
        view.embed.title = None
        await message.reply(
            content=f"{message.author.display_name}'s Inventory",
            embed=view.embed,
            view=view,
            files=profile_currency_icon_files(),
            mention_author=False,
        )

    async def handle_profile_buy_command(
        self,
        message: discord.Message,
    ) -> None:
        if message.guild is None:
            await message.reply("Purchases are only available in a server.", mention_author=False)
            return
        match = PROFILE_BUY_PATTERN.fullmatch(message.content)
        query = match.group(1).strip() if match and match.group(1) else None
        if not query:
            await message.reply(
                "Usage: `v!buy <asset name>`.",
                mention_author=False,
            )
            return
        matches = self.profile_shop_items_for_query(query)
        if len(matches) != 1:
            await message.reply(
                "I couldn't find one matching shop item. Use its name from "
                "`v!shop`; if names match, include `frame`, `background`, "
                "or `middle background` before the name.",
                mention_author=False,
            )
            return
        asset_id, item = matches[0]
        name = profile_asset_display(asset_id)
        price = int(item["price"])
        currency = str(item["currency"])
        view = ProfilePurchaseView(self, message.author.id, asset_id, item)
        embed = discord.Embed(
            description=(
                f"Are you sure you want to buy **{name}** for "
                f"{price:,} {currency}?"
            ),
            color=discord.Color.gold(),
        )
        await message.reply(
            embed=embed,
            view=view,
            mention_author=False,
        )

    async def handle_profile_command(self, message: discord.Message) -> None:
        match = PROFILE_COMMAND_PATTERN.fullmatch(message.content)
        if match is None:
            return
        if message.guild is None:
            await message.reply(
                "Profiles are only available in a server.",
                mention_author=False,
            )
            return
        user_id = int(match.group(1)) if match.group(1) else message.author.id
        preview_owner_id = None
        if user_id != message.author.id and await self.is_application_owner(
            message.author.id
        ):
            preview_owner_id = message.author.id
        settings = self.profile_settings_for_user(user_id)
        stats = self.profile_stats_for_user(message.guild.id, user_id)
        records = self.profile_records_for_user(message.guild.id, user_id)
        emoji_assets = await self.load_profile_emoji_assets()
        member = message.guild.get_member(user_id)
        if member is None and user_id == message.author.id:
            member = message.author
        user = member or self.get_user(user_id)
        if user is None:
            try:
                user = await self.fetch_user(user_id)
            except discord.HTTPException:
                logger.warning("Could not fetch profile user %s", user_id, exc_info=True)
        username = user.display_name if user is not None else f"User {user_id}"
        avatar = None
        if user is not None:
            try:
                avatar = await user.display_avatar.read()
            except (discord.HTTPException, aiohttp.ClientError):
                logger.warning("Could not fetch profile avatar for %s", user_id, exc_info=True)
        view = ProfileView(
            self,
            user_id,
            message.guild.id,
            preview_owner_id=preview_owner_id,
            username=username,
            avatar=avatar,
        )
        profile_file = discord.File(
            render_profile_image(
                settings,
                stats,
                emoji_assets,
                records,
                username=username,
                avatar=avatar,
                level=self.pokeball_drops.level(user_id),
                dyes=self.pokeball_drops.appearance(user_id, settings),
            ),
            filename="profile.png",
        )
        response = await message.reply(
            content=(
                "Owner preview only: appearance changes are temporary and "
                "will not be saved to this member's profile."
                if preview_owner_id is not None
                else None
            ),
            file=profile_file,
            view=view,
            mention_author=False,
        )
        view.message = response

    async def handle_event_command(self, message: discord.Message) -> None:
        embed = discord.Embed(
            title="Choose an event",
            description="Choose an event to start. More events may be added later.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Chat event",
            value=(
                "At least two participants react to join, then compete to send "
                "the most sentences with at least four words."
            ),
            inline=False,
        )
        await message.reply(
            embed=embed,
            view=EventMenuView(self, message.author.id),
            mention_author=False,
        )

    async def start_chat_event(
        self, interaction: discord.Interaction, host_id: int
    ) -> None:
        channel = interaction.channel
        channel_id = getattr(channel, "id", None)
        if not is_messageable_channel(channel) or not isinstance(channel_id, int):
            await interaction.response.send_message(
                "This event needs to be started in a server channel.",
                ephemeral=True,
            )
            return
        if channel_id in self.chat_events:
            await interaction.response.send_message(
                "A chat event is already running in this channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        session = ChatEventSession(
            host_id=host_id,
            channel=channel,
            channel_id=channel_id,
        )
        self.chat_events[channel_id] = session
        embed = discord.Embed(
            title="Chat event — sign up now!",
            description=(
                f"React with {CHAT_EVENT_EMOJI} to join. Sign-ups close in "
                f"{CHAT_EVENT_SIGNUP_SECONDS} seconds; at least "
                f"{CHAT_EVENT_MIN_PARTICIPANTS} people must join. After sign-up "
                "closes, send as many sentences with at least four words as you can."
            ),
            color=discord.Color.green(),
        )
        try:
            session.message = await channel.send(embed=embed)
            await session.message.add_reaction(CHAT_EVENT_EMOJI)
        except discord.HTTPException as error:
            self.chat_events.pop(channel_id, None)
            logger.warning("Could not start chat event: %s", error)
            await interaction.followup.send(
                "I couldn't start the chat event. Check that I can send messages "
                "and add reactions in this channel.",
                ephemeral=True,
            )
            return

        asyncio.create_task(self.run_chat_event(session))
        await interaction.followup.send(
            "Choose any positive duration in minutes or hours, such as "
            "`7 minutes` or `2 hours`. A number by itself means minutes. "
            "The timer starts after the one-minute sign-up period.",
            view=ChatEventDurationView(session),
            ephemeral=True,
        )
        try:
            if interaction.message is not None:
                await interaction.message.edit(
                    embed=discord.Embed(
                        title="Chat event selected",
                        description="The sign-up message is now open below.",
                        color=discord.Color.green(),
                    ),
                    view=None,
                )
        except discord.HTTPException as error:
            logger.warning("Could not update the event menu: %s", error)

    def track_chat_event_message(self, message: discord.Message) -> None:
        if message.author.bot or message.content.casefold().startswith("v!"):
            return
        session = self.chat_events.get(message.channel.id)
        if (
            session is None
            or not session.collecting
            or message.author.id not in session.participant_ids
        ):
            return
        session.sentence_counts[message.author.id] += count_qualifying_sentences(
            message.content
        )

    async def run_chat_event(self, session: ChatEventSession) -> None:
        channel_id = session.channel_id
        if channel_id is None:
            channel_id = getattr(session.channel, "id", None)
        if isinstance(channel_id, bool) or not isinstance(channel_id, int):
            raise RuntimeError("Chat event channel has no valid channel ID")
        try:
            await asyncio.sleep(CHAT_EVENT_SIGNUP_SECONDS)
            if session.message is None:
                return
            reaction = next(
                (
                    item
                    for item in session.message.reactions
                    if str(item.emoji) == CHAT_EVENT_EMOJI
                ),
                None,
            )
            if reaction is not None:
                try:
                    async for user in reaction.users(limit=None):
                        if not user.bot:
                            session.participant_ids.add(user.id)
                except discord.HTTPException as error:
                    logger.warning("Could not read chat event sign-ups: %s", error)
                    await session.channel.send(
                        "I couldn't read the sign-ups, so the chat event was canceled."
                    )
                    return
            try:
                await session.message.clear_reactions()
            except discord.HTTPException as error:
                logger.warning("Could not clear chat event reactions: %s", error)

            if len(session.participant_ids) < CHAT_EVENT_MIN_PARTICIPANTS:
                await session.channel.send(
                    "The chat event needs at least "
                    f"{CHAT_EVENT_MIN_PARTICIPANTS} participants; only "
                    f"{len(session.participant_ids)} signed up."
                )
                return
            session.sentence_counts = {
                user_id: 0 for user_id in session.participant_ids
            }
            await session.duration_selected.wait()
            if session.cancelled or session.duration_seconds is None:
                await session.channel.send(
                    "The chat event was canceled because no duration was chosen."
                )
                return

            session.collecting = True
            await session.channel.send(
                f"Chat event started! You have {session.duration_label}. "
                "Only sentences with at least four words count."
            )
            await asyncio.sleep(session.duration_seconds)
            session.collecting = False
            ordered_participants = sorted(
                session.participant_ids,
                key=lambda user_id: (
                    -session.sentence_counts[user_id],
                    user_id,
                ),
            )
            pages = [
                ordered_participants[index : index + 40]
                for index in range(0, len(ordered_participants), 40)
            ]
            for page_number, participant_page in enumerate(pages, start=1):
                description = "\n".join(
                    f"<@{user_id}> — {session.sentence_counts[user_id]} "
                    f"sentence(s)"
                    for user_id in participant_page
                )
                result = discord.Embed(
                    title="Chat event results"
                    if len(pages) == 1
                    else f"Chat event results ({page_number}/{len(pages)})",
                    description=description,
                    color=discord.Color.gold(),
                )
                await session.channel.send(
                    embed=result,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except discord.HTTPException:
            logger.exception("Could not complete chat event in channel %s", channel_id)
        finally:
            if self.chat_events.get(channel_id) is session:
                del self.chat_events[channel_id]

    async def handle_settings_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Server settings can only be changed in a server.",
                mention_author=False,
            )
            return
        await message.reply(
            view=ServerSettingsView(self, message.guild.id),
            mention_author=False,
        )

    async def handle_permission_command(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None:
            await message.reply(
                "Command permissions can only be configured in a server.",
                mention_author=False,
            )
            return
        permissions = member_guild_permissions(message.author)
        if permissions is None or not permissions.manage_guild:
            await message.reply(
                "You need the Manage Server permission to configure command access.",
                mention_author=False,
            )
            return
        match = PERMISSION_COMMAND_PATTERN.fullmatch(message.content)
        if match is None:
            await message.reply(
                "Usage: `v!permission <role id>`, `v!permission off`, or "
                "`v!permission` to view the current role.",
                mention_author=False,
            )
            return

        guild_key = str(guild.id)
        argument = match.group(1)
        if argument is None:
            role_id = self.command_permissions.get(guild_key)
            state = f"<@&{role_id}> (`{role_id}`)" if role_id else "not set"
            await message.reply(
                f"Command access role: {state}.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        updated_permissions = dict(self.command_permissions)
        if argument.casefold() == "off":
            if guild_key not in updated_permissions:
                await message.reply(
                    "No command access role is set for this server.",
                    mention_author=False,
                )
                return
            updated_permissions.pop(guild_key)
            confirmation = "Command role access turned off."
        else:
            role_id = int(argument)
            role = guild.get_role(role_id)
            if role is None or role_id == guild.id:
                await message.reply(
                    "That role ID is not a role in this server.",
                    mention_author=False,
                )
                return
            updated_permissions[guild_key] = role_id
            confirmation = (
                f"Members with <@&{role_id}> can now use the protected commands."
            )

        try:
            save_command_permissions(
                self.command_permissions_path,
                updated_permissions,
            )
        except ValueError:
            logger.exception(
                "Could not save command permissions for guild %s",
                guild.id,
            )
            await message.reply(
                "I couldn't save command permissions. Check the bot logs.",
                mention_author=False,
            )
            return
        self.command_permissions = updated_permissions
        await message.reply(
            confirmation,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def handle_command_lock_command(
        self,
        message: discord.Message,
        *,
        locked: bool,
    ) -> None:
        guild = message.guild
        if guild is None:
            await message.reply(
                "Command access can only be changed in a server.",
                mention_author=False,
            )
            return
        permissions = member_guild_permissions(message.author)
        if permissions is None or not permissions.administrator:
            await message.reply(
                "Only server administrators can enable or disable commands.",
                mention_author=False,
            )
            return

        try:
            self.set_commands_locked(guild.id, locked)
        except ValueError:
            logger.exception(
                "Could not update command lock for guild %s",
                guild.id,
            )
            await message.reply(
                "I couldn't update command access. Check the bot logs.",
                mention_author=False,
            )
            return

        if locked:
            confirmation = (
                "Bot commands are now disabled for this server. "
                "Automatic bot features will continue. "
                "An administrator can run `v!con` to re-enable commands."
            )
        else:
            confirmation = "Bot commands are enabled again for this server."
        await message.reply(confirmation, mention_author=False)

    async def save_flagged_pokemon_spawn_image(
        self, url: str, name: str, message_id: int
    ) -> None:
        display_name = display_pokemon_name(name)
        if normalize_pokemon_alias(display_name) not in load_pokemon_confidence_names(
            self.pokemon_confidence_path
        ):
            return
        image_http = self.image_http
        if image_http is None:
            logger.error("HTTP client is unavailable; cannot save flagged spawn image")
            return
        try:
            image_bytes, content_type = await download_image(image_http, url)
            extension = mimetypes.guess_extension(content_type, strict=False) or ".img"
            slug = re.sub(
                r"[^a-z0-9]+",
                "-",
                normalize_pokemon_alias(display_name),
            ).strip("-")
            destination = self.pokemon_confidence_review_dir
            destination.mkdir(parents=True, exist_ok=True)
            image_path = destination / f"{message_id}_{slug or 'pokemon'}{extension}"
            image_path.write_bytes(image_bytes)
            logger.info(
                "Saved flagged %s spawn image to %s",
                display_name,
                image_path,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
            logger.exception(
                "Could not save flagged spawn image for message %s",
                message_id,
            )

    async def report_low_accuracy(
        self, message: discord.Message, name: str, confidence: float
    ) -> None:
        guild = message.guild
        channel_ids = [RECOGNITION_ALERT_CHANNEL_ID]
        configured_channel_id = (
            self.low_accuracy_channels.get(str(guild.id)) if guild else None
        )
        if (
            configured_channel_id is not None
            and configured_channel_id not in channel_ids
        ):
            channel_ids.append(configured_channel_id)

        content = (
            f"<@{RECOGNITION_ALERT_USER_ID}> ⚠️ Low accuracy: "
            f"**{display_pokemon_name(name)}** at "
            f"{confidence:.2f}% (below {LOW_ACCURACY_THRESHOLD}%)\n"
            f"{message.jump_url}"
        )
        allowed_mentions = discord.AllowedMentions(
            users=[discord.Object(id=RECOGNITION_ALERT_USER_ID)],
            roles=False,
            everyone=False,
            replied_user=False,
        )
        for channel_id in channel_ids:
            channel = self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load low accuracy report channel %s",
                        channel_id,
                    )
                    continue
            if not is_messageable_channel(channel):
                logger.warning(
                    "Configured low-accuracy channel %s cannot receive messages",
                    channel_id,
                )
                continue
            try:
                await channel.send(
                    content,
                    allowed_mentions=allowed_mentions,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not send low accuracy report for message %s to channel %s",
                    message.id,
                    channel_id,
                )

    async def handle_low_accuracy_command(self, message: discord.Message) -> None:
        permissions = member_guild_permissions(message.author)
        if message.guild is None or permissions is None or not permissions.manage_guild:
            await message.reply(
                "You need the Manage Server permission to use this.",
                mention_author=False,
            )
            return
        argument = message.content.split(maxsplit=1)[1].strip() if " " in message.content.strip() else ""
        key = str(message.guild.id)
        if argument.lower() in ("off", "reset", "clear"):
            self.low_accuracy_channels.pop(key, None)
            save_low_accuracy_channels(self.low_accuracy_path, self.low_accuracy_channels)
            await message.reply("Low accuracy recorder turned off.", mention_author=False)
            return
        if message.channel_mentions:
            target = message.channel_mentions[0]
            self.low_accuracy_channels[key] = target.id
            save_low_accuracy_channels(self.low_accuracy_path, self.low_accuracy_channels)
            await message.reply(
                f"Low accuracy recorder on. Spawns scoring under {LOW_ACCURACY_THRESHOLD}% "
                f"will be linked in {target.mention}.",
                mention_author=False,
            )
            return
        current = self.low_accuracy_channels.get(key)
        state = f"<#{current}>" if current else "off"
        await message.reply(
            f"Low accuracy recorder: {state}\n"
            "Use `v!lowaccuracy #channel` to set it or `v!lowaccuracy off` to disable.",
            mention_author=False,
        )

    async def handle_afk_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "AFK settings can only be used in a server.",
                mention_author=False,
            )
            return
        await message.reply(
            view=AFKSettingsView(self, message.guild.id, message.author.id),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def handle_api_status(self, message: discord.Message) -> None:
        now = time.monotonic()
        recent = [
            record
            for record in self.recognition_durations
            if now - record[0] <= API_STATUS_WINDOW_SECONDS
        ]
        self.recognition_durations = deque(
            (
                record
                for record in self.recognition_durations
                if now - record[0] <= API_STATUS_WINDOW_SECONDS
            ),
            maxlen=1000,
        )
        active_incenses = self.current_active_incenses()
        max_requests = self.config.max_concurrent_vision_requests
        if self.pending_vision_requests:
            activity = "🟠 Busy"
        elif self.active_vision_requests >= max_requests:
            activity = "🟠 At capacity"
        elif not recent:
            activity = "🟢 Low Activity"
        else:
            activity = "🟢 Active"
        inference = [record[1] for record in recent]
        response = [record[2] for record in recent]

        def format_duration(seconds: float | None) -> str:
            return f"{seconds * 1000:.0f} ms" if seconds is not None else "—"

        inference_fastest = format_duration(min(inference)) if inference else "—"
        inference_slowest = format_duration(max(inference)) if inference else "—"
        inference_average = (
            format_duration(sum(inference) / len(inference)) if inference else "—"
        )
        inference_latest = format_duration(inference[-1]) if inference else "—"
        response_fastest = format_duration(min(response)) if response else "—"
        response_slowest = format_duration(max(response)) if response else "—"
        response_average = (
            format_duration(sum(response) / len(response)) if response else "—"
        )
        response_latest = format_duration(response[-1]) if response else "—"
        openai_backend = self.openai is not None
        model = self.config.openai_model if openai_backend else "SIFT reference matching"
        backend = "SIFT + OpenAI fallback" if openai_backend else "SIFT only"

        embed = discord.Embed(title="API Status", color=discord.Color.blurple())
        fields = (
            ("Activity", activity),
            ("Active Incense", str(len(active_incenses))),
            ("Store (latest)", "—"),
            ("Store (avg)", "—"),
            ("JSON load", "—"),
            ("CSV load", "Not used"),
            ("Inference Fastest", inference_fastest),
            ("Inference Slowest", inference_slowest),
            ("Inference Avg", inference_average),
            ("Inference Latest", inference_latest),
            ("Response Fastest", response_fastest),
            ("Response Slowest", response_slowest),
            ("Response Avg", response_average),
            ("Response Latest", response_latest),
            ("Pokémons Named", str(self.pokemon_named_count)),
        )
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
        embed.set_footer(
            text=(
                f"Model: {model} | Backend: {backend} | "
                f"Threads: {threading.active_count()} | Window: 5 min rolling | "
                f"Load: {self.active_vision_requests}/{max_requests} "
                f"(+{self.pending_vision_requests} waiting) | "
                f"Failed: {self.failed_recognition_count} | "
                "Incense is estimated"
            )
        )
        await message.reply(embed=embed, mention_author=False)

    async def on_raw_message_edit(
        self, payload: discord.RawMessageUpdateEvent
    ) -> None:
        await self.daycare.handle_raw_edit(payload)

    async def on_message_edit(
        self, _before: discord.Message, after: discord.Message
    ) -> None:
        del _before
        # Pokétwo sometimes adds the spawn image or text by editing the message.
        poketwo_catch = after.author.id == self.config.poketwo_bot_id
        catch_detection_report = has_catch_detection_embed(after)
        parsed_catch_report = (
            is_automated_message(after)
            and not poketwo_catch
            and profile_catch_user_id(after) is not None
        )
        if not poketwo_catch and not catch_detection_report and not parsed_catch_report:
            return
        self.track_profile_catch(after)
        await self.track_profile_box_shiny(after)
        await self.handle_catch_starboard(after)
        incense_action = self.track_incense_command(after)
        if incense_action == "buy":
            await self.pause_confirmed_incense_purchase(after)
        if not self.is_allowed_channel(after.channel):
            return
        text = message_text(after)
        if SPAWN_PATTERN.search(text):
            if poketwo_catch:
                self.pokeball_drops.record_spawn(after)
            await self.handle_spawn(after)

    async def handle_grab_command(
        self, message: discord.Message, silent_h_mode: bool = False
    ) -> None:
        prefix = "h!" if silent_h_mode else "v!"
        usage = f"Reply to a Pokémon list (like a `v!r search` result) with `{prefix}grab`."
        if message.guild is None or message.reference is None:
            await message.reply(usage, mention_author=False)
            return
        referenced = message.reference.resolved
        if not isinstance(referenced, discord.Message):
            reference_id = message.reference.message_id
            if reference_id is None:
                await message.reply(
                    "I couldn't read the message you replied to.",
                    mention_author=False,
                )
                return
            try:
                referenced = await message.channel.fetch_message(reference_id)
            except discord.HTTPException:
                await message.reply(
                    "I couldn't read the message you replied to.",
                    mention_author=False,
                )
                return
        texts = RESERVE_LIST_CACHE.get(referenced.id)
        if texts is None:
            texts = message_list_texts(referenced)
        entries = parse_grab_entries(texts)
        if not entries:
            await message.reply(usage, mention_author=False)
            return
        view = GrabListView(
            self,
            message.guild.id,
            message.author.id,
            entries,
            silent_h_mode=silent_h_mode,
        )
        response = await message.reply(
            embeds=view.current_embeds(),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
            mention_author=False,
        )
        view.message = response

    async def report_spawn_evidence(
        self, command: discord.Message, catch: discord.Message, species: str
    ) -> list[tuple[str, set[int]]] | None:
        spawn = None
        async for previous in command.channel.history(limit=500, before=catch):
            if (
                previous.author.id == self.config.poketwo_bot_id
                and SPAWN_PATTERN.search(message_text(previous))
            ):
                spawn = previous
                break
        if spawn is None:
            return None
        evidence: list[tuple[str, set[int]]] = []
        async for reply in command.channel.history(limit=500, after=spawn, before=command):
            if (
                reply.author.bot
                and reply.author.id != self.config.poketwo_bot_id
                and reply.webhook_id is None
                and reply.reference is not None
                and reply.reference.message_id == spawn.id
            ):
                text = message_text(reply)
                form = report_spawn_form(text, species)
                if form is not None:
                    is_vivillon = self.user is not None and reply.author.id == self.user.id
                    evidence.append((form, set() if is_vivillon else report_reserve_pings(text)))
        return evidence

    async def handle_reserve_report(self, message: discord.Message) -> None:
        usage = "Reply to the Pokétwo catch message with `v!report`."
        if message.guild is None or message.reference is None:
            await message.reply(usage, mention_author=False)
            return
        reference = message.reference
        if reference.channel_id != message.channel.id or reference.message_id is None:
            await message.reply(usage, mention_author=False)
            return
        catch = reference.resolved
        if not isinstance(catch, discord.Message):
            try:
                catch = await message.channel.fetch_message(reference.message_id)
            except discord.HTTPException:
                await message.reply("I couldn't read the catch message.", mention_author=False)
                return
        details = (
            parse_catch_details(message_text(catch))
            if catch.author.id == self.config.poketwo_bot_id
            else None
        )
        if details is None or details.user_id is None:
            await message.reply(usage, mention_author=False)
            return
        if details.user_id == message.author.id:
            await message.reply("You can't report your own catch.", mention_author=False)
            return

        caught_name = re.sub(
            r"^(?:gigantamax|gmax)\s+", "", details.pokemon, flags=re.IGNORECASE
        )
        has_local_reserve = message.author.id in reserved_user_ids_for_pokemon(
            self.reservations, message.guild.id, caught_name,
            additional_names=(details.pokemon,),
        )
        needs_form = bool(custom_forms_for_species(caught_name))
        evidence: list[tuple[str, set[int]]] = []
        if needs_form or not has_local_reserve:
            try:
                found_evidence = await self.report_spawn_evidence(message, catch, caught_name)
            except discord.HTTPException:
                logger.exception("Could not read spawn history for catch %s", catch.id)
                await message.reply(
                    "I couldn't read the spawn history to verify the reserve.",
                    mention_author=False,
                )
                return
            if found_evidence is None:
                await message.reply(
                    "I couldn't find the corresponding spawn to verify the reserve.",
                    mention_author=False,
                )
                return
            evidence = found_evidence
        forms = {name for name, _ in evidence if name.casefold() != caught_name.casefold()}
        if len(forms) > 1:
            await message.reply(
                "The naming bots gave conflicting form identifications; I can't verify this report.",
                mention_author=False,
            )
            return
        if needs_form and not evidence:
            await message.reply(
                "I couldn't identify the exact form from a naming bot's spawn reply.",
                mention_author=False,
            )
            return
        form_name = next(iter(forms), caught_name)
        has_local_reserve = message.author.id in reserved_user_ids_for_pokemon(
            self.reservations, message.guild.id, form_name,
            additional_names=(caught_name, details.pokemon),
        )
        has_spawn_reserve = any(message.author.id in users for _, users in evidence)
        if not has_local_reserve and not has_spawn_reserve:
            await message.reply(
                "You don't have this Pokémon reserved, or no reserve ping was found on the spawn.",
                mention_author=False,
            )
            return
        price = report_category_price(
            self.reserve_categories, message.guild.id, form_name,
            gigantamax=details.gigantamax,
        )
        if price is None:
            try:
                price = report_spawn_price(form_name)
                if price is None and form_name.casefold() != caught_name.casefold():
                    price = report_spawn_price(caught_name)
            except (OSError, ValueError, KeyError, TypeError):
                logger.exception("Could not load report spawn chances")
                await message.reply(
                    "I couldn't load the spawn-rate data. Check the bot logs.",
                    mention_author=False,
                )
                return
        if price is None:
            await message.reply(
                "No spawn-rate price is available for this Pokémon.", mention_author=False
            )
            return
        try:
            destination = self.get_channel(RESERVE_REPORT_CHANNEL_ID)
            if destination is None:
                destination = await self.fetch_channel(RESERVE_REPORT_CHANNEL_ID)
            if not isinstance(destination, (discord.TextChannel, discord.Thread)) or (
                destination.guild.id != message.guild.id
            ):
                await message.reply(
                    "The report channel isn't available in this server.",
                    mention_author=False,
                )
                return
            shown_name = f"Gigantamax {form_name}" if details.gigantamax else form_name
            await destination.send(
                f"<@{details.user_id}> hey you stole a reserved Pokémon\n"
                f"Pokémon: {shown_name}\n"
                f"PC: {price:,} PC\n"
                f"<@{details.user_id}> trade <@{message.author.id}> "
                f"in <#{RESERVE_REPORT_TRADE_THREAD_ID}>\n"
                f"{catch.jump_url}",
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False, replied_user=False
                ),
            )
        except discord.HTTPException:
            logger.exception("Could not send reserve report for catch %s", catch.id)
            await message.reply(
                "I couldn't send the report. Check the bot's channel permissions.",
                mention_author=False,
            )
            return
        await message.reply("Report sent.", mention_author=False)

    async def handle_ping_command(self, message: discord.Message) -> None:
        started_at = time.perf_counter()
        response = await message.reply("....loading", mention_author=False)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        await response.edit(content=f"{elapsed_ms}ms")

    async def confirm_pokemon_name(
        self, message: discord.Message, name: str
    ) -> str | None:
        """Return the name to use, asking the user when it looks misspelled.

        Returns None for unknown names or when the user declines or times out.
        """
        name = canonicalize_pokemon_name(name)
        if is_known_pokemon_name(name):
            return name
        suggestion = suggest_pokemon_name(name)
        if suggestion is None:
            await message.reply(
                f"**{name}** is not a valid Pokémon name.",
                mention_author=False,
            )
            return None
        view = NameSuggestionView(message.author.id)
        prompt = await message.reply(
            f"Do you mean **{suggestion}**?",
            view=view,
            mention_author=False,
        )
        await view.wait()
        confirmed = view.confirmed is True
        if view.confirmed is None:
            try:
                await prompt.edit(content="Timed out, nothing was added.", view=None)
            except discord.HTTPException:
                pass
        return suggestion if confirmed else None

    async def handle_shinyhunt_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Shiny hunts can only be added in a server.",
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!sh\s*", message.content, re.IGNORECASE):
            pokemon_names = shinyhunt_pokemon_for_user(
                self.shinyhunters,
                message.guild.id,
                message.author.id,
            )
            if pokemon_names:
                response = format_shinyhunt_status(pokemon_names[0])
            else:
                response = "You are not currently Shinyhunting any Pokémon"
            await message.reply(response, mention_author=False)
            return

        if re.fullmatch(r"v!sh\s+clear\s+all\s*", message.content, re.IGNORECASE):
            if not member_is_administrator(message.author):
                await message.reply(
                    "Only server administrators can clear everyone's shinyhunts.",
                    mention_author=False,
                )
                return
            await message.reply(
                "Are you sure you want to clear everyone's shinyhunts in this server?",
                view=ClearShinyhuntsView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!sh\s+clear\s*", message.content, re.IGNORECASE):
            updated_shinyhunters, cleared = clear_shinyhunter(
                self.shinyhunters,
                message.guild.id,
                message.author.id,
            )
            if cleared:
                try:
                    save_reservations(self.shinyhunt_path, updated_shinyhunters)
                except ValueError:
                    logger.exception("Could not save shiny-hunt clearing")
                    await message.reply(
                        "I couldn't clear that shiny hunt. Check the bot logs.",
                        mention_author=False,
                    )
                    return
                self.shinyhunters = updated_shinyhunters
            await message.reply(
                "Your shinyhunt has been cleared.",
                mention_author=False,
            )
            return

        remove_match = re.match(
            r"^v!sh\s+remove(?:\s|$)",
            message.content,
            re.IGNORECASE,
        )
        if remove_match is not None:
            pokemon_name = parse_shinyhunt_remove_command(message.content)
            if pokemon_name is None:
                await message.reply(
                    "Usage: `v!sh remove <pokemon>`",
                    mention_author=False,
                )
                return

            updated_shinyhunters, removed = remove_shinyhunter(
                self.shinyhunters,
                message.guild.id,
                pokemon_name,
                message.author.id,
            )
            if not removed:
                await message.reply(
                    f"You are not currently shinyhunting {pokemon_name}.",
                    mention_author=False,
                )
                return
            try:
                save_reservations(self.shinyhunt_path, updated_shinyhunters)
            except ValueError:
                logger.exception("Could not save shiny-hunt removal")
                await message.reply(
                    "I couldn't remove that shiny hunt. Check the bot logs.",
                    mention_author=False,
                )
                return

            self.shinyhunters = updated_shinyhunters
            await message.reply(
                f"You are no longer shinyhunting {format_shinyhunt_name(pokemon_name)}.",
                mention_author=False,
            )
            return

        pokemon_name = parse_shinyhunt_command(message.content)
        if pokemon_name is None:
            await message.reply(
                "Usage: `v!sh <pokemon>`, `v!sh remove <pokemon>`, or "
                "`v!sh clear` or `v!sh clear all` (one Pokémon per command)",
                mention_author=False,
            )
            return

        pokemon_name = await self.confirm_pokemon_name(message, pokemon_name)
        if pokemon_name is None:
            return

        updated_shinyhunters = add_shinyhunter(
            self.shinyhunters,
            message.guild.id,
            pokemon_name,
            message.author.id,
        )
        try:
            save_reservations(self.shinyhunt_path, updated_shinyhunters)
        except ValueError:
            logger.exception("Could not save shiny-hunt registrations")
            await message.reply(
                "I couldn't save that shiny hunt. Check the bot logs.",
                mention_author=False,
            )
            return
        self.shinyhunters = updated_shinyhunters
        await message.reply(
            format_shinyhunt_confirmation(pokemon_name),
            mention_author=False,
        )

    async def handle_type_ping_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Type pings can only be used in a server.",
                mention_author=False,
            )
            return
        if TYPE_PING_CLEAR_ALL_PATTERN.fullmatch(message.content) is not None:
            if not member_is_administrator(message.author):
                await message.reply(
                    "Only server administrators can clear everyone's type pings.",
                    mention_author=False,
                )
                return
            await message.reply(
                "Are you sure you want to clear everyone's type pings in this server?",
                view=ClearTypePingsView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
            return
        if TYPE_PING_COMMAND_PATTERN.fullmatch(message.content) is None:
            await message.reply(
                "Usage: `v!tp`, `v!typeping`, `v!tp clear all`, or "
                "`v!typeping clear all`",
                mention_author=False,
            )
            return

        view = TypePingView(self, message.guild.id, message.author.id)
        await message.reply(
            embed=view.embed,
            view=view,
            mention_author=False,
        )

    async def handle_collection_command(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Collections can only be used in a server.",
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!cl\s+list\s*", message.content, re.IGNORECASE):
            pokemon_names = collection_pokemon_for_user(
                self.collections,
                message.guild.id,
                message.author.id,
            )
            await reply_with_reservation_embeds(
                message,
                format_collection_embeds(pokemon_names),
            )
            return
        if re.match(r"^v!cl\s+list(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply("Usage: `v!cl list`", mention_author=False)
            return

        if re.fullmatch(r"v!cl\s+clear\s+all\s*", message.content, re.IGNORECASE):
            if not member_is_administrator(message.author):
                await message.reply(
                    "Only server administrators can clear everyone's collection.",
                    mention_author=False,
                )
                return
            await message.reply(
                "Are you sure you want to clear everyone's collection in this server?",
                view=ClearCollectionView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!cl\s+clear\s*", message.content, re.IGNORECASE):
            updated_collections = clear_user_collection(
                self.collections,
                message.guild.id,
                message.author.id,
            )
            try:
                save_reservations(self.collection_path, updated_collections)
            except ValueError:
                logger.exception("Could not clear Pokémon collection")
                await message.reply(
                    "I couldn't clear your collection. Check the bot logs.",
                    mention_author=False,
                )
                return
            self.collections = updated_collections
            await message.reply(
                "Your Pokémon collection has been cleared.",
                mention_author=False,
            )
            return
        if re.match(r"^v!cl\s+clear(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply(
                "Usage: `v!cl clear` or `v!cl clear all`",
                mention_author=False,
            )
            return

        if re.match(r"^v!cl\s+remove(?:\s|$)", message.content, re.IGNORECASE):
            pokemon_names = parse_collection_pokemon_command(
                message.content,
                COLLECTION_REMOVE_PATTERN,
            )
            if pokemon_names is None:
                await message.reply(
                    "Usage: `v!cl remove <pokemon>, <pokemon>`",
                    mention_author=False,
                )
                return

            updated_collections, removed_names, missing_names = (
                remove_collection_pokemon(
                    self.collections,
                    message.guild.id,
                    pokemon_names,
                    message.author.id,
                )
            )
            if not removed_names:
                await message.reply(
                    f"Those Pokémon were not found in your collection: "
                    f"{', '.join(missing_names)}.",
                    mention_author=False,
                )
                return

            try:
                save_reservations(self.collection_path, updated_collections)
            except ValueError:
                logger.exception("Could not remove Pokémon from collection")
                await message.reply(
                    "I couldn't update your collection. Check the bot logs.",
                    mention_author=False,
                )
                return

            self.collections = updated_collections
            response = f"Removed {', '.join(removed_names)} from your collection."
            if missing_names:
                response += f" Not found: {', '.join(missing_names)}."
            await message.reply(response, mention_author=False)
            return

        pokemon_names = parse_collection_add_command(message.content)
        if pokemon_names is None:
            await message.reply(
                "Usage: `v!cl add <pokemon>, <pokemon>`, "
                "`v!cl remove <pokemon>, <pokemon>`, `v!cl list`, or `v!cl clear`",
                mention_author=False,
            )
            return

        confirmed_names: list[str] = []
        for requested_name in pokemon_names:
            confirmed_name = await self.confirm_pokemon_name(message, requested_name)
            if confirmed_name is not None and confirmed_name.casefold() not in {
                name.casefold() for name in confirmed_names
            }:
                confirmed_names.append(confirmed_name)
        pokemon_names = confirmed_names
        if not pokemon_names:
            return

        new_names, already_added_names = split_collection_add_names(
            self.collections,
            message.guild.id,
            pokemon_names,
            message.author.id,
        )
        if not new_names:
            await message.reply(
                format_collection_add_confirmation([], already_added_names),
                mention_author=False,
            )
            return

        updated_collections = add_collection_pokemon(
            self.collections,
            message.guild.id,
            new_names,
            message.author.id,
        )
        try:
            save_reservations(self.collection_path, updated_collections)
        except ValueError:
            logger.exception("Could not save Pokémon collection")
            await message.reply(
                "I couldn't save your collection. Check the bot logs.",
                mention_author=False,
            )
            return

        self.collections = updated_collections
        await message.reply(
            format_collection_add_confirmation(new_names, already_added_names),
            mention_author=False,
        )

    async def handle_reserve_category_command(
        self,
        message: discord.Message,
    ) -> None:
        if message.guild is None:
            await message.reply(
                "Reserve categories can only be used in a server.",
                mention_author=False,
            )
            return
        if not has_reserve_manager_access(
            self,
            message.guild.id,
            message.author,
        ):
            await message.reply(
                "Only reserve managers or members with the configured "
                "command role can manage reserve categories.",
                mention_author=False,
            )
            return

        category_name = parse_add_reserve_category_command(message.content)
        if category_name is not None:
            if is_known_pokemon_name(category_name):
                await message.reply(
                    "A category name cannot be a Pokémon name.",
                    mention_author=False,
                )
                return
            updated_categories, added = add_reserve_category(
                self.reserve_categories,
                message.guild.id,
                category_name,
            )
            if not added:
                await message.reply(
                    f"Category `{category_name}` already exists.",
                    mention_author=False,
                )
                return
            try:
                save_reserve_categories(
                    self.reserve_categories_path,
                    updated_categories,
                )
            except ValueError:
                logger.exception("Could not save reserve categories")
                await message.reply(
                    "I couldn't save that category. Check the bot logs.",
                    mention_author=False,
                )
                return
            self.reserve_categories = updated_categories
            await message.reply(
                f"Category `{category_name.casefold()}` created.",
                mention_author=False,
            )
            return
        if re.match(r"^v!addcategory(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply(
                "Usage: `v!addcategory <name>`",
                mention_author=False,
            )
            return

        parsed_create = parse_create_reserve_category_command(message.content)
        if parsed_create is not None:
            category_name, pokemon_names = parsed_create
            category_key = reserve_category_storage_key(category_name)
            if category_key not in self.reserve_categories.get(
                str(message.guild.id),
                {},
            ):
                await message.reply(
                    f"Category `{category_name}` does not exist. "
                    f"Create it with `v!addcategory {category_name}` first.",
                    mention_author=False,
                )
                return
            invalid_names = [
                name for name in pokemon_names if not is_known_pokemon_name(name)
            ]
            if invalid_names:
                await message.reply(
                    f"Unknown Pokémon: {', '.join(invalid_names)}.",
                    mention_author=False,
                )
                return
            updated_categories, added_names, category_exists = (
                append_reserve_category_pokemon(
                    self.reserve_categories,
                    message.guild.id,
                    category_name,
                    pokemon_names,
                )
            )
            if not category_exists:
                await message.reply(
                    f"Category `{category_name}` does not exist.",
                    mention_author=False,
                )
                return
            if not added_names:
                await message.reply(
                    f"No new Pokémon were added to `{category_key}`.",
                    mention_author=False,
                )
                return
            try:
                save_reserve_categories(
                    self.reserve_categories_path,
                    updated_categories,
                )
            except ValueError:
                logger.exception("Could not save Pokémon in reserve category")
                await message.reply(
                    "I couldn't save those Pokémon. Check the bot logs.",
                    mention_author=False,
                )
                return
            self.reserve_categories = updated_categories
            await message.reply(
                f"Added {len(added_names)} Pokémon to `{category_key}`.",
                mention_author=False,
            )
            return
        if re.match(
            r"^v!categorycreate(?:\s|$)",
            message.content,
            re.IGNORECASE,
        ):
            await message.reply(
                "Usage: `v!categorycreate <categoryname> "
                "<pokemonname>, <pokemonname>`",
                mention_author=False,
            )
            return

        if LIST_RESERVE_CATEGORIES_PATTERN.fullmatch(message.content):
            embeds = format_reserve_category_embeds(
                self.reserve_categories,
                message.guild.id,
            )
            await reply_with_reservation_embeds(message, embeds)
            return
        if re.match(r"^v!categorylist(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply(
                "Usage: `v!categorylist`",
                mention_author=False,
            )
            return

        category_name = parse_delete_reserve_category_command(message.content)
        if category_name is not None:
            updated_categories, deleted = delete_reserve_category(
                self.reserve_categories,
                message.guild.id,
                category_name,
            )
            if not deleted:
                await message.reply(
                    f"Category `{category_name}` was not found.",
                    mention_author=False,
                )
                return
            try:
                save_reserve_categories(
                    self.reserve_categories_path,
                    updated_categories,
                )
            except ValueError:
                logger.exception("Could not delete reserve category")
                await message.reply(
                    "I couldn't delete that category. Check the bot logs.",
                    mention_author=False,
                )
                return
            self.reserve_categories = updated_categories
            await message.reply(
                f"Category `{reserve_category_storage_key(category_name)}` "
                "deleted. Existing reserves were not changed.",
                mention_author=False,
            )
            return
        if re.match(
            r"^v!(?:categorydelete|cd)(?:\s|$)",
            message.content,
            re.IGNORECASE,
        ):
            await message.reply(
                "Usage: `v!categorydelete <categoryname>` or "
                "`v!cd <categoryname>`",
                mention_author=False,
            )

    async def handle_reserve_command(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            await message.reply(
                "Reserve commands can only be used in a server.",
                mention_author=False,
            )
            return

        if re.fullmatch(r"v!r\s+list\s*", message.content, re.IGNORECASE):
            embeds = format_server_reservation_embeds(
                self.reservations,
                message.guild.id,
            )
            await reply_with_reservation_embeds(message, embeds)
            return
        if re.match(r"^v!r\s+list(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply("Usage: `v!r list`", mention_author=False)
            return

        member_match = re.fullmatch(
            r"v!r\s+<@!?(\d+)>\s*",
            message.content,
            re.IGNORECASE,
        )
        if (
            member_match is not None
            and int(member_match.group(1)) == message.author.id
        ):
            embeds = format_reservation_embeds(
                message.author.display_name,
                reserved_pokemon_for_user(
                    self.reservations,
                    message.guild.id,
                    message.author.id,
                ),
            )
            await reply_with_reservation_embeds(message, embeds)
            return

        if re.match(r"^v!r\s+search(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_search(message)
            return

        if not has_reserve_manager_access(
            self,
            message.guild.id,
            message.author,
        ):
            await message.reply(
                "Only reserve managers or members with the configured "
                "command role can add, remove, or clear reservations.",
                mention_author=False,
            )
            return
        if member_match is not None:
            await message.reply(
                "Use `v!r @you` to see your own reserves, or "
                "`v!r search @member` to see another member's reserves.",
                mention_author=False,
            )
            return

        if re.match(r"^v!r\s+(?:e|exchange)(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_exchange(message)
            return
        if re.match(r"^v!r\s+remove(?:\s|$)", message.content, re.IGNORECASE):
            await self.handle_reserve_remove(message)
            return
        if re.fullmatch(r"v!r\s+clear\s*", message.content, re.IGNORECASE):
            await message.reply(
                "Are you sure you want to clear all reserves?",
                view=ClearReservesView(
                    self,
                    message.guild.id,
                    message.author.id,
                ),
                mention_author=False,
            )
            return
        if re.match(r"^v!r\s+clear(?:\s|$)", message.content, re.IGNORECASE):
            await message.reply(
                "Usage: `v!r clear`",
                mention_author=False,
            )
            return
        if re.fullmatch(r"v!r\s+all\s*", message.content, re.IGNORECASE):
            paused_channels = []
            for channel_id in self.muted_poketwo_channels.copy():
                channel = message.guild.get_channel(channel_id)
                if channel is None:
                    channel = message.guild.get_thread(channel_id)
                if channel is not None and channel.guild.id == message.guild.id:
                    paused_channels.append((channel_id, channel))
            if not paused_channels:
                await message.reply(
                    "No paused channels in this server.",
                    mention_author=False,
                )
                return

            resumed = 0
            failed = 0
            for channel_id, channel in paused_channels:
                if await self.set_poketwo_blocked(channel, False):
                    self.muted_poketwo_channels.discard(channel_id)
                    resumed += 1
                else:
                    failed += 1
            if failed:
                response = (
                    f"Resumed Pokétwo in {resumed} channel(s); "
                    f"couldn't resume {failed} channel(s). Check the bot logs."
                )
            else:
                response = f"Resumed Pokétwo in {resumed} paused channel(s)."
            await message.reply(response, mention_author=False)
            return

        parsed_command = parse_reserve_add_command(message.content)
        if parsed_command is None or len(message.mentions) != 1:
            await message.reply(
                "Usage: `v!r add <pokemon>, <pokemon> @member` "
                "or `v!r add all <pokemon> @member`",
                mention_author=False,
            )
            return

        pokemon_names, target_id = parsed_command
        target = message.mentions[0]
        if target.id != target_id:
            await message.reply(
                "Please mention exactly one server member.",
                mention_author=False,
            )
            return

        pokemon_names, used_categories = expand_reserve_category_names(
            self.reserve_categories,
            message.guild.id,
            pokemon_names,
        )
        if not pokemon_names:
            await message.reply(
                f"Reserve category `{', '.join(used_categories)}` is empty.",
                mention_author=False,
            )
            return
        unknown_names = [
            name for name in pokemon_names if not is_known_pokemon_name(name)
        ]
        if unknown_names:
            await message.reply(
                f"Unknown Pokémon: {', '.join(unknown_names)}.",
                mention_author=False,
            )
            return
        org_store = cast(
            Callable[[], OrgReserves] | None,
            getattr(self, "org_store", None),
        )
        conflicting_category_names = []
        if org_store is not None:
            conflicting_category_names = [
                name
                for name in pokemon_names
                if org_store().category_owner_for(name, target.id) is not None
            ]
        if conflicting_category_names:
            await message.reply(
                "These Pokémon are reserved by another category claim: "
                f"{', '.join(conflicting_category_names)}.",
                mention_author=False,
            )
            return
        event_species = list(
            dict.fromkeys(
                canonicalize_pokemon_name(name[4:].strip())
                for name in pokemon_names
                if name.casefold().startswith("all ")
                and custom_forms_for_species(name[4:].strip())
            )
        )
        if event_species:
            await message.reply(
                "Choose whether to reserve only the event forms of "
                f"{', '.join(event_species)} or all forms, including the "
                "regular Pokémon.",
                view=ReserveAllFormsChoiceView(
                    self,
                    message.guild.id,
                    message.author.id,
                    target.id,
                    pokemon_names,
                    event_species,
                ),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        updated_reservations = {
            key: list(user_ids) for key, user_ids in self.reservations.items()
        }
        for pokemon_name in pokemon_names:
            key = reservation_key_for_command(message.guild.id, pokemon_name)
            user_ids = updated_reservations.setdefault(key, [])
            if target.id not in user_ids:
                user_ids.append(target.id)
        try:
            save_reservations(self.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not save Pokémon reservations")
            await message.reply(
                "I couldn't save that reservation. Check the bot logs.",
                mention_author=False,
            )
            return

        self.reservations = updated_reservations
        if used_categories:
            await message.reply(
                f"Category `{', '.join(used_categories)}` expanded to "
                f"{len(pokemon_names)} Pokémon and was added to "
                f"{target.mention}.",
                mention_author=False,
            )
            return
        display_names = ", ".join(
            (
                f"all forms of {name[len('all '):]}".capitalize()
                if name.casefold().startswith("all ")
                else name[0].upper() + name[1:]
            )
            for name in pokemon_names
        )
        await message.reply(
            f"Reserve {display_names} added to {target.mention}",
            mention_author=False,
        )

    async def handle_reserve_exchange(self, message: discord.Message) -> None:
        usage = (
            "Reply to a list like `@member pikachu, eevee` (one member per line; the `-` is optional) "
            "with `v!r e @owner`."
        )
        match = EXCHANGE_COMMAND_PATTERN.fullmatch(message.content.strip())
        if match is None or message.reference is None or message.guild is None:
            await message.reply(usage, mention_author=False)
            return
        source_id = int(match.group(1))

        referenced = message.reference.resolved
        if not isinstance(referenced, discord.Message):
            reference_id = message.reference.message_id
            if reference_id is None:
                await message.reply(
                    "I couldn't read the message you replied to.",
                    mention_author=False,
                )
                return
            try:
                referenced = await message.channel.fetch_message(reference_id)
            except discord.HTTPException:
                await message.reply(
                    "I couldn't read the message you replied to.",
                    mention_author=False,
                )
                return

        transfers = parse_exchange_list("\n".join(message_list_texts(referenced)))
        if not transfers:
            await message.reply(usage, mention_author=False)
            return

        _, _, skipped = exchange_reservations(
            self.reservations, message.guild.id, source_id, transfers
        )
        embed = format_exchange_embed(
            self.reservations, message.guild.id, source_id, transfers, skipped
        )
        await message.reply(
            embed=embed,
            view=ExchangeReservesView(
                self, message.guild.id, message.author.id, source_id, transfers
            ),
            allowed_mentions=discord.AllowedMentions.none(),
            mention_author=False,
        )

    async def handle_reserve_remove(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            await message.reply(
                "Reservations can only be removed in a server.",
                mention_author=False,
            )
            return

        parsed_command = parse_reserve_remove_command(message.content)
        if parsed_command is None:
            await message.reply(
                "Usage: `v!r remove <pokemon>[, <pokemon> ...] [@member]` "
                "or `v!r remove all <pokemon> [@member]`",
                mention_author=False,
            )
            return

        pokemon_names, target_id = parsed_command
        expected_mentions = 1 if target_id is not None else 0
        if len(message.mentions) != expected_mentions:
            await message.reply(
                "Usage: `v!r remove <pokemon>[, <pokemon> ...] [@member]` "
                "or `v!r remove all <pokemon> [@member]`",
                mention_author=False,
            )
            return
        target = message.mentions[0] if target_id is not None else None
        if target is not None and target.id != target_id:
            await message.reply(
                "Please mention exactly one server member.",
                mention_author=False,
            )
            return

        pokemon_names, used_categories = expand_reserve_category_names(
            self.reserve_categories,
            message.guild.id,
            pokemon_names,
        )
        if not pokemon_names:
            await message.reply(
                f"Reserve category `{', '.join(used_categories)}` is empty.",
                mention_author=False,
            )
            return

        updated_reservations, removed_names, missing_names = remove_reservations(
            self.reservations,
            message.guild.id,
            pokemon_names,
            target.id if target else None,
        )
        if not removed_names:
            names = ", ".join(pokemon_names)
            await message.reply(
                f"No reservation was found for {names}.",
                mention_author=False,
            )
            return

        try:
            save_reservations(self.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not save Pokémon reservation removal")
            await message.reply(
                "I couldn't save that removal. Check the bot logs.",
                mention_author=False,
            )
            return

        self.reservations = updated_reservations
        if used_categories:
            response = (
                f"Removed {len(removed_names)} Pokémon reservations from "
                f"category `{', '.join(used_categories)}`."
            )
            if target is not None:
                response = (
                    f"Removed {len(removed_names)} Pokémon reservations from "
                    f"category `{', '.join(used_categories)}` for "
                    f"{target.mention}."
                )
        else:
            response = format_remove_confirmation(
                ", ".join(removed_names),
                target.mention if target else None,
            )
        if missing_names:
            response += f". No reservation was found for {', '.join(missing_names)}"
        await message.reply(response, mention_author=False)

    async def handle_reserve_search(self, message: discord.Message) -> None:
        if message.guild is None:
            await message.reply(
                "Reservations can only be searched in a server.",
                mention_author=False,
            )
            return

        match = RESERVE_SEARCH_PATTERN.fullmatch(message.content)
        if match is None:
            await message.reply(
                "Usage: `v!r search <pokemon|@member>`",
                mention_author=False,
            )
            return

        query = match.group(1).strip()
        if message.mentions:
            member_match = re.fullmatch(r"<@!?(\d+)>", query)
            if (
                len(message.mentions) != 1
                or member_match is None
                or int(member_match.group(1)) != message.mentions[0].id
                or not isinstance(message.mentions[0], discord.Member)
            ):
                await message.reply(
                    "Usage: `v!r search <pokemon|@member>`",
                    mention_author=False,
                )
                return

            member = message.mentions[0]
            embeds = format_reservation_embeds(
                member.display_name,
                reserved_pokemon_for_user(
                    self.reservations,
                    message.guild.id,
                    member.id,
                ),
            )
            await reply_with_reservation_embeds(message, embeds)
            return

        pokemon_name = unicodedata.normalize("NFC", query)
        if len(pokemon_name) > 60 or not is_valid_pokemon_name(pokemon_name):
            await message.reply(
                "Usage: `v!r search <pokemon|@member>`",
                mention_author=False,
            )
            return
        if not is_known_pokemon_name(pokemon_name):
            await message.reply(
                f"**{pokemon_name}** is not a valid Pokémon name.",
                mention_author=False,
            )
            return

        if pokemon_name.casefold().startswith("all "):
            embeds = format_all_forms_reservation_embeds(
                self.reservations,
                message.guild.id,
                pokemon_name[4:].strip(),
            )
        else:
            embeds = format_pokemon_reserver_embeds(
                self.reservations,
                message.guild.id,
                pokemon_name,
            )
        await reply_with_reservation_embeds(message, embeds)

    async def handle_catch_starboard(self, message: discord.Message) -> None:
        if message.guild is None or message.id in self.handled_catch_ids:
            return
        details = parse_catch_details(message_text(message))
        if details is None:
            details = parse_catch_detection_details(message)
        if details is None:
            return
        category = starboard_category(details)
        normal_pokemon_catch = is_normal_starboard_pokemon(details.pokemon)
        if category is None and not normal_pokemon_catch:
            return

        settings = self.starboard_settings_for_guild(message.guild.id)
        posts = catch_starboard_destinations(details, settings)
        if not posts:
            logger.info(
                "No starboard destination configured for catch message %s in guild %s "
                "(category=%s, normal_starboard_match=%s)",
                message.id,
                message.guild.id,
                category,
                normal_pokemon_catch,
            )
            return

        self.handled_catch_ids[message.id] = None
        while len(self.handled_catch_ids) > 5000:
            del self.handled_catch_ids[next(iter(self.handled_catch_ids))]

        for channel_id, post_category in posts.items():
            channel = self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load starboard channel %s in guild %s",
                        channel_id,
                        message.guild.id,
                    )
                    continue
            if not is_messageable_channel(channel):
                logger.warning(
                    "Configured starboard channel %s cannot receive messages",
                    channel_id,
                )
                continue
            jump_url = (
                f"https://discord.com/channels/{message.guild.id}/"
                f"{message.channel.id}/{message.id}"
            )
            embed = format_starboard_embed(
                details,
                post_category,
                message.created_at,
                use_3d_shiny_model=(
                    details.shiny and channel_id == settings["shiny_channel"]
                ),
            )
            self.tint_embeds(message.guild, {"embed": embed})
            try:
                custom_thumbnail = custom_starboard_thumbnail_path(
                    details, post_category
                )
                if custom_thumbnail:
                    await channel.send(
                        embed=embed,
                        file=discord.File(
                            custom_thumbnail,
                            filename=custom_thumbnail.name,
                        ),
                        view=starboard_jump_view(jump_url),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await channel.send(
                        embed=embed,
                        view=starboard_jump_view(jump_url),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                logger.info(
                    "Posted catch message %s to starboard channel %s as %s",
                    message.id,
                    channel_id,
                    post_category,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not post catch message %s to starboard channel %s",
                    message.id,
                    channel_id,
                )

        shiny_channel_id = settings["shiny_channel"]
        if details.shiny and shiny_channel_id is not None:
            shiny_channel = self.get_channel(shiny_channel_id)
            if shiny_channel is None:
                try:
                    shiny_channel = await self.fetch_channel(shiny_channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load shinyboard channel %s in guild %s",
                        shiny_channel_id,
                        message.guild.id,
                    )
            if shiny_channel is not None and not is_renamable_channel(
                shiny_channel
            ):
                logger.warning(
                    "Configured shinyboard channel %s cannot be renamed",
                    shiny_channel_id,
                )
                shiny_channel = None
            channel_name = getattr(shiny_channel, "name", None)
            if not isinstance(channel_name, str):
                channel_name = None
            try:
                updated_name = self.increment_shinyboard_count(
                    message.guild.id,
                    channel_name,
                )
            except ValueError:
                logger.exception(
                    "Could not save shinyboard catch count for guild %s",
                    message.guild.id,
                )
                return
            if (
                shiny_channel is not None
                and updated_name is not None
                and updated_name != channel_name
            ):
                try:
                    await shiny_channel.edit(
                        name=updated_name,
                        reason="Update shiny catch count",
                    )
                except discord.HTTPException:
                    logger.warning(
                        "Could not rename shinyboard channel %s to %s",
                        shiny_channel_id,
                        updated_name,
                        exc_info=True,
                    )

    async def post_test_starboard(
        self,
        message: discord.Message,
        pokemon_name: str,
        *,
        category: str,
        form_name: str | None = None,
    ) -> None:
        if message.guild is None:
            return
        is_shiny = category == "shiny"
        settings = self.starboard_settings_for_guild(message.guild.id)
        details = CatchDetails(
            user_id=message.author.id,
            pokemon=display_pokemon_name(form_name or pokemon_name),
            level="Unknown",
            iv="Unknown",
            iv_value=None,
            gender=None,
            shiny=is_shiny,
            chain=None,
            gigantamax=False,
            missingno=False,
        )
        posts = catch_starboard_destinations(details, settings)
        if not posts:
            board_name = "Shinyboard or Vivillon Starboard" if is_shiny else "Normal Starboard"
            logger.warning(
                "Cannot post v!test preview for message %s: no %s destination "
                "is configured "
                "in guild %s",
                message.id,
                board_name,
                message.guild.id,
            )
            await message.reply(
                f"No {board_name} destination is configured. "
                "Choose a channel in `v!settings`.",
                mention_author=False,
            )
            return

        failed_channels: list[int] = []
        for channel_id, post_category in posts.items():
            channel = self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.exception(
                        "Could not load starboard channel %s in guild %s for v!test",
                        channel_id,
                        message.guild.id,
                    )
                    failed_channels.append(channel_id)
                    continue
            if not is_messageable_channel(channel):
                logger.warning(
                    "Configured starboard channel %s cannot receive messages",
                    channel_id,
                )
                failed_channels.append(channel_id)
                continue
            jump_url = (
                f"https://discord.com/channels/{message.guild.id}/"
                f"{message.channel.id}/{message.id}"
            )
            embed = format_starboard_embed(
                details,
                post_category,
                message.created_at,
                use_3d_shiny_model=(
                    is_shiny and channel_id == settings["shiny_channel"]
                ),
                test_preview=True,
            )
            self.tint_embeds(message.guild, {"embed": embed})
            try:
                custom_thumbnail = custom_starboard_thumbnail_path(
                    details, post_category
                )
                if custom_thumbnail:
                    await channel.send(
                        embed=embed,
                        file=discord.File(
                            custom_thumbnail,
                            filename=custom_thumbnail.name,
                        ),
                        view=starboard_jump_view(jump_url),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await channel.send(
                        embed=embed,
                        view=starboard_jump_view(jump_url),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                logger.info(
                    "Posted v!test preview for %s to starboard channel %s as %s",
                    pokemon_name,
                    channel_id,
                    post_category,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not post v!test preview for %s to starboard channel %s",
                    pokemon_name,
                    channel_id,
                )
                failed_channels.append(channel_id)
        if failed_channels:
            await message.reply(
                "I couldn't post the test preview to every configured starboard "
                f"channel ({', '.join(map(str, failed_channels))}). "
                "Check the bot logs and channel permissions.",
                mention_author=False,
            )

    async def send_recognition_failure_alert(
        self, source_message: discord.Message
    ) -> None:
        channel = self.get_channel(RECOGNITION_ALERT_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.fetch_channel(RECOGNITION_ALERT_CHANNEL_ID)
            except discord.HTTPException:
                logger.exception(
                    "Could not load recognition alert channel %s",
                    RECOGNITION_ALERT_CHANNEL_ID,
                )
                return
        if not is_messageable_channel(channel):
            logger.error(
                "Recognition alert channel %s cannot receive messages",
                RECOGNITION_ALERT_CHANNEL_ID,
            )
            return

        content = (
            f"<@{RECOGNITION_ALERT_USER_ID}> Vivillon couldn't confidently identify "
            f"the spawn in <#{source_message.channel.id}>.\n"
            f"Jump to the spawn: {source_message.jump_url}"
        )
        allowed_mentions = discord.AllowedMentions(
            users=[discord.Object(id=RECOGNITION_ALERT_USER_ID)],
            roles=False,
            everyone=False,
            replied_user=False,
        )
        try:
            await channel.send(content, allowed_mentions=allowed_mentions)
        except discord.HTTPException:
            logger.exception(
                "Could not send recognition alert for message %s to channel %s",
                source_message.id,
                RECOGNITION_ALERT_CHANNEL_ID,
            )

    async def handle_spawn(
        self,
        message: discord.Message,
        *,
        test_mode: bool = False,
        shiny_test_mode: bool = False,
    ) -> None:
        guild = message.guild
        if guild is None or self.premium_tier_for_guild(guild.id) is None:
            if test_mode:
                await message.reply(
                    "Spawn naming requires a premium tier. Run `v!premium` "
                    "to check this server's access.",
                    mention_author=False,
                )
            return
        guild_id = guild.id
        if not test_mode and message.guild:
            naming_settings = self.naming_settings_for_guild(message.guild.id)
            if not naming_settings["enabled"]:
                return
            try:
                self.shinyhunters = load_reservations(self.shinyhunt_path)
                self.collections = migrate_legacy_all_keys(
                    load_reservations(self.collection_path)
                )
                self.type_pings = load_type_pings(self.type_ping_path)
            except ValueError:
                logger.exception("Could not refresh spawn ping registrations")
                await message.reply(
                    "I couldn't load the current ping registrations. "
                    "Check the bot logs.",
                    mention_author=False,
                )
                return
        url = image_url(message)
        if not url:
            logger.warning("Image test or spawn message %s had no image", message.id)
            return
        if self.image_http is None:
            logger.error("HTTP client was not initialized")
            return
        if message.id in self.handled_spawn_ids:
            return
        self.handled_spawn_ids[message.id] = None
        while len(self.handled_spawn_ids) > 5000:
            del self.handled_spawn_ids[next(iter(self.handled_spawn_ids))]

        started = time.monotonic()
        self.pending_vision_requests += 1
        waiting_for_vision_slot = True
        name: str | None = None
        confidence = 0.0
        inference_seconds = 0.0
        try:
            try:
                await self.acquire_vision_capacity(guild_id)
                self.pending_vision_requests -= 1
                waiting_for_vision_slot = False
                try:
                    inference_started = time.monotonic()
                    for attempt in range(3):
                        try:
                            name, confidence = await recognize_pokemon(
                                url,
                                client=self.openai,
                                http=self.image_http,
                                model=self.config.openai_model,
                                detail=self.config.openai_image_detail,
                                matcher=self.image_matcher,
                            )
                            break
                        except NoMatchError:
                            raise
                        except (
                            aiohttp.ClientError,
                            asyncio.TimeoutError,
                            ValueError,
                            OpenAIError,
                        ):
                            if attempt == 2:
                                raise
                            await asyncio.sleep(0.1)
                    inference_seconds = time.monotonic() - inference_started
                finally:
                    await self.release_vision_capacity(guild_id)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                self.failed_recognition_count += 1
                logger.exception("Could not recognize spawn in message %s", message.id)
                await self.send_recognition_failure_alert(message)
                return
            except NoMatchError:
                self.failed_recognition_count += 1
                logger.info("No Pokémon match was verified for spawn %s", message.id)
                if test_mode:
                    await message.reply(
                        "I couldn't match that test image to a reference Pokémon.",
                        mention_author=False,
                    )
                else:
                    await self.send_recognition_failure_alert(message)
                return
            except OpenAIError:
                self.failed_recognition_count += 1
                logger.exception("Vision request failed for message %s", message.id)
                await self.send_recognition_failure_alert(message)
                return
        finally:
            if waiting_for_vision_slot:
                self.pending_vision_requests -= 1

        completed = time.monotonic()
        response_seconds = completed - started
        if response_seconds >= RECOGNITION_WINDOW_SECONDS:
            logger.warning(
                "SLOW recognition for spawn %s took %.2fs",
                message.id,
                response_seconds,
            )
        logger.info(
            "Recognized %s in %.2fs (message %s)",
            name or "nothing",
            response_seconds,
            message.id,
        )
        if not name:
            if not test_mode:
                self.failed_recognition_count += 1
            await self.send_recognition_failure_alert(message)
            return
        if (
            confidence <= LOW_ACCURACY_THRESHOLD
            and not test_mode
            and not shiny_test_mode
        ):
            append_pokemon_confidence(
                self.pokemon_confidence_path,
                display_pokemon_name(name),
                confidence,
            )
        if not test_mode and not shiny_test_mode:
            await self.save_flagged_pokemon_spawn_image(url, name, message.id)
        if confidence < LOW_ACCURACY_THRESHOLD:
            await self.report_low_accuracy(message, name, confidence)
        if not test_mode:
            self.pokemon_named_count += 1
            self.recognition_durations.append(
                (completed, inference_seconds, response_seconds)
            )
        thumbnail_name = name
        name = species_display_name(name)
        guess_name = shown_form_name(name, thumbnail_name)
        if is_missingno_name(name) and not test_mode:
            channel_id = getattr(message.channel, "id", None)
            if channel_id is not None:
                self.muted_poketwo_channels.add(channel_id)
            await message.reply(
                "Ping a staff member. Dont catch the pokemon.",
                mention_author=False,
            )
            if channel_id is not None:
                await self.set_poketwo_blocked(message.channel, True)
            return

        if message.guild and not test_mode:
            try:
                self.type_pings = load_type_pings(self.type_ping_path)
            except ValueError:
                logger.exception("Could not refresh type ping registrations")
                await message.reply(
                    "I couldn't load the current type ping registrations. "
                    "Check the bot logs.",
                    mention_author=False,
                )
                return

        reserved_user_ids = (
            reserved_user_ids_for_pokemon(
                self.reservations,
                message.guild.id,
                name,
                additional_names=(guess_name,),
            )
            if message.guild
            else []
        )
        shinyhunter_user_ids = (
            shinyhunter_user_ids_for_pokemon(
                self.shinyhunters,
                message.guild.id,
                name,
                additional_names=(guess_name,),
            )
            if message.guild
            else []
        )
        collection_user_ids = (
            collection_user_ids_for_pokemon(
                self.collections,
                message.guild.id,
                name,
                additional_names=(guess_name,),
            )
            if message.guild
            else []
        )
        type_ping_user_ids = (
            type_ping_user_ids_for_pokemon(
                self.type_pings,
                message.guild.id,
                pokemon_types_for(thumbnail_name, name),
            )
            if message.guild
            else []
        )
        if message.guild:
            shinyhunter_user_ids = [
                user_id
                for user_id in shinyhunter_user_ids
                if self.afk_settings_for_user(message.guild.id, user_id)[
                    "shinyhunt"
                ]
            ]
            collection_user_ids = [
                user_id
                for user_id in collection_user_ids
                if self.afk_settings_for_user(message.guild.id, user_id)[
                    "collection"
                ]
            ]
        naming_settings = (
            self.naming_settings_for_guild(message.guild.id)
            if message.guild
            else SERVER_NAMING_DEFAULTS
        )
        if test_mode:
            # Show the full spawn message, without pinging anyone.
            (
                reserved_user_ids,
                shinyhunter_user_ids,
                collection_user_ids,
                type_ping_user_ids,
            ) = [], [], [], []
            assisted = True
        else:
            if not naming_settings["enabled"]:
                return
            if naming_settings["only_pings"] and not (
                reserved_user_ids
                or shinyhunter_user_ids
                or collection_user_ids
                or type_ping_user_ids
            ):
                return
            assisted = naming_settings["assisted"]

        if test_mode:
            if shiny_test_mode:
                await self.post_test_starboard(
                    message,
                    name,
                    category="shiny",
                    form_name=thumbnail_name,
                )
            elif is_normal_starboard_pokemon(thumbnail_name):
                await self.post_test_starboard(
                    message,
                    name,
                    category="normal_pokemon",
                    form_name=thumbnail_name,
                )

        type_emojis = type_emoji_text(thumbnail_name, name)
        if type_emojis:
            card_files = catch_card_files(name, thumbnail_name) if assisted else []
            await reply_with_spawn_media(
                message,
                format_typed_spawn_reply(
                    name,
                    confidence,
                    POKETWO_COMMAND_BOT_ID,
                    type_emojis,
                    reserved_user_ids,
                    shinyhunter_user_ids,
                    collection_user_ids,
                    type_ping_user_ids,
                    assisted=assisted,
                    guess_name=guess_name,
                ),
                embed=format_pc_catch_embed(name, thumbnail_name) if assisted else None,
                files=card_files,
            )
            return

        is_fire_spawn = is_fire_icon_pokemon(name)
        is_water_spawn = is_water_icon_pokemon(name)
        is_normal_spawn = is_normal_icon_pokemon(name)
        is_electric_spawn = is_electric_icon_pokemon(name)
        is_grass_spawn = is_grass_icon_pokemon(name)
        is_ice_spawn = is_ice_icon_pokemon(name)
        if (
            is_fire_spawn
            or is_water_spawn
            or is_normal_spawn
            or is_electric_spawn
            or is_grass_spawn
            or is_ice_spawn
        ):
            reply = format_custom_type_spawn_reply(
                name,
                confidence,
                POKETWO_COMMAND_BOT_ID,
                reserved_user_ids,
                shinyhunter_user_ids,
                collection_user_ids,
                include_fire=is_fire_spawn,
                include_water=is_water_spawn,
                include_normal=is_normal_spawn,
                include_electric=is_electric_spawn,
                include_grass=is_grass_spawn,
                include_ice=is_ice_spawn,
                assisted=assisted,
                guess_name=guess_name,
                type_ping_user_ids=type_ping_user_ids,
            )
            companion_icon_filename = (
                fire_companion_icon_filename_for_pokemon(name)
                or water_companion_icon_filename_for_pokemon(name)
                or normal_companion_icon_filename_for_pokemon(name)
                or electric_companion_icon_filename_for_pokemon(name)
            )
            if assisted and companion_icon_filename:
                await message.reply(
                    reply,
                    embed=format_pc_catch_embed(name, thumbnail_name),
                    file=discord.File(
                        Path(__file__).with_name("assets") / companion_icon_filename,
                        filename=companion_icon_filename,
                    ),
                    mention_author=False,
                )
            else:
                card_files = catch_card_files(name, thumbnail_name) if assisted else []
                await reply_with_spawn_media(
                    message,
                    reply,
                    embed=format_pc_catch_embed(name, thumbnail_name) if assisted else None,
                    files=card_files,
                )
            return

        icon_filename = type_icon_filename_for_pokemon(name)
        if icon_filename:
            type_embed = format_type_spawn_embed(
                name,
                confidence,
                POKETWO_COMMAND_BOT_ID,
                icon_filename,
                assisted=assisted,
                guess_name=guess_name,
            )
            content_lines = [format_guess(name, confidence, guess_name)]
            content_lines.extend(
                format_spawn_mention_lines(
                    reserved_user_ids,
                    shinyhunter_user_ids,
                    collection_user_ids,
                    type_ping_user_ids,
                )
            )
            embeds = [type_embed]
            files = [
                discord.File(
                    Path(__file__).with_name("assets") / icon_filename,
                    filename=icon_filename,
                )
            ]
            if assisted:
                embeds.append(format_pc_catch_embed(name, thumbnail_name))
                files.extend(catch_card_files(name, thumbnail_name))
            await message.reply(
                content="\n".join(content_lines),
                embeds=embeds,
                files=files,
                mention_author=False,
            )
        else:
            card_files = catch_card_files(name, thumbnail_name) if assisted else []
            await reply_with_spawn_media(
                message,
                format_spawn_reply(
                    name,
                    confidence,
                    POKETWO_COMMAND_BOT_ID,
                    reserved_user_ids,
                    shinyhunter_user_ids,
                    collection_user_ids,
                    type_ping_user_ids,
                    assisted=assisted,
                    guess_name=guess_name,
                ),
                embed=format_pc_catch_embed(name, thumbnail_name) if assisted else None,
                files=card_files,
            )


def clear_guild_reservations(
    reservations: dict[str, list[int]],
    guild_id: int,
) -> dict[str, list[int]]:
    guild_prefix = f"{guild_id}:"
    return {
        key: list(user_ids)
        for key, user_ids in reservations.items()
        if not key.startswith(guild_prefix)
    }


class ExchangeReservesView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        source_id: int,
        transfers: list[tuple[int, list[str]]],
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.source_id = source_id
        self.transfers = transfers

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not has_reserve_manager_access(
                self.bot,
                self.guild_id,
                interaction.user,
            )
        ):
            await interaction.response.send_message(
                "Only the authorized command user can confirm this action.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_exchange(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated, _, _ = exchange_reservations(
            self.bot.reservations, self.guild_id, self.source_id, self.transfers
        )
        try:
            save_reservations(self.bot.reserve_path, updated)
        except ValueError:
            logger.exception("Could not save Pokémon reservation exchange")
            await interaction.response.send_message(
                "I couldn't save that exchange. Check the bot logs.",
                ephemeral=True,
            )
            return
        self.bot.reservations = updated
        self.stop()
        await interaction.response.edit_message(
            content="Reserves exchanged.", embed=None, view=None
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel_exchange(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.stop()
        await interaction.response.edit_message(
            content="Exchange cancelled.", embed=None, view=None
        )


class GrabEmojiModal(discord.ui.Modal, title="Custom emoji"):
    emojis = discord.ui.TextInput(
        label="Emojis (separate with commas)",
        placeholder="🔥, 💧, <:custom:123456789012345678>",
        required=False,
        max_length=500,
    )

    def __init__(self, view: "GrabListView") -> None:
        super().__init__()
        self.grab_view = view
        self.emojis.default = ", ".join(view.emojis) or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.grab_view.emojis = [
            emoji.strip() for emoji in str(self.emojis).split(",") if emoji.strip()
        ][:50]
        await self.grab_view.refresh(interaction)


class GrabAddReservesView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        pairs: list[tuple[str, int]],
        silent_h_mode: bool = False,
    ) -> None:
        super().__init__(timeout=180)
        self.silent_h_mode = silent_h_mode
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.pairs = pairs

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who clicked Add reserves can confirm this.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        org_store = cast(
            Callable[[], OrgReserves] | None,
            getattr(self.bot, "org_store", None),
        )
        conflicts = []
        if org_store is not None and not self.silent_h_mode:
            conflicts = [
                name
                for name, user_id in self.pairs
                if org_store().category_owner_for(name, user_id) is not None
            ]
        if conflicts:
            await interaction.response.send_message(
                "These Pokémon are reserved by another category claim: "
                f"{', '.join(conflicts)}.",
                ephemeral=True,
            )
            return
        if not self.silent_h_mode:
            updated = add_reservations_bulk(
                self.bot.reservations, self.guild_id, self.pairs
            )
            try:
                save_reservations(self.bot.reserve_path, updated)
            except ValueError:
                logger.exception("Could not save grabbed reservations")
                await interaction.response.send_message(
                    "I couldn't save those reserves. Check the bot logs.",
                    ephemeral=True,
                )
                return
            self.bot.reservations = updated
        self.stop()
        await interaction.response.edit_message(content="Adding reserves...", view=None)

        channel = interaction.channel
        if not is_messageable_channel(channel):
            logger.warning(
                "Could not post grabbed reserve confirmations: "
                "interaction channel is not messageable"
            )
            await interaction.edit_original_response(
                content="I couldn't post the reserve confirmations in this channel."
            )
            return
        no_pings = discord.AllowedMentions.none()
        try:
            for name, user_id in self.pairs:
                if self.silent_h_mode:
                    await channel.send(
                        f"h!r add {name} <@{user_id}>", allowed_mentions=no_pings
                    )
                    await asyncio.sleep(0.5)
                    continue
                await channel.send(
                    f"v!r add {name} <@{user_id}>", allowed_mentions=no_pings
                )
                await asyncio.sleep(0.5)
                await channel.send(
                    f"{grab_display_name(name)} added to <@{user_id}>",
                    allowed_mentions=no_pings,
                )
                await asyncio.sleep(0.5)
            await interaction.edit_original_response(content="Reserves added.")
        except discord.HTTPException:
            logger.exception("Could not post grabbed reserve confirmations")

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.stop()
        await interaction.response.edit_message(
            content="Add reserves cancelled.", view=None
        )


class GrabListView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        entries: list[tuple[str, list[int]]],
        silent_h_mode: bool = False,
    ) -> None:
        super().__init__(timeout=600)
        self.silent_h_mode = silent_h_mode
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.entries = entries
        self.ordered = False
        self.all_forms = False
        self.emojis: list[str] = []
        self.message: discord.Message | None = None
        self.sync_buttons()

    def current_embeds(self) -> list[discord.Embed]:
        lines = build_grab_lines(
            self.entries,
            ordered=self.ordered,
            all_forms=self.all_forms,
            emojis=self.emojis,
        )
        # One message can hold 6000 embed characters in total, so the list is
        # spread over as many embeds as needed instead of being paged.
        pages = paginate_grab_lines(lines, 2900)
        embeds = [
            discord.Embed(description=page, color=discord.Color.blurple())
            for page in pages[:2]
        ]
        embeds[-1].set_footer(text=f"{len(self.entries)} Pokémon")
        return embeds

    def sync_buttons(self) -> None:
        self.order_button.style = (
            discord.ButtonStyle.success if self.ordered else discord.ButtonStyle.secondary
        )
        self.all_forms_button.style = (
            discord.ButtonStyle.success
            if self.all_forms
            else discord.ButtonStyle.secondary
        )
        self.all_forms_button.label = "All forms on" if self.all_forms else "All forms off"
        self.emoji_button.style = (
            discord.ButtonStyle.success if self.emojis else discord.ButtonStyle.secondary
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        embeds = self.current_embeds()
        self.sync_buttons()
        await interaction.response.edit_message(embeds=embeds, view=self)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            logger.warning("Could not disable expired grab-list buttons")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who ran `v!grab` can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Order", style=discord.ButtonStyle.secondary, row=0)
    async def order_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.ordered = not self.ordered
        await self.refresh(interaction)

    @discord.ui.button(label="All forms off", style=discord.ButtonStyle.secondary, row=0)
    async def all_forms_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.all_forms = not self.all_forms
        await self.refresh(interaction)

    @discord.ui.button(label="Custom emoji", style=discord.ButtonStyle.secondary, row=0)
    async def emoji_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await interaction.response.send_modal(GrabEmojiModal(self))

    @discord.ui.button(label="Add reserves", style=discord.ButtonStyle.primary, row=0)
    async def add_reserves_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        if not isinstance(
            interaction.user,
            discord.Member,
        ) or not has_reserve_manager_access(
            self.bot,
            self.guild_id,
            interaction.user,
        ):
            await interaction.response.send_message(
                "Only reserve managers can add reserves.", ephemeral=True
            )
            return
        pairs = grab_reserve_pairs(self.entries, self.all_forms)
        if not pairs:
            await interaction.response.send_message(
                "Add reserves only works when the list has an @user behind each Pokémon.",
                ephemeral=True,
            )
            return
        assignments = "\n".join(
            f"{grab_display_name(name)} → <@{user_id}>" for name, user_id in pairs
        )
        if len(assignments) > 3800:
            assignments = assignments[:3800].rsplit("\n", 1)[0] + "\n…"
        await interaction.response.send_message(
            "Are you sure you want to add all reserves?",
            embed=discord.Embed(
                title="Reserves to add",
                description=assignments,
                color=discord.Color.blurple(),
            ),
            view=GrabAddReservesView(
                self.bot,
                self.guild_id,
                interaction.user.id,
                pairs,
                silent_h_mode=self.silent_h_mode,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Copy", style=discord.ButtonStyle.secondary, row=1)
    async def copy_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        lines = build_grab_lines(
            self.entries,
            ordered=self.ordered,
            all_forms=self.all_forms,
            emojis=self.emojis,
        )
        chunks = paginate_grab_lines(lines, 2000)
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


class NameSuggestionView(discord.ui.View):
    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=NAME_SUGGESTION_TIMEOUT_SECONDS)
        self.requester_id = requester_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who ran the command can answer this.",
                ephemeral=True,
            )
            return False
        return True

    async def _finish(
        self, interaction: discord.Interaction, confirmed: bool, text: str
    ) -> None:
        self.confirmed = confirmed
        await interaction.response.edit_message(content=text, view=None)
        self.stop()

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await self._finish(interaction, True, "Confirmed.")

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await self._finish(interaction, False, "Cancelled, nothing was added.")


class ReserveAllFormsChoiceView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
        target_id: int,
        pokemon_names: list[str],
        event_species: list[str],
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.target_id = target_id
        self.pokemon_names = pokemon_names
        self.event_species = event_species

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not has_reserve_manager_access(
                self.bot,
                self.guild_id,
                interaction.user,
            )
        ):
            await interaction.response.send_message(
                "Only the authorized command user can choose this reservation.",
                ephemeral=True,
            )
            return False
        return True

    async def _finish(
        self,
        interaction: discord.Interaction,
        *,
        event_forms_only: bool,
    ) -> None:
        names_to_add: list[str] = []
        for name in self.pokemon_names:
            if event_forms_only and name.casefold().startswith("all "):
                species_name = name[4:].strip()
                custom_forms = custom_forms_for_species(species_name)
                names_to_add.extend(custom_forms or [name])
            else:
                names_to_add.append(name)

        updated_reservations = {
            key: list(user_ids) for key, user_ids in self.bot.reservations.items()
        }
        for name in names_to_add:
            key = reservation_key_for_command(self.guild_id, name)
            user_ids = updated_reservations.setdefault(key, [])
            if self.target_id not in user_ids:
                user_ids.append(self.target_id)
        try:
            save_reservations(self.bot.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not save Pokémon reservations")
            await interaction.response.send_message(
                "I couldn't save that reservation. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.reservations = updated_reservations
        self.stop()
        choice = "event forms only" if event_forms_only else "all forms"
        await interaction.response.edit_message(
            content=(
                f"Reservation added ({choice} for "
                f"{', '.join(self.event_species)})."
            ),
            view=None,
        )

    @discord.ui.button(label="Event forms only", style=discord.ButtonStyle.primary)
    async def reserve_event_forms(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self._finish(interaction, event_forms_only=True)

    @discord.ui.button(label="All forms", style=discord.ButtonStyle.success)
    async def reserve_all_forms(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self._finish(interaction, event_forms_only=False)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        self.stop()
        await interaction.response.edit_message(
            content="Reservation cancelled.",
            view=None,
        )


class ClearReservesView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not has_reserve_manager_access(
                self.bot,
                self.guild_id,
                interaction.user,
            )
        ):
            await interaction.response.send_message(
                "Only the authorized command user can confirm this action.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated_reservations = clear_guild_reservations(
            self.bot.reservations,
            self.guild_id,
        )
        try:
            save_reservations(self.bot.reserve_path, updated_reservations)
        except ValueError:
            logger.exception("Could not clear Pokémon reservations")
            await interaction.response.send_message(
                "I couldn't clear the reserves. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.reservations = updated_reservations
        await interaction.response.edit_message(
            content="All reserves have been cleared.",
            view=None,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.edit_message(
            content="Command cancelled",
            view=None,
        )


class ClearCollectionView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not member_is_administrator(interaction.user)
        ):
            await interaction.response.send_message(
                "Only the administrator who ran this command can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated_collections = clear_guild_collection(
            self.bot.collections,
            self.guild_id,
        )
        try:
            save_reservations(self.bot.collection_path, updated_collections)
        except ValueError:
            logger.exception("Could not clear server Pokémon collections")
            await interaction.response.send_message(
                "I couldn't clear the collections. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.collections = updated_collections
        await interaction.response.edit_message(
            content="Everyone's Pokémon collection in this server has been cleared.",
            view=None,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.edit_message(
            content="Command cancelled",
            view=None,
        )


class ClearShinyhuntsView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not member_is_administrator(interaction.user)
        ):
            await interaction.response.send_message(
                "Only the administrator who ran this command can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated_shinyhunters = clear_guild_shinyhunts(
            self.bot.shinyhunters,
            self.guild_id,
        )
        try:
            save_reservations(self.bot.shinyhunt_path, updated_shinyhunters)
        except ValueError:
            logger.exception("Could not clear server shinyhunts")
            await interaction.response.send_message(
                "I couldn't clear the shinyhunts. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.shinyhunters = updated_shinyhunters
        await interaction.response.edit_message(
            content="Everyone's shinyhunts in this server have been cleared.",
            view=None,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.edit_message(
            content="Command cancelled",
            view=None,
        )


class ClearTypePingsView(discord.ui.View):
    def __init__(
        self,
        bot: "NamingBot",
        guild_id: int,
        requester_id: int,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.requester_id
            or interaction.guild_id != self.guild_id
            or not isinstance(interaction.user, discord.Member)
            or not member_is_administrator(interaction.user)
        ):
            await interaction.response.send_message(
                "Only the administrator who ran this command can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        updated_type_pings = clear_guild_type_pings(
            self.bot.type_pings,
            self.guild_id,
        )
        try:
            save_type_pings(self.bot.type_ping_path, updated_type_pings)
        except ValueError:
            logger.exception("Could not clear server type pings")
            await interaction.response.send_message(
                "I couldn't clear the type pings. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.bot.type_pings = updated_type_pings
        await interaction.response.edit_message(
            content="Everyone's type pings in this server have been cleared.",
            view=None,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.edit_message(
            content="Command cancelled",
            view=None,
        )


def install_embed_tinting(bot: NamingBot) -> None:
    original_send = discord.abc.Messageable.send
    original_reply = discord.Message.reply

    async def send(self, *args, **kwargs):
        bot.tint_embeds(getattr(self, "guild", None), kwargs)
        return await original_send(self, *args, **kwargs)

    async def reply(self, *args, **kwargs):
        bot.tint_embeds(self.guild, kwargs)
        return await original_reply(self, *args, **kwargs)

    discord.abc.Messageable.send = send
    discord.Message.reply = reply


def main() -> None:
    config = Config.from_environment()
    bot = NamingBot(config)
    install_embed_tinting(bot)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
