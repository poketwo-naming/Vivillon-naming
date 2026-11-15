"""Daycare breeding boxes (`v!box`) and pair picking (`v!dc`)."""

import asyncio
import json
import random
import re
import time
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from data_paths import data_path
from typing import Any, Final, NamedTuple

import discord

BOX_LIMIT: Final[int] = 7500
MAX_CUSTOM_BOXES: Final[int] = 20
BULK_SLUG: Final[str] = "bulk"
TRACK_SECONDS: Final[int] = 30 * 60
MAX_TRACKED: Final[int] = 200
UNDISCOVERED: Final[int] = 15
DITTO: Final[int] = 13

DEFAULT_DC_SETTINGS: Final[dict[str, Any]] = {
    "output": "mobile",
    "details": True,
    "remaining": True,
    "strategy": "best",
    "highest": True,
    "shiny": False,
    "pairs": 1,
    "grace": 1,
}
SETTING_CYCLES: Final[dict[str, list[Any]]] = {
    "output": ["mobile", "desktop"],
    "details": [True, False],
    "remaining": [True, False],
    "strategy": ["best", "random"],
    "highest": [True, False],
    "shiny": [False, True],
    "grace": [1, 6, 12, 24],
}

HELP_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!box\s?help\s*$", re.IGNORECASE
)
BOX_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!b(?:ox)?(?:\s+(\S+)(?:\s+(.+?))?)?\s*$", re.IGNORECASE | re.DOTALL
)
DC_COMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^v!dc(?:\s+(.+?))?\s*$", re.IGNORECASE | re.DOTALL
)
LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*`\s*(\d+)\s*`(.*)$")
EMOJI_PATTERN: Final[re.Pattern[str]] = re.compile(r"<a?:(\w+):\d+>")
QUOTED_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\"“][^\"”]*[\"”]")
BOLD_PATTERN: Final[re.Pattern[str]] = re.compile(r"\*\*(.+?)\*\*")
IV_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@lru_cache(maxsize=1)
def _egg_data() -> tuple[dict[str, str], dict[str, tuple[int, ...]]]:
    path = data_path("egg_groups.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    names = {key: value for key, value in data["groups"].items()}
    species = {key: tuple(value) for key, value in data["species"].items()}
    return names, species


def egg_group_name(group_id: int) -> str:
    return _egg_data()[0].get(str(group_id), "Unknown")


def species_key(value: str) -> str:
    value = value.replace("♂", "m").replace("♀", "f")
    value = unicodedata.normalize("NFKD", value)
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def egg_groups_for(name: str) -> tuple[int, ...]:
    """Resolve a Pokétwo display name (forms included) to its egg groups."""
    species = _egg_data()[1]
    words = name.split()
    for start in range(len(words)):
        groups = species.get(species_key(" ".join(words[start:])))
        if groups:
            return groups
    return ()


def parse_pokemon_lines(texts: list[str]) -> list[tuple[str, list[Any]]]:
    """Parse Pokétwo list lines into (code, [name, gender, iv, shiny])."""
    parsed: list[tuple[str, list[Any]]] = []
    for text in texts:
        for line in text.replace("’", "'").splitlines():
            match = LINE_PATTERN.match(line)
            if match is None:
                continue
            head, _, tail = match.group(2).partition("•")
            bold = BOLD_PATTERN.search(head)
            if bold is None:
                continue
            name = EMOJI_PATTERN.sub("", bold.group(1)).replace("✨", "")
            name = " ".join(name.split())
            if not name:
                continue
            marker = QUOTED_PATTERN.sub("", head).casefold()
            marker += " ".join(EMOJI_PATTERN.findall(head)).casefold()
            if "♀" in marker or "female" in marker:
                gender = "F"
            elif "♂" in marker or "male" in marker:
                gender = "M"
            else:
                gender = "N"
            iv_match = IV_PATTERN.search(tail)
            iv = float(iv_match.group(1)) if iv_match else 0.0
            shiny = "✨" in head
            parsed.append((match.group(1), [name, gender, iv, shiny]))
    return parsed


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:20]


class Candidate(NamedTuple):
    code: str
    name: str
    gender: str
    iv: float
    shiny: bool
    groups: tuple[int, ...]


