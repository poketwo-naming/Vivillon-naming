"""The `v!help` command list."""

from typing import Final

import discord

HELP_COMMAND_PATTERN: Final[str] = r"^v!help\s*$"
FIELD_VALUE_LIMIT: Final[int] = 1024

HELP_CATEGORIES: Final[list[tuple[str, list[tuple[str, str]]]]] = [
    (
        "🔍 Spawn Naming",
        [
            ("v!grab", "Reply to a Pokémon list to turn it into a clean grab list."),
        ],
    ),
    (
        "⏸️ Channel Controls",
        [
            ("v!p / v!pause", "Pause Pokétwo in this channel."),
            (
                "v!p all",
                "Pause active incense channels in this server (checks recent history).",
            ),
            (
                "v!poff / v!pon",
                "Disable/enable automatic pausing after confirmed incense purchases for this server.",
            ),
            ("v!r", "Resume Pokétwo in this channel (no arguments)."),
            ("v!r all", "Resume all paused Pokétwo channels in this server."),
        ],
    ),
    (
        "📌 Reserves",
        [
            ("v!r add <pokemon, ...> @member", "Reserve Pokémon for a member (`all <pokemon>` covers every form)."),
            ("v!r remove <pokemon, ...> [@member]", "Remove reserves."),
            ("v!addcategory <name>", "Create a reserve category."),
            ("v!categorycreate <category> <pokemon, ...>", "Append Pokémon to a category."),
            ("v!categorylist", "List categories and their Pokémon counts."),
            ("v!categorydelete <name> / v!cd <name>", "Delete a category."),
            ("v!r search <pokemon|@member>", "See who reserved a Pokémon, or what a member reserved."),
            ("v!r @you", "See your own reserved Pokémon."),
            ("v!r list", "Show every reserve in the server."),
            ("v!r e @owner", "Reply to a reserve list to hand those reserves to another member."),
            ("v!r clear", "Clear every reserve in the server."),
        ],
    ),
    (
        "✨ Shiny Hunt & Collection",
        [
            ("v!sh <pokemon> / v!sh all <pokemon>", "Hunt one Pokémon or every form."),
            ("v!sh remove <pokemon> / v!sh remove all <pokemon>", "Stop hunting those forms."),
            ("v!sh clear / clear all", "Clear your hunts, or the whole server's."),
            ("v!cl add <pokemon, ...>", "Add Pokémon or `all <pokemon>` forms to your pings."),
            ("v!cl remove <pokemon, ...>", "Remove Pokémon or `all <pokemon>` forms."),
            ("v!cl list", "Show your collection."),
            ("v!cl clear / clear all", "Clear your collection, or the whole server's."),
            (
                "v!tp / v!typeping",
                "Choose Pokémon types to get pinged for, including dual-type spawns.",
            ),
            (
                "v!tp clear all / v!typeping clear all",
                "Administrators: clear everyone's type pings in this server.",
            ),
        ],
    ),
    (
        "🥚 Breeding Boxes & Daycare",
        [
            ("v!box", "Show all your boxes and how full they are (limit 7,500 each)."),
            ("v!box create <name>", "Make a new box."),
            ("v!box append [box] [-c]", "Reply to a Pokétwo list to store its Pokémon; page arrows keep adding."),
            ("v!box list / remove / transfer / copy", "Browse, delete, move or duplicate stored Pokémon and boxes."),
            ("v!box tag / untag / tags / tagged", "Track egg moves on stored Pokémon."),
            ("v!box rename / delete / clear / reset", "Manage or wipe boxes."),
            ("v!dc [box]", "Pull 1-2 breedable pairs with a ready-to-paste daycare command."),
            ("v!dc settings", "Change how pairs are picked and shown."),
            ("v!boxhelp", "Full list of box commands."),
        ],
    ),
    (
        "🛍️ Profile Shop & Inventory",
        [
            ("v!shop", "Browse frames, backgrounds, and middle backgrounds for sale."),
            ("v!buy <asset name or code>", "Confirm a purchase and equip the profile asset."),
            ("v!inv", "View your Pokédollar balance and owned profile assets."),
            ("v!drops add/remove <category id> / v!drops list", "Manage Server: choose categories for incense Pokéball drops."),
            ("v!dyeinv", "View your normal and radiant dyes."),
            ("v!dye <dye code> <asset code>", "Apply a matching dye to an owned frame or background."),
            ("v!equip <asset code>", "Equip a specific copy of a profile asset."),
        ],
    ),
    (
        "⚙️ Settings & Utility",
        [
            ("v!settings", "Server settings: turn naming, assisted replies and ping-only mode on or off."),
            ("v!coff / v!con", "Administrators: disable or re-enable commands for this server; automatic bot features continue."),
            ("v!premium / v!premium add <tier> <server id>", "See Bronze/Silver/Gold spawn-naming limits; only the bot owner can grant a tier."),
            ("v!lowaccuracy #channel", "Post a link in that channel whenever a spawn scores under 90% (use `off` to disable)."),
            ("v!afk", "Your personal ping settings for shiny hunts and collections."),
            ("v!profile [@user]", "View your or another member's Pokémon catch stats."),
            ("v!backfill [#channel or category id] / v!backfill continue <#channel> / v!backfill stop", "Admins or the configured role: backfill profile data in one channel, one category, from a channel down to the last one, or across the server, or stop a scan."),
            (
                "v!permission <role id> / off",
                "Manage Server: grant a role access to protected commands.",
            ),
            ("v!settime @role ...", "Choose the roles pinged for timed spawns."),
            ("v!timereset", "Reset that timer."),
            ("v!event", "Start a chat event."),
            ("v!ping", "Check the bot's response time."),
            ("v!api", "See how many Pokémon were recognized recently."),
            ("v!help", "Show this list."),
        ],
    ),
]


def build_help_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Vivillon Command List",
        description="Everything the bot can do, grouped by purpose. Names in `<>` are required, `[]` optional.",
        color=discord.Color.from_rgb(0x9B, 0x8C, 0xE8),
    )
    for title, commands in HELP_CATEGORIES:
        chunks: list[list[str]] = [[]]
        length = 0
        for usage, text in commands:
            entry = f"`{usage}`\n-# {text}"
            if chunks[-1] and length + len(entry) + 1 > FIELD_VALUE_LIMIT:
                chunks.append([])
                length = 0
            chunks[-1].append(entry)
            length += len(entry) + 1
        for index, chunk in enumerate(chunks):
            embed.add_field(
                name=title if index == 0 else f"{title} (cont.)",
                value="\n".join(chunk),
                inline=False,
            )
    embed.set_footer(text="Tip: v!boxhelp explains every box command in detail.")
    return embed
