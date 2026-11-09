"""Incense Pokéball drops, progression, and profile dyes."""

import asyncio
import copy
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Callable

import discord

logger = logging.getLogger("vivillon_naming")
INTERVAL = 180
BALL_LIFETIME = 10
BALL_IMAGE = Path(__file__).with_name("assets") / "drop_pokeball.png"


def level_for_xp(xp: int) -> int:
    # The cost of the next level starts at 500 XP and rises by 100 each level.
    level = 0
    while xp >= 500 + 100 * level:
        xp -= 500 + 100 * level
        level += 1
    return level


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read Pokéball data from {path}") from error


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        raise ValueError(f"Could not save Pokéball data to {path}") from error


def load_dyes(path: Path) -> list[dict[str, str]]:
    data = read_json(path, {"dyes": []})
    if not isinstance(data, dict) or set(data) != {"dyes"} or not isinstance(data["dyes"], list):
        raise ValueError(f"Invalid dye catalog in {path}")
    dyes = []
    seen = set()
    for dye in data["dyes"]:
        if (
            not isinstance(dye, dict)
            or set(dye) != {"name", "type", "rarity", "color"}
            or not isinstance(dye["name"], str)
            or not dye["name"].strip()
            or dye["name"] in seen
            or dye["type"] not in ("frame", "background")
            or dye["rarity"] not in ("normal", "radiant")
            or dye["rarity"] == "radiant" and dye["type"] != "frame"
            or not isinstance(dye["color"], str)
            or re.fullmatch(r"#[0-9a-fA-F]{6}", dye["color"]) is None
        ):
            raise ValueError(f"Invalid dye definition in {path}")
        seen.add(dye["name"])
        dyes.append(dict(dye))
    return dyes