def build_candidates(
    entries: dict[str, list[Any]], include_shiny: bool
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for code, (name, gender, iv, shiny) in entries.items():
        if shiny and not include_shiny:
            continue
        groups = egg_groups_for(name)
        if not groups or UNDISCOVERED in groups:
            continue
        if DITTO in groups:
            gender = "D"
        elif gender not in ("M", "F"):
            continue
        candidates.append(Candidate(code, name, gender, iv, shiny, groups))
    return candidates


def find_pairs(
    candidates: list[Candidate],
    count: int,
    strategy: str = "best",
    highest: bool = True,
    rng: random.Random | None = None,
) -> list[tuple[Candidate, Candidate]]:
    """Greedily build up to `count` breedable (male, female) pairs."""
    order = list(candidates)
    if strategy == "random":
        (rng or random).shuffle(order)
    else:
        order.sort(key=lambda item: item.iv, reverse=highest)
    position = {item.code: index for index, item in enumerate(order)}
    pools: dict[tuple[int, str], deque[Candidate]] = {}
    dittos: deque[Candidate] = deque()
    breeders: deque[Candidate] = deque()
    for item in order:
        if item.gender == "D":
            dittos.append(item)
            continue
        breeders.append(item)
        for group in item.groups:
            pools.setdefault((group, item.gender), deque()).append(item)
    used: set[str] = set()

    def first(pool: deque[Candidate] | None) -> Candidate | None:
        while pool and pool[0].code in used:
            pool.popleft()
        return pool[0] if pool else None

    pairs: list[tuple[Candidate, Candidate]] = []
    for anchor in order:
        if len(pairs) >= count:
            break
        if anchor.code in used:
            continue
        if anchor.gender == "D":
            partner = first(breeders)
        else:
            opposite = "F" if anchor.gender == "M" else "M"
            options = [
                first(pools.get((group, opposite))) for group in anchor.groups
            ]
            real = [item for item in options if item is not None]
            partner = (
                min(real, key=lambda item: position[item.code])
                if real
                else first(dittos)
            )
        if partner is None:
            continue
        used.update((anchor.code, partner.code))
        male, female = (
            (anchor, partner)
            if anchor.gender == "M" or partner.gender in ("F", "D")
            else (partner, anchor)
        )
        pairs.append((male, female))
    return pairs


def shared_group_label(first: Candidate, second: Candidate) -> str:
    shared = [group for group in first.groups if group in second.groups]
    if shared:
        return egg_group_name(shared[0])
    other = second if first.gender == "D" else first
    return egg_group_name(other.groups[0])


def gender_symbol(gender: str) -> str:
    return {"M": "♂", "F": "♀"}.get(gender, "")


def load_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(DEFAULT_DC_SETTINGS)
    for key, value in (raw or {}).items():
        if key in settings and type(value) is type(settings[key]):
            settings[key] = value
    if settings["pairs"] not in (1, 2):
        settings["pairs"] = 1
    return settings


class BoxStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.users: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"Could not read box data from {path}") from error
            users = data.get("users") if isinstance(data, dict) else None
            if not isinstance(users, dict):
                raise ValueError(f"Box data in {path} has an invalid format")
            self.users = users

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            temporary.write_text(
                json.dumps({"users": self.users}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            raise ValueError(f"Could not save box data to {self.path}") from error

    def user(self, user_id: int) -> dict[str, Any]:
        record = self.users.setdefault(str(user_id), {})
        boxes = record.setdefault("boxes", {})
        boxes.setdefault(BULK_SLUG, {"name": "Bulk", "entries": {}})
        return record

    def boxes(self, user_id: int) -> dict[str, dict[str, Any]]:
        return self.user(user_id)["boxes"]

    def find_box(self, user_id: int, value: str) -> str | None:
        boxes = self.boxes(user_id)
        slug = slugify(value)
        if slug in boxes:
            return slug
        for key, box in boxes.items():
            if box["name"].casefold() == value.strip().casefold():
                return key
        return None

    def create_box(self, user_id: int, name: str) -> str:
        """Create a box and return its slug; raises ValueError with a reason."""
        name = " ".join(name.split())
        slug = slugify(name)
        if not slug or len(name) > 32:
            raise ValueError("Box names need 1-32 letters or numbers.")
        boxes = self.boxes(user_id)
        if slug in boxes:
            raise ValueError(f"You already have a box called **{boxes[slug]['name']}**.")
        if len(boxes) - 1 >= MAX_CUSTOM_BOXES:
            raise ValueError(f"You can only have {MAX_CUSTOM_BOXES} custom boxes.")
        boxes[slug] = {"name": name, "entries": {}}
        self.save()
        return slug

    def delete_box(self, user_id: int, slug: str) -> None:
        del self.boxes(user_id)[slug]
        self.save()

    def rename_box(self, user_id: int, slug: str, name: str) -> str:
        name = " ".join(name.split())
        new_slug = slugify(name)
        boxes = self.boxes(user_id)
        if not new_slug or len(name) > 32:
            raise ValueError("Box names need 1-32 letters or numbers.")
        if new_slug != slug and new_slug in boxes:
            raise ValueError(f"You already have a box called **{boxes[new_slug]['name']}**.")
        box = boxes.pop(slug)
        box["name"] = name
        boxes[new_slug] = box
        self.save()
        return new_slug

    def add_entries(
        self, user_id: int, slug: str, parsed: list[tuple[str, list[Any]]]
    ) -> tuple[int, int, int]:
        """Add entries; returns (added, already_present, skipped_for_limit)."""
        entries = self.boxes(user_id)[slug]["entries"]
        added = present = skipped = 0
        for code, data in parsed:
            if code in entries:
                present += 1
            elif len(entries) >= BOX_LIMIT:
                skipped += 1
            else:
                entries[code] = data
                added += 1
        if added:
            self.save()
        return added, present, skipped

    def remove_entries(self, user_id: int, slug: str, codes: list[str]) -> None:
        entries = self.boxes(user_id)[slug]["entries"]
        for code in codes:
            entries.pop(code, None)
        self.save()

    def locate(self, user_id: int, code: str) -> str | None:
        for slug, box in self.boxes(user_id).items():
            if code in box["entries"]:
                return slug
        return None

    def drop_entries(self, user_id: int, slug: str, codes: list[str]) -> list[str]:
        """Permanently remove entries and their tags; returns codes removed."""
        box = self.boxes(user_id)[slug]
        removed = [code for code in codes if code in box["entries"]]
        for code in removed:
            del box["entries"][code]
            box.get("tags", {}).pop(code, None)
        if removed:
            self.save()
        return removed

    def set_tags(
        self, user_id: int, codes: list[str], moves: list[str], add: bool
    ) -> list[str]:
        touched: list[str] = []
        for code in codes:
            slug = self.locate(user_id, code)
            if slug is None:
                continue
            tags = self.boxes(user_id)[slug].setdefault("tags", {})
            current = tags.get(code, [])
            if add:
                current = current + [m for m in moves if m not in current]
            else:
                current = [m for m in current if m not in moves]
            if current:
                tags[code] = current
            else:
                tags.pop(code, None)
            touched.append(code)
        if touched:
            self.save()
        return touched

    def transfer(
        self, user_id: int, codes: list[str], destination: str
    ) -> tuple[int, int]:
        """Move entries (with tags) into a box; returns (moved, skipped)."""
        boxes = self.boxes(user_id)
        target = boxes[destination]
        moved = skipped = 0
        for code in codes:
            source = self.locate(user_id, code)
            if source is None or source == destination:
                continue
            if len(target["entries"]) >= BOX_LIMIT:
                skipped += 1
                continue
            origin = boxes[source]
            target["entries"][code] = origin["entries"].pop(code)
            moves = origin.get("tags", {}).pop(code, None)
            if moves:
                target.setdefault("tags", {})[code] = moves
            moved += 1
        if moved:
            self.save()
        return moved, skipped

    def copy_box(self, user_id: int, source: str, name: str) -> str:
        slug = self.create_box(user_id, name)
        boxes = self.boxes(user_id)
        boxes[slug]["entries"] = {
            code: list(data) for code, data in boxes[source]["entries"].items()
        }
        boxes[slug]["tags"] = {
            code: list(moves)
            for code, moves in boxes[source].get("tags", {}).items()
            if code in boxes[source]["entries"]
        }
        self.save()
        return slug

    def clear_box(self, user_id: int, slug: str) -> int:
        box = self.boxes(user_id)[slug]
        count = len(box["entries"])
        box["entries"] = {}
        box["tags"] = {}
        self.save()
        return count

    def reset(self, user_id: int) -> None:
        self.users.pop(str(user_id), None)
        self.save()

    def settings(self, user_id: int) -> dict[str, Any]:
        return load_settings(self.user(user_id).get("dc"))

    def update_settings(self, user_id: int, **changes: Any) -> dict[str, Any]:
        settings = {**self.settings(user_id), **changes}
        self.user(user_id)["dc"] = settings
        self.save()
        return settings


def species_summary(entries: dict[str, list[Any]], limit: int = 5) -> str:
    counts = Counter(data[0] for data in entries.values())
    if not counts:
        return "empty"
    top = counts.most_common(limit)
    text = ", ".join(f"{name} ×{count}" for name, count in top)
    if len(counts) > limit:
        text += f" +{len(counts) - limit} more"
    return text


def build_box_list_embed(boxes: dict[str, dict[str, Any]]) -> discord.Embed:
    lines: list[str] = []
    for slug, box in boxes.items():
        count = len(box["entries"])
        lines.append(f"• **{box['name']}** `{slug}`: {count}/{BOX_LIMIT}")
        lines.append(f"-# {species_summary(box['entries'])}"[:150])
    embed = discord.Embed(
        title="Daycare Breeding Boxes",
        description="\n".join(lines)[:4000],
        color=discord.Color.from_rgb(0x2B, 0x2D, 0x31),
    )
    embed.set_footer(
        text=f"{len(boxes) - 1}/{MAX_CUSTOM_BOXES} non-Bulk boxes used • "
        "Bulk cannot be deleted or renamed"
    )
    return embed


@dataclass
class TrackedAppend:
    owner_id: int
    slug: str
    reply: discord.Message
    total_added: int
    started: float


class PutBackView(discord.ui.View):
    def __init__(
        self,
        feature: "DaycareFeature",
        user_id: int,
        slug: str,
        taken: list[tuple[str, list[Any]]],
        grace_hours: int,
    ) -> None:
        super().__init__(timeout=grace_hours * 3600)
        self.feature = feature
        self.user_id = user_id
        self.slug = slug
        self.taken = taken
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the trainer who ran this command can use it.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Put Back", style=discord.ButtonStyle.secondary)
    async def put_back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        async with self.feature.lock:
            if self.slug not in self.feature.store.boxes(self.user_id):
                await interaction.response.send_message(
                    "That box no longer exists.", ephemeral=True
                )
                return
            self.feature.store.add_entries(self.user_id, self.slug, self.taken)
        self.stop()
        await interaction.response.edit_message(view=None)
        await interaction.followup.send(
            f"↩️ Put {len(self.taken)} Pokémon back into the box.", ephemeral=True
        )


SETTING_EMOJI: Final[dict[str, str]] = {
    "output": "📱",
    "details": "🔎",
    "remaining": "📊",
    "strategy": "🎯",
    "highest": "📈",
    "shiny": "✨",
    "grace": "⏳",
}


def setting_label(key: str, settings: dict[str, Any]) -> str:
    value = settings[key]
    emoji = SETTING_EMOJI[key]
    if key == "output":
        return f"{emoji} Output: {value.title()}"
    if key in ("details", "remaining"):
        return f"{emoji} {key.title()}: {'On' if value else 'Off'}"
    if key == "strategy":
        return f"{emoji} Pick: {'Best IV' if value == 'best' else 'Random'}"
    if key == "highest":
        return f"{emoji} {'Highest' if value else 'Lowest'} IV first"
    if key == "shiny":
        return f"{emoji} Shinies: {'Include' if value else 'Skip'}"
    return f"{emoji} Grace: {value}h"


def setting_style(key: str, settings: dict[str, Any]) -> discord.ButtonStyle:
    if key in ("details", "remaining"):
        return (
            discord.ButtonStyle.success
            if settings[key]
            else discord.ButtonStyle.secondary
        )
    if key == "strategy":
        return discord.ButtonStyle.primary
    return discord.ButtonStyle.secondary


def build_settings_embed(settings: dict[str, Any]) -> discord.Embed:
    def on_off(value: bool) -> str:
        return "On" if value else "Off"

    embed = discord.Embed(
        title="🥚 Daycare Control Panel",
        description="Tune how `v!dc` picks and prints your breeding pairs.",
        color=discord.Color.from_rgb(0xF4, 0x8F, 0xB1),
    )
    embed.add_field(
        name="📱 Output",
        value=(
            f"`{settings['output'].title()}` · Details `{on_off(settings['details'])}`"
            f" · Remaining `{on_off(settings['remaining'])}`\n"
            "-# Mobile prints one paste-ready command; Desktop prints one per pair."
        ),
        inline=False,
    )
    embed.add_field(
        name="💞 Pairing",
        value=(
            f"`{'Best IV' if settings['strategy'] == 'best' else 'Random'}` · "
            f"`{'Highest' if settings['highest'] else 'Lowest'} IV`\n"
            "-# Best IV anchors on the top (or bottom) IV, then finds a partner "
            "from a shared egg group."
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ Defaults",
        value=(
            f"`{settings['pairs']}` pair(s) · Grace `{settings['grace']}h` · "
            f"Shinies `{'Included' if settings['shiny'] else 'Skipped'}`\n"
            "-# Pairs pulled per use, how long Put Back stays available, "
            "and whether shinies can be paired."
        ),
        inline=False,
    )
    return embed


class SettingButton(discord.ui.Button):
    def __init__(self, key: str, settings: dict[str, Any], row: int) -> None:
        super().__init__(
            label=setting_label(key, settings),
            style=setting_style(key, settings),
            row=row,
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DaycareSettingsView):
            raise RuntimeError("Settings button is not attached to its view")
        cycle = SETTING_CYCLES[self.key]
        current = view.settings[self.key]
        new_value = cycle[(cycle.index(current) + 1) % len(cycle)]
        view.settings = view.feature.store.update_settings(
            view.user_id, **{self.key: new_value}
        )
        view.refresh()
        await interaction.response.edit_message(
            embed=build_settings_embed(view.settings), view=view
        )


class PairCountSelect(discord.ui.Select):
    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(
            placeholder="Pairs per pull",
            options=[
                discord.SelectOption(
                    label=f"{count} pair{'s' if count > 1 else ''}",
                    value=str(count),
                    default=settings["pairs"] == count,
                )
                for count in (1, 2)
            ],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DaycareSettingsView):
            raise RuntimeError("Pair-count select is not attached to its view")
        view.settings = view.feature.store.update_settings(
            view.user_id, pairs=int(self.values[0])
        )
        view.refresh()
        await interaction.response.edit_message(
            embed=build_settings_embed(view.settings), view=view
        )


class DaycareSettingsView(discord.ui.View):
    LAYOUT: Final[list[list[str]]] = [
        ["output", "details", "remaining"],
        ["strategy", "highest", "shiny"],
        ["grace"],
    ]

    def __init__(self, feature: "DaycareFeature", user_id: int) -> None:
        super().__init__(timeout=300)
        self.feature = feature
        self.user_id = user_id
        self.settings = feature.store.settings(user_id)
        self.message: discord.Message | None = None
        self.refresh()

    def refresh(self) -> None:
        self.clear_items()
        for row, keys in enumerate(self.LAYOUT):
            for key in keys:
                self.add_item(SettingButton(key, self.settings, row))
        self.add_item(PairCountSelect(self.settings))
        info = discord.ui.Button(
            label="Info", emoji="ℹ️", style=discord.ButtonStyle.primary, row=4
        )
        info.callback = self.show_info
        close = discord.ui.Button(
            label="Close", style=discord.ButtonStyle.danger, row=4
        )
        close.callback = self.close_panel
        self.add_item(info)
        self.add_item(close)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "These are someone else's settings. Run `v!dc settings` for your own.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    async def show_info(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "**`v!dc [box]`** pulls breedable pairs out of a box (default Bulk).\n"
            "• **Pick**: Best IV anchors on the best IV; Random shuffles.\n"
            "• **Grace**: how long the Put Back button works after a pull.\n"
            "• Pairs always share an egg group; Ditto only pairs when nothing "
            "else fits.",
            ephemeral=True,
        )

    async def close_panel(self, interaction: discord.Interaction) -> None:
        self.stop()
        message = interaction.message
        if message is not None:
            await message.delete()


HELP_ROWS: Final[list[tuple[str, str]]] = [
    ("v!box create <name>", "Start a fresh, empty breeding box."),
    ("v!box delete <name>", "Throw a box away for good (Bulk is protected)."),
    ("v!box rename <old> <new>", "Give one of your boxes a new name."),
    ("v!box boxes", "See every box, its fill level and its top species."),
    (
        "v!box append [box] [-c]",
        "Reply to a Pokétwo list to file its Pokémon into a box. Turning pages "
        "keeps adding. `-c` creates the box if it's missing.",
    ),
    ("v!box remove <ids...> [box]", "Delete specific Pokémon IDs from one or all boxes."),
    ("v!box tag <ids...> <moves>", "Mark Pokémon as carrying egg moves (comma separated)."),
    ("v!box untag <ids...> <moves>", "Strip those egg-move marks off again."),
    ("v!box tags <id>", "Check which egg moves one Pokémon is tagged with."),
    ("v!box tagged <move>", "Find every stored Pokémon tagged with a move."),
    ("v!box transfer <ids...> <box>", "Shift Pokémon (and their tags) into another box."),
    ("v!box copy <source> <new>", "Duplicate a box under a new name."),
    ("v!box list [box]", "Browse a box's contents page by page."),
    ("v!box clear [box]", "Empty a box after you confirm."),
    ("v!box reset", "Wipe all your boxes, tags and settings after you confirm."),
    ("v!dc [box]", "Pull 1-2 breedable pairs and get the daycare command."),
    ("v!dc settings", "Open the daycare control panel."),
]


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📦 Breeding Box Guide",
        description=(
            f"Keep your daycare stock organised. Each box holds up to "
            f"**{BOX_LIMIT:,}** Pokémon. `v!b` works as a shortcut for `v!box`."
        ),
        color=discord.Color.from_rgb(0x7E, 0xC8, 0xA4),
    )
    embed.add_field(
        name="Commands",
        value=" · ".join(
            f"`{name.split()[1]}`" for name, _ in HELP_ROWS if name.startswith("v!box")
        ),
        inline=False,
    )
    for start in range(0, len(HELP_ROWS), 6):
        chunk = HELP_ROWS[start : start + 6]
        embed.add_field(
            name="\u200b",
            value="\n".join(f"**{usage}**\n{text}" for usage, text in chunk),
            inline=False,
        )
    embed.set_footer(text="Tip: reply to a Pokétwo list with v!box append to fill a box.")
    return embed


class ConfirmView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=30)
        self.user_id = user_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("Not your prompt.", ephemeral=True)
        return False

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.defer()


class BoxEntriesView(discord.ui.View):
    PAGE_SIZE: Final[int] = 20

    def __init__(self, user_id: int, box: dict[str, Any]) -> None:
        super().__init__(timeout=300)
        self.user_id = user_id
        self.box = box
        self.page = 0
        self.message: discord.Message | None = None

    def page_count(self) -> int:
        return max(1, -(-len(self.box["entries"]) // self.PAGE_SIZE))

    def page_embed(self) -> discord.Embed:
        items = list(self.box["entries"].items())
        self.page = min(self.page, self.page_count() - 1)
        start = self.page * self.PAGE_SIZE
        tags = self.box.get("tags", {})
        lines = []
        for code, (name, gender, iv, shiny) in items[start : start + self.PAGE_SIZE]:
            line = f"`{code}` {'✨ ' if shiny else ''}{name} {gender_symbol(gender)} {iv:.2f}%"
            if code in tags:
                line += f" 🏷️ {', '.join(tags[code])}"
            lines.append(line)
        embed = discord.Embed(title=f"{self.box['name']} contents", description="\n".join(lines))
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.page_count()} • "
            f"{len(items)}/{BOX_LIMIT} Pokémon"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("Not your list.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = (self.page - 1) % self.page_count()
        await interaction.response.edit_message(embed=self.page_embed())

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def following(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = (self.page + 1) % self.page_count()
        await interaction.response.edit_message(embed=self.page_embed())


class DaycareFeature:
    def __init__(self, path: Path, poketwo_bot_id: int) -> None:
        self.store = BoxStore(path)
        self.poketwo_bot_id = poketwo_bot_id
        self.lock = asyncio.Lock()
        self.tracked: dict[int, TrackedAppend] = {}

    async def handle_message(self, message: discord.Message) -> bool:
        content = message.content
        if HELP_COMMAND_PATTERN.match(content):
            await message.reply(embed=build_help_embed(), mention_author=False)
            return True
        box_match = BOX_COMMAND_PATTERN.match(content)
        if box_match is not None:
            await self.handle_box(message, box_match.group(1), box_match.group(2))
            return True
        dc_match = DC_COMMAND_PATTERN.match(content)
        if dc_match is not None:
            await self.handle_dc(message, dc_match.group(1))
            return True
        return False

    async def reply(self, message: discord.Message, text: str, **kwargs: Any) -> Any:
        return await message.reply(
            text,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
            **kwargs,
        )

    async def handle_box(
        self, message: discord.Message, action: str | None, argument: str | None
    ) -> None:
        user_id = message.author.id
        action = (action or "").casefold()
        handlers = {
            "create": self.box_create,
            "grate": self.box_create,
            "append": self.box_append,
            "delete": self.box_delete,
            "rename": self.box_rename,
            "remove": self.box_remove,
            "tag": self.box_tag,
            "untag": self.box_tag,
            "tags": self.box_tags,
            "tagged": self.box_tagged,
            "transfer": self.box_transfer,
            "copy": self.box_copy,
            "list": self.box_list,
            "clear": self.box_clear,
            "reset": self.box_reset,
        }
        if action in ("", "boxes"):
            async with self.lock:
                embed = build_box_list_embed(self.store.boxes(user_id))
            await message.reply(embed=embed, mention_author=False)
        elif action == "help":
            await message.reply(embed=build_help_embed(), mention_author=False)
        elif action in handlers:
            handler = handlers[action]
            async with self.lock:
                if action == "untag":
                    await handler(message, argument, untag=True)
                else:
                    await handler(message, argument)
        else:
            await message.reply(embed=build_help_embed(), mention_author=False)

    def split_ids(self, argument: str | None) -> tuple[list[str], list[str]]:
        """Split leading numeric codes from the remaining tokens."""
        tokens = (argument or "").replace(",", " ").split()
        codes: list[str] = []
        while tokens and tokens[0].isdigit():
            codes.append(tokens.pop(0))
        return list(dict.fromkeys(codes)), tokens

    async def box_remove(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        codes, rest = self.split_ids(argument)
        if not codes:
            await self.reply(message, "Usage: `v!box remove <ids...> [box]`")
            return
        slugs = list(self.store.boxes(user_id))
        if rest:
            slug = self.store.find_box(user_id, " ".join(rest))
            if slug is None:
                await self.reply(message, "❌ I couldn't find that box.")
                return
            slugs = [slug]
        removed = sum(
            len(self.store.drop_entries(user_id, slug, codes)) for slug in slugs
        )
        await self.reply(message, f"🗑️ Removed **{removed}** Pokémon from your boxes.")

    async def box_tag(
        self, message: discord.Message, argument: str | None, untag: bool = False
    ) -> None:
        command = "untag" if untag else "tag"
        codes, rest = self.split_ids(argument)
        moves = [m.strip() for m in " ".join(rest).split(",") if m.strip()]
        if not codes or not moves:
            await self.reply(message, f"Usage: `v!box {command} <ids...> <move, move...>`")
            return
        touched = self.store.set_tags(message.author.id, codes, moves, not untag)
        verb = "Removed tags from" if untag else "Tagged"
        await self.reply(
            message,
            f"🏷️ {verb} **{len(touched)}** Pokémon ({', '.join(moves)})."
            if touched
            else "❌ None of those IDs are in your boxes.",
        )

    async def box_tags(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        codes, _ = self.split_ids(argument)
        slug = self.store.locate(user_id, codes[0]) if codes else None
        if slug is None:
            await self.reply(message, "Usage: `v!box tags <id>` (ID must be in a box)")
            return
        box = self.store.boxes(user_id)[slug]
        moves = box.get("tags", {}).get(codes[0])
        name = box["entries"][codes[0]][0]
        await self.reply(
            message,
            f"🏷️ `{codes[0]}` {name}: " + (", ".join(moves) if moves else "no tags"),
        )

    async def box_tagged(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        move = (argument or "").strip().casefold()
        if not move:
            await self.reply(message, "Usage: `v!box tagged <move>`")
            return
        lines: list[str] = []
        for box in self.store.boxes(user_id).values():
            for code, moves in box.get("tags", {}).items():
                if code in box["entries"] and move in (m.casefold() for m in moves):
                    lines.append(
                        f"`{code}` {box['entries'][code][0]} · {box['name']}"
                    )
        if not lines:
            await self.reply(message, f"No Pokémon tagged with **{move}**.")
            return
        embed = discord.Embed(
            title=f"Tagged: {move}",
            description="\n".join(lines[:60])
            + (f"\n+{len(lines) - 60} more" if len(lines) > 60 else ""),
        )
        await message.reply(embed=embed, mention_author=False)

    async def box_transfer(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        codes, rest = self.split_ids(argument)
        slug = self.store.find_box(user_id, " ".join(rest)) if rest else None
        if not codes or slug is None:
            await self.reply(message, "Usage: `v!box transfer <ids...> <box>`")
            return
        moved, skipped = self.store.transfer(user_id, codes, slug)
        name = self.store.boxes(user_id)[slug]["name"]
        text = f"📦 Moved **{moved}** Pokémon to **{name}**."
        if skipped:
            text += f"\n⚠️ {skipped} did not fit (limit {BOX_LIMIT})."
        await self.reply(message, text)

    async def box_copy(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        parts = (argument or "").split(None, 1)
        source = self.store.find_box(user_id, parts[0]) if parts else None
        if len(parts) < 2 or source is None:
            await self.reply(message, "Usage: `v!box copy <source> <new>`")
            return
        try:
            slug = self.store.copy_box(user_id, source, parts[1])
        except ValueError as error:
            await self.reply(message, f"❌ {error}")
            return
        box = self.store.boxes(user_id)[slug]
        await self.reply(
            message, f"✅ Copied into **{box['name']}** ({len(box['entries'])} Pokémon)."
        )

    async def box_list(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        slug = BULK_SLUG if not argument else self.store.find_box(user_id, argument)
        if slug is None:
            await self.reply(message, "❌ I couldn't find that box.")
            return
        box = self.store.boxes(user_id)[slug]
        if not box["entries"]:
            await self.reply(message, f"**{box['name']}** is empty.")
            return
        view = BoxEntriesView(message.author.id, box)
        view.message = await message.reply(
            embed=view.page_embed(), view=view, mention_author=False
        )

    async def confirm(self, message: discord.Message, prompt: str) -> bool:
        view = ConfirmView(message.author.id)
        sent = await self.reply(message, prompt, view=view)
        await view.wait()
        try:
            await sent.edit(view=None)
        except discord.HTTPException:
            pass
        return view.confirmed

    async def box_clear(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        slug = BULK_SLUG if not argument else self.store.find_box(user_id, argument)
        if slug is None:
            await self.reply(message, "❌ I couldn't find that box.")
            return
        name = self.store.boxes(user_id)[slug]["name"]
        self.lock.release()
        try:
            confirmed = await self.confirm(message, f"Clear everything in **{name}**?")
        finally:
            await self.lock.acquire()
        if not confirmed or slug not in self.store.boxes(user_id):
            await self.reply(message, "Cancelled, nothing was cleared.")
            return
        count = self.store.clear_box(user_id, slug)
        await self.reply(message, f"🧹 Cleared **{count}** Pokémon from **{name}**.")

    async def box_reset(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        self.lock.release()
        try:
            confirmed = await self.confirm(
                message,
                "⚠️ Reset **all** your boxes, tags and daycare settings? "
                "This can't be undone.",
            )
        finally:
            await self.lock.acquire()
        if not confirmed:
            await self.reply(message, "Cancelled, nothing was reset.")
            return
        self.store.reset(user_id)
        await self.reply(message, "♻️ All your box data has been reset.")

    async def box_create(self, message: discord.Message, name: str | None) -> None:
        if not name:
            await self.reply(message, "Usage: `v!box create <name>`")
            return
        try:
            slug = self.store.create_box(message.author.id, name)
        except ValueError as error:
            await self.reply(message, f"❌ {error}")
            return
        box_name = self.store.boxes(message.author.id)[slug]["name"]
        await self.reply(message, f"✅ Created breeding box **{box_name}**.")

    async def box_delete(self, message: discord.Message, name: str | None) -> None:
        user_id = message.author.id
        slug = self.store.find_box(user_id, name) if name else None
        if slug is None:
            await self.reply(message, "❌ I couldn't find that box.")
        elif slug == BULK_SLUG:
            await self.reply(message, "❌ Bulk cannot be deleted or renamed.")
        else:
            box_name = self.store.boxes(user_id)[slug]["name"]
            self.store.delete_box(user_id, slug)
            await self.reply(message, f"🗑️ Deleted box **{box_name}**.")

    async def box_rename(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        parts = (argument or "").split(None, 1)
        slug = self.store.find_box(user_id, parts[0]) if parts else None
        if len(parts) < 2 or slug is None:
            await self.reply(message, "Usage: `v!box rename <name> <new name>`")
        elif slug == BULK_SLUG:
            await self.reply(message, "❌ Bulk cannot be deleted or renamed.")
        else:
            try:
                new_slug = self.store.rename_box(user_id, slug, parts[1])
            except ValueError as error:
                await self.reply(message, f"❌ {error}")
                return
            box_name = self.store.boxes(user_id)[new_slug]["name"]
            await self.reply(message, f"✅ Renamed the box to **{box_name}**.")

    async def box_append(self, message: discord.Message, name: str | None) -> None:
        user_id = message.author.id
        words = (name or "").split()
        create_missing = "-c" in words
        name = " ".join(word for word in words if word != "-c") or None
        slug = BULK_SLUG if not name else self.store.find_box(user_id, name)
        if slug is None and create_missing and name is not None:
            try:
                slug = self.store.create_box(user_id, name)
            except ValueError as error:
                await self.reply(message, f"❌ {error}")
                return
        if slug is None:
            await self.reply(
                message,
                f"❌ No box called **{name}**. Create it with `v!box create {name}`.",
            )
            return
        try:
            referenced = await self.resolve_reference(message)
        except discord.HTTPException as error:
            await self.reply(
                message,
                f"❌ Couldn't retrieve the replied-to message (Discord HTTP {error.status}). "
                "Check that I can view the channel and read message history.",
            )
            return
        if referenced is None:
            await self.reply(
                message,
                "Reply to a Pokétwo Pokémon list with `v!box append [name]`.",
            )
            return
        if referenced.author.id != self.poketwo_bot_id:
            await self.reply(
                message,
                "❌ The replied-to message isn't from the configured Pokétwo account. "
                "Check `POKETWO_BOT_ID` or reply to the Pokétwo list itself.",
            )
            return
        parsed = self.parse_list(
            referenced.content,
            referenced.embeds,
            [component.to_dict() for component in referenced.components],
        )
        if not parsed and not referenced.content and not referenced.embeds:
            await self.reply(
                message,
                "❌ I can't see the list content on the replied-to message. Reply to the "
                "Pokétwo list and check that Message Content Intent is enabled and "
                "approved for this bot.",
            )
            return
        if not parsed:
            await self.reply(message, "❌ I couldn't find any Pokémon codes in that list.")
            return
        added, present, skipped = self.store.add_entries(user_id, slug, parsed)
        reply = await self.reply(
            message, self.append_text(user_id, slug, added, added, present, skipped)
        )
        self.prune_tracked()
        self.tracked[referenced.id] = TrackedAppend(
            user_id, slug, reply, added, time.monotonic()
        )

    def append_text(
        self, user_id: int, slug: str, added: int, total_added: int, present: int, skipped: int
    ) -> str:
        box = self.store.boxes(user_id)[slug]
        text = (
            f"✅ Added **{total_added}** entries across 1 box(es).\n"
            f"• **{box['name']}**: added {total_added}, now "
            f"{len(box['entries'])}/{BOX_LIMIT}"
        )
        if present:
            text += f"\n-# {present} already in the box were skipped."
        if skipped:
            text += f"\n⚠️ Box is full — {skipped} entries did not fit."
        return text

    @staticmethod
    def parse_list(
        content: str, embeds: list[discord.Embed], components: list[dict[str, Any]]
    ) -> list[tuple[str, list[Any]]]:
        texts = [content] + [embed.description for embed in embeds if embed.description]
        pending = list(reversed(components))
        while pending:
            component = pending.pop()
            if component.get("type") == 10 and isinstance(component.get("content"), str):
                texts.append(component["content"])
            pending.extend(reversed(component.get("components", [])))
        return parse_pokemon_lines(texts)

    async def resolve_reference(
        self, message: discord.Message
    ) -> discord.Message | None:
        if message.reference is None:
            return None
        resolved = message.reference.resolved
        if isinstance(resolved, discord.Message):
            if resolved.author.id != self.poketwo_bot_id or self.parse_list(
                resolved.content,
                resolved.embeds,
                [component.to_dict() for component in resolved.components],
            ):
                return resolved
        message_id = message.reference.message_id
        if message_id is None:
            return None
        return await message.channel.fetch_message(message_id)

    def prune_tracked(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self.tracked.items() if now - v.started > TRACK_SECONDS]:
            del self.tracked[key]
        while len(self.tracked) >= MAX_TRACKED:
            del self.tracked[next(iter(self.tracked))]

    async def handle_raw_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        """Add the next page when a tracked Pokétwo list is paged."""
        tracked = self.tracked.get(payload.message_id)
        if tracked is None:
            return
        if time.monotonic() - tracked.started > TRACK_SECONDS:
            del self.tracked[payload.message_id]
            return
        raw_embeds = payload.data.get("embeds") or []
        embeds = [discord.Embed.from_dict(raw) for raw in raw_embeds]
        parsed = self.parse_list(
            payload.data.get("content") or "", embeds, payload.data.get("components") or []
        )
        if not parsed:
            return
        async with self.lock:
            if tracked.slug not in self.store.boxes(tracked.owner_id):
                del self.tracked[payload.message_id]
                return
            added, present, skipped = self.store.add_entries(
                tracked.owner_id, tracked.slug, parsed
            )
            if not added and not skipped:
                return
            tracked.total_added += added
            text = self.append_text(
                tracked.owner_id, tracked.slug, added, tracked.total_added, 0, skipped
            )
        try:
            await tracked.reply.edit(content=text)
        except discord.HTTPException:
            pass

    async def handle_dc(self, message: discord.Message, argument: str | None) -> None:
        user_id = message.author.id
        if argument and argument.casefold() == "settings":
            view = DaycareSettingsView(self, user_id)
            view.message = await message.reply(
                embed=build_settings_embed(view.settings),
                view=view,
                mention_author=False,
            )
            return
        async with self.lock:
            slug = BULK_SLUG if not argument else self.store.find_box(user_id, argument)
            if slug is None:
                await self.reply(message, f"❌ No box called **{argument}**.")
                return
            settings = self.store.settings(user_id)
            box = self.store.boxes(user_id)[slug]
            candidates = build_candidates(box["entries"], settings["shiny"])
            pairs = find_pairs(
                candidates, settings["pairs"], settings["strategy"], settings["highest"]
            )
            if not pairs:
                await self.reply(
                    message,
                    f"💤 No breedable pairs found in **{box['name']}**. "
                    "Pairs need a male and female sharing an egg group.",
                )
                return
            taken = [
                (item.code, box["entries"][item.code])
                for pair in pairs
                for item in pair
            ]
            self.store.remove_entries(user_id, slug, [code for code, _ in taken])
            remaining = None
            if settings["remaining"]:
                leftover = build_candidates(box["entries"], settings["shiny"])
                remaining = len(
                    find_pairs(leftover, len(leftover), settings["strategy"], settings["highest"])
                )
        text = self.format_pairs(box["name"], pairs, settings, remaining)
        view = PutBackView(self, user_id, slug, taken, settings["grace"])
        view.message = await self.reply(message, text, view=view)

    def format_pairs(
        self,
        box_name: str,
        pairs: list[tuple[Candidate, Candidate]],
        settings: dict[str, Any],
        remaining: int | None,
    ) -> str:
        codes = [item.code for pair in pairs for item in pair]
        lines = [f"🥚 Box: **{box_name}** · Pairs formed: **{len(pairs)}**"]
        if settings["output"] == "mobile":
            lines.append(f"`@Pokétwo daycare add {' '.join(codes)}`")
        else:
            lines.append(
                "```\n"
                + "\n".join(
                    f"@Pokétwo daycare add {male.code} {female.code}"
                    for male, female in pairs
                )
                + "\n```"
            )
        if settings["details"]:
            for male, female in pairs:
                label = shared_group_label(male, female)
                lines.append(
                    f"`{male.code}` {male.name} {gender_symbol(male.gender)} "
                    f"{male.iv:.2f}% ⇄ `{female.code}` {female.name} "
                    f"{gender_symbol(female.gender)} {female.iv:.2f}% · {label}"
                )
        if remaining is not None:
            lines.append(f"-# {remaining} pair(s) remaining.")
        return "\n".join(lines)