class PokeballDrops:
    def __init__(
        self, bot: Any, path: Path, catalog_path: Path,
        save_inventory: Callable[[Path, dict[str, dict[str, Any]]], None],
    ) -> None:
        self.bot = bot
        self.path = path
        self.catalog_path = catalog_path
        self.save_inventory = save_inventory
        self.data = read_json(path, {"categories": {}, "users": {}})
        if (
            not isinstance(self.data, dict)
            or set(self.data) != {"categories", "users"}
            or not isinstance(self.data["categories"], dict)
            or not isinstance(self.data["users"], dict)
        ):
            raise ValueError(f"Invalid Pokéball data in {path}")
        for guild_id, categories in self.data["categories"].items():
            if not isinstance(guild_id, str) or not guild_id.isdecimal() or not isinstance(categories, list) or any(
                not isinstance(category, int) or isinstance(category, bool) or category <= 0 for category in categories
            ):
                raise ValueError(f"Invalid Pokéball categories in {path}")
        for user_id, user in self.data["users"].items():
            if (
                not isinstance(user_id, str) or not user_id.isdecimal()
                or not isinstance(user, dict)
                or set(user) not in ({"xp", "dyes", "applied"}, {"xp", "dyes", "applied", "selected"})
                or not isinstance(user["xp"], int) or isinstance(user["xp"], bool) or user["xp"] < 0
                or not isinstance(user["dyes"], list)
                or not isinstance(user["applied"], dict)
                or not isinstance(user.get("selected", {}), dict)
            ):
                raise ValueError(f"Invalid Pokéball user in {path}")
            for dye in user["dyes"]:
                if not self.valid_owned_dye(dye):
                    raise ValueError(f"Invalid owned dye in {path}")
            for code, dye in user["applied"].items():
                if not isinstance(code, str) or not self.valid_owned_dye(dye):
                    raise ValueError(f"Invalid applied dye in {path}")
            if any(
                setting not in ("frame", "background", "middle_background")
                or not isinstance(code, str) or re.fullmatch(r"[A-Z0-9]{7}", code) is None
                for setting, code in user.get("selected", {}).items()
            ):
                raise ValueError(f"Invalid selected profile asset in {path}")
        load_dyes(catalog_path)
        self.tasks: dict[int, asyncio.Task] = {}
        self.expiry_tasks: set[asyncio.Task] = set()
        self.last_spawn: dict[int, float] = {}

    @staticmethod
    def valid_owned_dye(dye: Any) -> bool:
        return (
            isinstance(dye, dict)
            and set(dye) == {"code", "name", "type", "rarity", "color"}
            and isinstance(dye["code"], str) and re.fullmatch(r"[A-Z0-9]{7}", dye["code"]) is not None
            and isinstance(dye["name"], str) and bool(dye["name"])
            and dye["type"] in ("frame", "background")
            and dye["rarity"] in ("normal", "radiant")
            and not (dye["rarity"] == "radiant" and dye["type"] != "frame")
            and isinstance(dye["color"], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", dye["color"]) is not None
        )

    def save(self, data: dict[str, Any]) -> None:
        write_json(self.path, data)
        self.data = data

    @staticmethod
    def user(data: dict[str, Any], user_id: int) -> dict[str, Any]:
        return data["users"].setdefault(str(user_id), {"xp": 0, "dyes": [], "applied": {}, "selected": {}})

    def level(self, user_id: int) -> int:
        return level_for_xp(self.data["users"].get(str(user_id), {}).get("xp", 0))

    def record_spawn(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None or not self.data["categories"].get(str(guild.id)):
            return
        channel_id = message.channel.id
        record = self.bot.active_incenses.get(str(channel_id))
        if (
            record is None or record["guild_id"] != guild.id
            or record["expires_at"] <= time.time()
            or channel_id in self.bot.muted_poketwo_channels
        ):
            return
        self.last_spawn[guild.id] = time.monotonic()
        if guild.id not in self.tasks:
            self.tasks[guild.id] = asyncio.create_task(self.run_guild(guild.id))

    async def run_guild(self, guild_id: int) -> None:
        try:
            while True:
                await asyncio.sleep(INTERVAL)
                if time.monotonic() - self.last_spawn.get(guild_id, 0) > INTERVAL:
                    return
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    return
                categories = set(self.data["categories"].get(str(guild_id), []))
                channels = [
                    channel for channel in guild.text_channels
                    if channel.category_id in categories
                    and guild.me is not None
                    and channel.permissions_for(guild.me).view_channel
                    and channel.permissions_for(guild.me).send_messages
                    and channel.permissions_for(guild.me).attach_files
                    and channel.permissions_for(guild.me).embed_links
                ]
                if not channels:
                    logger.warning("No accessible Pokéball drop channels in guild %s", guild_id)
                    continue
                channel = random.choice(channels)
                view = PokeballView(self)
                embed = discord.Embed(description="A Pokéball dropped! Be the first to open it.", color=discord.Color.pink())
                embed.set_thumbnail(url="attachment://pokeball.png")
                try:
                    view.message = await channel.send(
                        embed=embed, file=discord.File(BALL_IMAGE, filename="pokeball.png"), view=view
                    )
                    view.start_expiry()
                except (discord.HTTPException, OSError):
                    logger.exception("Could not send Pokéball drop in channel %s", channel.id)
        finally:
            self.tasks.pop(guild_id, None)

    def close(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
        for task in self.expiry_tasks:
            task.cancel()
        self.expiry_tasks.clear()

    def award(self, user_id: int) -> str:
        dyes = load_dyes(self.catalog_path)
        roll = random.randrange(15000)
        rarity = "radiant" if roll < 2 else "normal" if roll < 17 else None
        choices = [dye for dye in dyes if dye["rarity"] == rarity]
        if choices:
            data = copy.deepcopy(self.data)
            user = self.user(data, user_id)
            used = {dye["code"] for entry in data["users"].values() for dye in entry["dyes"]}
            used.update(code for entry in data["users"].values() for code in entry["applied"])
            while True:
                code = f"{random.randrange(16 ** 7):07X}"
                if code not in used:
                    break
            dye = {**random.choice(choices), "code": code}
            user["dyes"].append(dye)
            self.save(data)
            return f"found a **{dye['rarity']} {dye['type']} dye: {dye['name']}** (`{code}`)!"
        if random.randrange(2) == 0:
            amount = random.randint(0, 500)
            data = copy.deepcopy(self.data)
            user = self.user(data, user_id)
            old_level = level_for_xp(user["xp"])
            user["xp"] += amount
            new_level = level_for_xp(user["xp"])
            self.save(data)
            if not amount:
                return "found **0 XP**. How unlucky!"
            return f"found **{amount:,} XP**!" + (f" They reached **level {new_level}**!" if new_level > old_level else "")
        amount = random.randint(0, 1000)
        inventory = copy.deepcopy(self.bot.profile_inventory)
        user = inventory.setdefault(str(user_id), {"balances": {}, "assets": []})
        currency = "Pokédollar"
        user["balances"][currency] = user["balances"].get(currency, 0) + amount
        self.save_inventory(self.bot.profile_inventory_path, inventory)
        self.bot.profile_inventory = inventory
        return f"found **{amount:,} Pokédollars**!" if amount else "found **0 Pokédollars**. How unlucky!"

    def appearance(self, user_id: int, settings: dict[str, int | str]) -> dict[str, dict[str, str]]:
        user = self.data["users"].get(str(user_id), {})
        applied = user.get("applied", {})
        inventory = self.bot.profile_inventory.get(str(user_id), {}).get("assets", [])
        result = {}
        assets_by_code = {asset["code"]: asset for asset in inventory}
        for code, dye in applied.items():
            asset = assets_by_code.get(code)
            if asset and settings.get(asset["type"]) == asset["key"]:
                result[asset["type"]] = dye
        for setting, code in user.get("selected", {}).items():
            asset = assets_by_code.get(code)
            if asset and asset["type"] == setting and settings.get(setting) == asset["key"]:
                if code in applied:
                    result[setting] = applied[code]
                else:
                    result.pop(setting, None)
        return result

    def select_purchased_copy(
        self, user_id: int, setting: str, code: str
    ) -> dict[str, Any] | None:
        user = self.data["users"].get(str(user_id), {})
        if setting not in user.get("selected", {}):
            return None
        previous = self.data
        updated = copy.deepcopy(previous)
        updated["users"][str(user_id)]["selected"][setting] = code
        self.save(updated)
        return previous

    async def configure(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None:
            await message.reply("Use this command in a server.", mention_author=False)
            return
        permissions = getattr(message.author, "guild_permissions", None)
        if permissions is None or not permissions.manage_guild:
            await message.reply("You need Manage Server to configure Pokéball drops.", mention_author=False)
            return
        match = re.fullmatch(
            r"v!drops\s+(?:(?P<action>add|remove)\s+)?(?P<ids>\d+(?:\s+\d+)*)\s*"
            r"|v!drops\s+(?P<listing>list)\s*",
            message.content,
            re.I,
        )
        if not match:
            await message.reply(
                "Usage: `v!drops [add] <category id> [more ids]`, "
                "`v!drops remove <category id> [more ids]`, or `v!drops list`.",
                mention_author=False,
            )
            return
        categories = self.data["categories"].get(str(guild.id), [])
        if match.group("listing"):
            await message.reply("Drop categories: " + (", ".join(f"`{category}`" for category in categories) or "none"), mention_author=False)
            return
        action = (match.group("action") or "add").lower()
        category_ids = list(dict.fromkeys(int(raw_id) for raw_id in match.group("ids").split()))
        if action == "add":
            invalid = [
                category_id for category_id in category_ids
                if not isinstance(guild.get_channel(category_id), discord.CategoryChannel)
            ]
            if invalid:
                await message.reply(
                    "These IDs are not categories in this server: "
                    + ", ".join(f"`{category_id}`" for category_id in invalid)
                    + ". No categories were added.",
                    mention_author=False,
                )
                return
        data = copy.deepcopy(self.data)
        categories = data["categories"].setdefault(str(guild.id), [])
        changed = []
        unchanged = []
        for category_id in category_ids:
            if action == "add" and category_id not in categories:
                categories.append(category_id)
                changed.append(category_id)
            elif action == "remove" and category_id in categories:
                categories.remove(category_id)
                changed.append(category_id)
            else:
                unchanged.append(category_id)
        self.save(data)
        parts = []
        if changed:
            verb = "Added" if action == "add" else "Removed"
            parts.append(f"{verb}: " + ", ".join(f"`{category_id}`" for category_id in changed) + ".")
        if unchanged:
            status = "Already added" if action == "add" else "Not configured"
            parts.append(f"{status}: " + ", ".join(f"`{category_id}`" for category_id in unchanged) + ".")
        await message.reply(" ".join(parts), mention_author=False)

    async def dye_inventory(self, message: discord.Message) -> None:
        user = self.data["users"].get(str(message.author.id), {})
        dyes = user.get("dyes", [])
        view = DyeInventoryView(message.author.id, dyes)
        await message.reply(embed=view.embed(), view=view, mention_author=False)

    async def dye(self, message: discord.Message) -> None:
        match = re.fullmatch(r"v!dye\s+([a-z0-9]{7})\s+([a-z0-9]{7})\s*", message.content, re.I)
        if not match:
            await message.reply("Usage: `v!dye <dye code> <frame/background code>`.", mention_author=False)
            return
        dye_code, asset_code = (value.upper() for value in match.groups())
        data = copy.deepcopy(self.data)
        user = self.user(data, message.author.id)
        dye = next((item for item in user["dyes"] if item["code"] == dye_code), None)
        assets = self.bot.profile_inventory.get(str(message.author.id), {}).get("assets", [])
        asset = next((item for item in assets if item["code"] == asset_code), None)
        if dye is None or asset is None:
            await message.reply("I couldn't find that dye and owned asset. Check `v!dyeinv` and `v!inv`.", mention_author=False)
            return
        if asset["type"] != dye["type"]:
            await message.reply("That dye doesn't match the asset type.", mention_author=False)
            return
        user["dyes"].remove(dye)
        user["applied"].pop(asset_code, None)
        user["applied"][asset_code] = dye
        user.setdefault("selected", {})[asset["type"]] = asset_code
        self.save(data)
        await message.reply(f"Dye applied! Use `v!equip {asset_code}` to wear this copy.", mention_author=False)

    async def equip(self, message: discord.Message) -> None:
        match = re.fullmatch(r"v!equip\s+([a-z0-9]{7})\s*", message.content, re.I)
        if match is None:
            await message.reply("Usage: `v!equip <asset code>`.", mention_author=False)
            return
        code = match.group(1).upper()
        assets = self.bot.profile_inventory.get(str(message.author.id), {}).get("assets", [])
        asset = next((item for item in assets if item["code"] == code), None)
        if asset is None:
            await message.reply("That asset code is not in your inventory.", mention_author=False)
            return
        old_data = self.data
        data = copy.deepcopy(old_data)
        self.user(data, message.author.id).setdefault("selected", {})[asset["type"]] = code
        self.save(data)
        try:
            self.bot.set_profile_setting(message.author.id, asset["type"], asset["key"])
        except ValueError:
            self.save(old_data)
            raise
        await message.reply(f"Equipped asset `{code}` on your profile.", mention_author=False)


class DyeInventoryView(discord.ui.View):
    def __init__(self, user_id: int, dyes: list[dict[str, str]]) -> None:
        super().__init__(timeout=300)
        self.user_id = user_id
        self.dyes = dyes
        self.page = 0
        self.update_buttons()

    def update_buttons(self) -> None:
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 10 >= len(self.dyes)

    def embed(self) -> discord.Embed:
        items = self.dyes[self.page * 10:(self.page + 1) * 10]
        lines = [f"`{dye['code']}` - {dye['name'][:100]} ({dye['rarity']} {dye['type']})" for dye in items]
        embed = discord.Embed(title="Dye inventory", description="\n".join(lines) or "You don't have any dyes yet.", color=discord.Color.pink())
        embed.set_footer(text=f"Page {self.page + 1} of {max(1, (len(self.dyes) + 9) // 10)}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the inventory owner can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class PokeballView(discord.ui.View):
    def __init__(self, drops: PokeballDrops) -> None:
        super().__init__(timeout=None)
        self.drops = drops
        self.claimed = False
        self.message: discord.Message | None = None
        self.deadline: float | None = None
        self.claim_lock = asyncio.Lock()

    def start_expiry(self) -> None:
        self.deadline = time.monotonic() + BALL_LIFETIME
        task = asyncio.create_task(self.expire())
        self.drops.expiry_tasks.add(task)
        task.add_done_callback(self.drops.expiry_tasks.discard)

    async def expire(self) -> None:
        if self.deadline is None:
            raise RuntimeError("Pokéball expiry was not started")
        await asyncio.sleep(max(0, self.deadline - time.monotonic()))
        async with self.claim_lock:
            self.stop()
            if self.message is not None:
                try:
                    await self.message.delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    logger.warning("Could not delete expired Pokéball message", exc_info=True)

    @discord.ui.button(label="Open Pokéball", style=discord.ButtonStyle.primary)
    async def open_ball(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self.claim_lock:
            if self.claimed:
                await interaction.response.send_message("Someone already opened this Pokéball.", ephemeral=True)
                return
            if self.deadline is None or time.monotonic() >= self.deadline:
                await interaction.response.send_message("This Pokéball has expired.", ephemeral=True)
                return
            self.claimed = True
            try:
                result = self.drops.award(interaction.user.id)
            except (ValueError, OSError):
                self.claimed = False
                logger.exception("Could not save Pokéball reward for user %s", interaction.user.id)
                await interaction.response.send_message("I couldn't save your reward. Please try again.", ephemeral=True)
                return
            button.disabled = True
            await interaction.response.edit_message(content=f"{interaction.user.mention} {result}", view=self, allowed_mentions=discord.AllowedMentions.none())
