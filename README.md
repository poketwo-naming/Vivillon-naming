# Vivillon-naming

A Discord application bot that recognizes Pokétwo spawn images with local
reference-image matching and an optional OpenAI vision fallback, then replies
with the predicted Pokémon name and confidence percentage.

## Requirements

- Python 3.10 or newer
- A Discord application/bot token
- An OpenAI API key only if you want to enable the optional vision fallback
- The Pokétwo bot ID for the server where you will use the bot

Without an OpenAI API key, spawn images are checked only against the local
reference-image bank and are not sent to OpenAI.

This project uses a regular Discord bot account, not a user-account self-bot.
Enable **Message Content Intent** for your application in the Discord Developer
Portal, invite it to your server with permission to read and send messages, and
ensure it can view the channel where Pokétwo spawns appear. Discord may require
approval for privileged intents on larger bots.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```sh
   python -m pip install -r requirements.txt
   ```

3. Set the required environment variables:

   ```sh
   export DISCORD_TOKEN="your-discord-bot-token"
   export OPENAI_API_KEY="your-openai-api-key"   # optional
   export POKETWO_BOT_ID="the-poketwo-bot-user-id"
   ```

   `POKETWO_BOT_ID` identifies the account whose spawn messages the bot
   monitors. Generated catch commands target `<@716390085896962058>`.

   The bot responds to commands in server channels and threads. Spawn naming
   requires a premium tier assigned to that server with `v!premium add`; other
   commands and features remain available without a tier. Direct messages are
   otherwise ignored; tier status requires a server context.
   Bronze, Silver, and Gold allow up to 100, 200, and 300 simultaneous spawn
   recognitions per server. The bot also has a shared ceiling of 300 requests;
   set `MAX_CONCURRENT_VISION_REQUESTS` between 1 and 300 to lower it for your
   OpenAI project’s rate limits. The client retries temporary API errors.
   A larger channel count does not increase OpenAI API quota, so billing,
   project limits, and the exact error in the bot logs still matter if requests
   continue to fail. `OPENAI_MODEL` can select another vision-capable
   Chat Completions model.

   `v!premium` displays Bronze/Silver/Gold tier cards and shows which tier is
   active for the current server. Only the bot owner, and only from the main
   server (`1530949341013868635`), can grant access with
   `v!premium add bronze <server id>`, `v!premium add silver <server id>`, or
   `v!premium add gold <server id>`. Tier assignments persist in
   `data/premium_servers.json` (or the path set by `PREMIUM_SERVERS_FILE`).

4. Start the bot:

   ```sh
   python bot.py
   ```

## Container deployment

For an always-on host or VM, build and run the bot as a container:

```sh
docker volume create vivillon-data
docker build -t vivillon-naming .
docker run -d --name vivillon-naming --restart unless-stopped \
  --env-file .env \
  -e DATA_DIR=/data \
  -e PROFILE_DATA_FILE=/data/profile_data.json \
  -e PREMIUM_SERVERS_FILE=/data/premium_servers.json \
  -e STARBOARD_SETTINGS_FILE=/data/starboard_settings.json \
  -e SERVER_SETTINGS_FILE=/data/server_settings.json \
  -v vivillon-data:/data \
  vivillon-naming
```

Create `.env` with `DISCORD_TOKEN` and `POKETWO_BOT_ID`; `OPENAI_API_KEY` is
optional. Keep this file private and out of GitHub. The Docker image runs
`python bot.py`. The named volume preserves profile and board settings when
you recreate the container. If upgrading an older container that kept other
JSON files under `/app/data`, copy those files into the volume before replacing
it; setting `DATA_DIR=/data` does not migrate them automatically.

This container is a persistent Discord Gateway bot, not an HTTP service.
Cloud Run services require an HTTP listener, so this Dockerfile alone does not
make the bot suitable for a Cloud Run service.

The bot also handles spawns whose image or text Pokétwo adds by editing the message, processes each spawn message once, and retries temporary image-download or recognition failures up to three times before replying with an error.

To test an image manually, post it with `v!test` as the message caption. A
Missingno match immediately posts a staff warning.
Other test matches never send a catch command. A listed Pokémon recognized by
`v!test` also posts a clearly labeled test preview to the configured Normal
Starboard; its level and IV are shown as unknown.
Use `v!test shiny` with an image to post shiny test previews to the same
configured destinations as a real shiny catch: Vivillon Starboard and
Shinyboard, never Normal Starboard. Preview level and IV are unknown. Each
starboard embed includes a `Jump to message` link to
its source catch (or to the test command for a preview). Shiny embeds use a
small thumbnail. Only Shinyboard embeds use an animated shiny image: a 3D GIF
from Project Pokémon when available, or an animated sprite for unsupported
species/forms. Other starboards use static artwork in the shiny form.
After a Missingno match (real or `v!test`), Vivillon denies Pokétwo's Send Messages
permission in that channel (needs Manage Permissions) so no more spawns appear.
Vivillon keeps handling everything else normally. Use `v!p` or `v!pause` to pause
Pokétwo in the current channel; the bot replies `Incense paused.` Use `v!r` with
no arguments to restore Pokétwo's permission and resume the channel. Use
`v!r all` to resume all
paused channels in the current server. Use `v!p all` to pause every channel in
the current server with an active incense. It checks the latest 100 messages in
channels without a tracked incense, so the bot needs permission to read channel
history to recover incense activity it missed.

Image analysis uses `high` detail by default for more reliable recognition, including screenshots with surrounding Discord UI; set `OPENAI_IMAGE_DETAIL` to `low` or `auto` to change it. For speed, OpenAI fetches the spawn image directly from its URL (the bot only downloads and uploads it itself if that fails), and model replies are capped at 60 tokens.

When naming is enabled, the bot attempts to recognize every Pokétwo spawn with
an image and replies with one predicted name and its estimated confidence
percentage (for example, `Pikachu: 85.00%`). Registered reserve, shinyhunt,
collection, and type-ping members are mentioned when they match; registrations
do not limit which spawns are named. The confidence is an estimate, not a
calibrated probability. Real-spawn guesses at or below 50% are appended to
`pokemon_confidence.csv` in the project root, creating it with a header if needed.
Real spawns matching a name in that CSV are also saved to
`pokemon_confidence_review/` for manual review.
The bot owner can reply to a recognition alert with `v!correct <correct name>`
(for example, `v!correct Zygarde Core`). The bot retrieves the original spawn
image, records its SHA-256 hash, corrected name, previous guess and confidence
in `data/pokemon_corrections.csv`, and immediately uses that name for identical
image bytes, including after a restart. Correcting a different image does not
change general matching, and resized or re-encoded copies are not exact matches.
The original spawn and its image must still be accessible. To persist corrections
in a container, set `POKEMON_CORRECTIONS_FILE=/data/pokemon_corrections.csv`
with `/data` mounted on persistent storage.
If recognition has no verified match, the bot reports
when no guess is available, without posting an error reply in the spawn channel.
If the vision model is unavailable, the bot names the best local reference
candidate when possible and reports it as a low-confidence guess. The vision
model compares visible traits such as silhouette, proportions, face, colors,
and markings to identify Pokémon across the National Pokédex and distinguish
similar species and forms. It distinguishes Finizen from Palafin by checking
for Palafin's red, heart-shaped chest/underside mark when visible. Image
recognition can still make mistakes, so check guesses before relying on them.
Guesses below 50% are still named, and a
low-accuracy alert mentioning the configured alert recipient, with the
confidence and source link, is sent to the recognition alert channel. An
agreeing local match with sufficient feature votes raises a low-confidence
vision guess to at least 85%. An unverified Vivillon form prediction is
still named at low confidence. It then
posts the matching Pokétwo catch command as inline code for easier copying,
preceded by a bold “Copy Here >” label, when Assisted mode is on. Maushold's
Family-of-Three and Family-of-Four appearances are displayed simply as
Maushold. A separate
desktop copy card
below it shows “Catch [Pokémon]”, “Copy Below”, and the Pokétwo catch command.
Regional form names are displayed with their demonyms, such as Alolan,
Galarian, and Hisuian, even when a model or form catalog uses the region name.
Assisted mode can be turned off to show names and mentions without catch commands.
Discord displays both copy formats on mobile and desktop. Discord's copy controls
depend on the client; the bot cannot directly write to a user's clipboard. Pure
Ice, Grass, Fire, Water, Normal, and Electric spawns use their custom emojis
inline with the guessed name and no embed. Configured paired types that include
any of those types show both corresponding custom emojis inline. Other
configured type matches show their icons beside the guessed name in an embed,
with the catch command in the embed description when Assisted mode is on. Other
dual-type Pokémon keep the regular text reply. Reservation, shinyhunt,
collection, and type-ping mentions remain active for both reply styles.
Pokétwo or Discord may ignore or restrict commands sent by another bot account.
If the prediction is `Missingno.` or `???`, the bot asks for a staff member; it
does not send a catch command for that spawn.

This application does not bypass those restrictions.

Use `v!settings` to configure naming separately for each server. Members with
Manage Server permission can turn naming on or off, disable Assisted mode to
remove catch-command copy messages while keeping Pokémon names, or enable
**Only Pings** under **Naming**. Only Pings is off by default. When enabled,
ordinary spawn replies are sent only if a reserve, shiny hunt, collection, or
type ping matches; personal AFK settings still apply. The bot still recognizes
spawns and reports recognition problems, and Missingno's safety warning still
appears. Test commands continue to show their normal output. Older `pings`
settings remain ignored, so servers must explicitly turn Only Pings on.
Settings are saved to `server_settings.json` by default; set
`SERVER_SETTINGS_FILE` to use another path.

Manage Server members can use `v!permission <role id>` to grant that server role
access to `v!grab`, `v!test`, reserve and category commands, `v!settings`,
`v!settime`/`v!timereset`, `v!event`, and `v!backfill`. Existing reserve managers,
Manage Server members, and administrators retain their existing access where
those commands already require those permissions. For listed commands that were
previously public, the configured role is required. Commands not listed keep
their current permissions. Only Manage Server members can configure the role.
Use `v!permission` to view the configured role or `v!permission off` to remove
it. The setting is stored in `command_permissions.json` by default; set
`COMMAND_PERMISSIONS_FILE` to use a different persistent path.

Server administrators can use `v!coff` to disable `v!` commands for everyone
in that server and `v!con` to re-enable them. While commands are disabled,
automatic bot features continue to run; only these two administrator controls
remain available. The lock is stored in `command_locks.json` by default; set
`COMMAND_LOCKS_FILE` to use a different persistent path.

Open **Starboard** from `v!settings` to choose separate **Vivillon Starboard**,
**Shinyboard**, and **Normal Starboard** channels. The Vivillon Starboard posts
shiny catches, catches with 90% IV or higher, catches below 10% IV, MissingNo.
catches, and Gigantamax catches. The Normal Starboard posts Pokétwo catches and
Catch Detection System reports for configured regional forms and featured
Pokémon, with the catcher, Pokémon, level, IV, thumbnail, and catch time. Shiny
catches also post to the shinyboard. Catch Detection System shiny, high-IV,
low-IV, MissingNo., and Gigantamax reports use the Vivillon Starboard, with
the Gigantamax emoji on both sides of Gigantamax capture titles. The bot needs
access to that custom emoji and permission to use external emojis where needed.
Shiny catches are also posted to the shinyboard
when configured. Shiny posts include the catcher, Pokémon, level, IV, gender
when Pokétwo provides it, and a chain only when the catch message identifies
one. Shiny Terapagos catch embeds use the bundled custom thumbnail. Normal
Starboard Pokémon Spotlight embeds use the same static 2D artwork
as naming thumbnails. Starboard channel choices and the shiny count are saved in
`starboard_settings.json` by default; set `STARBOARD_SETTINGS_FILE` to use
another path. Each caught shiny increments the saved shiny count and renames
the shinyboard with a numeric suffix (for example, `shiny-board-1`, then
`shiny-board-2`). The bot needs Manage Channels permission to rename the
channel; catches are still counted if Discord prevents a rename.

Shinyboard embeds use animated shiny GIFs from the
[Project Pokémon sprite index](https://projectpokemon.org/home/docs/spriteindex_148/)
where a 3D model is available, including the
[Generation 8 models](https://projectpokemon.org/home/docs/spriteindex_148/3d-models-generation-8-pok%C3%A9mon-r123/).
For unsupported species/forms, the Shinyboard uses Pokémon Showdown's animated
shiny sprite instead. Project Pokémon credits PKParaiso for the Generation 8
animations; the bot links to hosted images and does not bundle them. Other
starboards continue to use static shiny artwork.

Use `v!api` in the configured server to view the number of Pokémon recognized
since restart, recent inference and response-time statistics, current request
load, and configured recognition backend in a three-column status layout.
Store and JSON load timings are not measured by this bot; CSV loading is not
used. It also counts incenses across all servers the bot is in. Incense status
is tracked from observed buy/stop commands and Pokétwo spawn messages that
report `Incense: Active` or `Incense: Inactive`, including embed footers, with
a one-hour fallback timer. A previously running incense is detected when
Pokétwo next reports its status. Incense tracking is saved in `incenses.json`
(override with `INCENSE_TRACKING_FILE`). A confirmed `@Pokétwo inc buy -y`
purchase also pauses Pokétwo in that channel and replies
`Incense has been paused.` Use `v!r` with no arguments to resume the channel.
Use `v!poff` to disable automatic pausing after a confirmed incense purchase in
this server, and `v!pon` to re-enable it. This setting is saved in
`auto_pause_incense_settings.json` (override with
`AUTO_PAUSE_INCENSE_SETTINGS_FILE`).

Use `v!event` to start an event. The organizer can choose **Chat event**, and
members join by reacting with ⏲️ to the sign-up message during its one-minute
sign-up window; at least two people must join for the event to proceed. The
organizer privately enters any positive duration in minutes or hours (for
example, `7 minutes` or `2 hours`; a number by itself means minutes). Once
sign-ups close, only joined members' messages count, and each sentence must
contain at least four words. The bot posts the sentence totals for everyone who
joined. The bot needs permission to add reactions and manage messages so it can
remove the sign-up reaction when registration closes.

## Pokémon reservations

Any server member can view reservations with `v!r list`, search who reserved a
Pokémon with `v!r search pikachu`, or see one member's reserved Pokémon with
`v!r search @member`. Members can also see their own reserved Pokémon with
`v!r @you`. Use `v!r search all arceus` to list Arceus by type
(for example, `fairy arceus @member`) and show the reservers for each type.
Use `v!r search all pichu` for its regular and spiky-eared forms. This catalog
covers alternate and regional forms across Pokémon. Results
with multiple pages show previous/next arrow buttons beneath the embed. The
catalog in `pokemon_forms.json` is a static snapshot based on the
[PokeAPI CSV data](https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv).
To regenerate it, download `pokemon.csv`, `pokemon_forms.csv`,
`pokemon_species.csv`, and `pokemon_types.csv` into one directory and run
`python generate_pokemon_forms.py <csv-directory>`.

Only members with the reserve-manager role (role ID `1532820386511720579`) can
change reservations. They can reserve Pokémon for a server member with:

```text
v!r add pikachu, eevee @member
v!r add all arceus @member
```

Names must match a Pokémon in the bot's catalog; unknown names are rejected
instead of being saved as reservations.

Use `all <pokemon>` to reserve every form of that Pokémon; the member is then
mentioned when any matching form spawns. More than one member can reserve the
same Pokémon. When a reserved Pokémon spawns, the bot lists and mentions its
reserved members in a `Reserved:` line above the catch command. The
`Reserved:` line is omitted when no one reserved that Pokémon. Other members
are not mentioned. Reservations are stored in
`reserves.json` by default; set `RESERVES_FILE` to a different path if needed.
Keep that file on persistent host storage to retain reservations across
restarts. When a Pokémon has custom event forms, `v!r add all <pokemon>`
offers **Event forms only** or **All forms**. For example, event-only Applin
reserves Enchanted Applin and Rotten Applin; all forms also includes regular
Applin. The bot must be able to read and send messages in the command channel
as well as the spawn channel.

Reserve managers can create server-specific categories and append Pokémon to
them:

```text
v!addcategory rare
v!categorycreate rare pikachu, eevee, all arceus
v!categorylist
v!r add rare @member
v!r remove rare @member
v!categorydelete rare
```

Category names are single words and cannot be Pokémon names. Repeating
`v!categorycreate` appends new Pokémon without duplicating existing entries.
Adding or removing a category with `v!r` expands it into its Pokémon; deleting
the category does not change reservations that were already expanded. The
`v!cd <name>` alias also deletes a category. Category data is stored in
`reserve_categories.json` by default; set `RESERVE_CATEGORIES_FILE` to use a
different persistent path.

Members with the reserve-manager role can remove reservations with
`v!r remove pikachu, eevee @member` or `v!r remove pikachu, eevee, @member` to
remove them only from that member's reserves, or
`v!r remove pikachu, eevee` to remove those Pokémon's reservations for everyone
in the current server. Use `v!r remove all arceus @member` to remove that
member's all-forms reservation. A single Pokémon name can still be used in
either command.
Successful member-specific removals reply with `Pikachu, Eevee removed from
@member Reserves`.

Use `v!r clear` to clear every reservation in the current server. The bot asks
for confirmation with Yes and No buttons; Yes clears the server's reservations,
and No cancels the command.

Any server member can select one Pokémon to shinyhunt with `v!sh absol`, or
track every form with `v!sh all arceus`. `Riffex` is accepted as an alias for
Toxtricity. A new selection replaces
their previous shinyhunt in that server. Running `v!sh` without a Pokémon name
reports their current selection. Use `v!sh remove absol` to remove your own
shinyhunt for that Pokémon, or `v!sh remove all arceus` to remove your all-forms
shinyhunt; use `v!sh clear` to stop hunting and remove all your shinyhunts in
that server. Server administrators can use `v!sh clear all` to clear every
member's shinyhunts in the current server, after confirming. Other shinyhunt
commands do not affect other members. When a matching Pokémon spawns, registered
hunters are mentioned in a `Shinyhunt:` line. If the Pokémon has a reservation,
the existing `Reserved:` mentions take precedence over shiny-hunt mentions.
Shiny-hunt registrations are stored in `shinyhunts.json` by default; set
`SHINYHUNTS_FILE` to use a different path.

Any server member can add Pokémon to their collection with
`v!cl add pikachu, eevee`, remove one or more with `v!cl remove pikachu, eevee`,
or use `v!cl add all alcremie` and `v!cl remove all alcremie` to add or remove
every catalogued form at once. They can clear their own collection in the
current server with `v!cl clear` and view their list with `v!cl list`. Server
administrators can use `v!cl clear all` to
clear every member's collection in the current server, after confirming.
Removing Pokémon from a collection leaves other members' entries intact. Adding
a Pokémon that is already in your collection
reports that it is already added and does not create a duplicate. Collection
entries are stored in `collections.json`
by default; set `COLLECTIONS_FILE` to use a different path. The list is
paginated at 20 Pokémon per page with previous/next buttons. On a spawn, a
reservation takes precedence over shinyhunt, collection, and type-ping mentions.
Otherwise, the bot shows `Shinyhunt:`, `Collection:`, and `Typeping:` lines only
for groups with matching members. If no one matches, it shows the normal naming
reply without empty mention lines.

Use `v!tp` or `v!typeping` to choose one or more Pokémon types for spawn pings.
A Pokémon matches each of its types, so enabling Normal also matches a
dual-type Pokémon that has Normal as either type. Matching members are
mentioned on a separate `Typeping:` line.
Selections are saved per member and server in `type_pings.json` by default; set
`TYPE_PINGS_FILE` to use a different path.
Server administrators can use `v!tp clear all` or `v!typeping clear all` to
clear every member's type pings in the current server. The bot asks for
confirmation and leaves other servers' settings unchanged.

Use `v!afk` to open your personal ping settings. The **Shiny Hunt** and
**Collection** buttons independently turn those notifications on or off; the
settings are saved per member and server in `afk_settings.json` by default
(override the path with `AFK_SETTINGS_FILE`). Both are on by default, preserving
existing notification behavior.

Use `v!profile` to view your catch stats, or `v!profile @user` to view another
member's stats in the current server where Vivillon is enabled. Profile catch
totals and records are tracked separately for each server. The card counts
total catches, shinies, catches below 10% IV, catches at or above 90% IV, Gigantamax catches,
and Missingno catches. Each `Congratulations @user! You caught a` message
adds one to Total; a spawn by itself does not count, and the total has no cap.
Server administrators can run `v!backfill` in that server to scan readable
text channels and active threads for earlier catches. Use `v!backfill <channel>`
for one channel or `v!backfill <category id>` for only the channels in that
category. Use `v!backfill continue <channel>` to scan from that channel down
through the last channel in the server's channel list. Run `v!backfill stop` to
stop an active scan; catches processed before stopping are saved. The bot needs
View Channel and Read Message History permissions; channels it cannot read are
reported and excluded. The bot posts cumulative totals and a scanned-message
count after each channel. The card's right side shows each record's level, Pokémon, gender
(when provided in the catch message), and IV percentage for the highest and
lowest IV catches, plus the highest and lowest IV among shiny catches. The
profile card is public. Its
public **Edit** menu appears only after the owner presses **Edit**; changing a
setting updates the card without a confirmation reply. The card has the normal
gray background on its left and right sides by default. The bot owner can use
`v!profile @user` to preview another member's
appearance. Only the bot owner can edit this temporary preview; changes update
the public preview card but are not saved to the member's profile. Other
members can still view profiles, but only edit their own. The background picker
also offers blurred Cosmog, Hisuian Zorua, and Moon Night images, plus a
blurred Meadow Night image and a blurred, rotated Eevee image; the middle
column defaults to white and can also use Cosmog, Hisuian Zorua, or Eevee.
Image-based middle backgrounds receive a subtle color tint sampled from the
surrounding background, helping the two images blend together. Text is drawn
above both background layers. The
default picker choices are labeled **Default text color**, **Default
background**, and **Default middle background**. The frame picker offers
**No frame**, **Mystic**, **Gem**, and **Nightflower**. The Buneary background,
Buneary middle background, and Flower Spring frame are limited to their
designated profile; the Slakoth background, Slakoth middle background, and
Moonlit frame are limited to a different designated profile. The Marshadow
background and middle background, plus the Moonveil frame, are limited to a
third designated profile. Moonveil enlarges the profile card to fit its frame.
The Jirachi background, middle background, and frame are limited to a
fourth designated profile. Every profile also gets a **Music** picker in the
edit menu; choosing **Return to me** DMs the owner a one-hour audio file
(`music/return_to_me.ogg`); if DMs are closed, the owner gets
`music/return_to_me.mp3` as a private reply instead. Each
set is hidden from other members and reset to defaults if found in their
saved settings.
Profile choices and per-server totals are saved in `profile_data.json` by
default; set `PROFILE_DATA_FILE` to use another path.

Use `v!shop` to browse Frames, Backgrounds, and Middle backgrounds, and
`v!buy <asset name or code>` to confirm a purchase. Purchased assets are added
to the profile, equipped immediately, and shown by `v!inv`. Existing equipped
visual assets are migrated into their owners' inventories; profile music is not
an inventory item. The inventory and shop catalog are stored separately in
`profile_inventory.json` and `profile_shop.json` by default. The inventory file
is private runtime data and is ignored by Git. Balances start at zero Pokédollar.
An asset can be purchased any
number of times. Every purchase charges its price and adds a separate inventory
line with its own seven-character code, even when the asset is already owned.

Add assets and prices to `profile_shop.json`. `type` is `frame`, `background`,
or `middle_background`; `key` must match an existing profile asset key. Shop
codes are generated automatically and remain stable per catalog item; each
owned copy gets a separate unique code shown in `v!inv`.

```json
{
  "items": [
    {"type": "frame", "key": "mystic", "price": 100},
    {"type": "background", "key": "cosmog", "price": 75}
  ]
}
```

The optional `currency` field defaults to `Pokédollar`. `PROFILE_SHOP_FILE` and
`PROFILE_INVENTORY_FILE` can override the default data paths.
When Pokétwo reports a completed Bingo quest, its completing member is named in plain text (no mention)
and awarded 25 Pokédollars. Completing a full blackout awards 200 Pokédollars.

### Incense Pokéball drops and dyes

Members with Manage Server can enable drops in every text channel within
multiple categories. Use `v!drops <category id>`, `v!drops add <category id>`,
or put several space-separated IDs in one command, such as
`v!drops 123456789 987654321`. Repeated commands add to the existing list.
Use `v!drops remove <category id> [more ids]` to remove categories and
`v!drops list` to see configured IDs. Enable Discord
Developer Mode to copy a category's ID. The bot needs View Channel, Send
Messages, Embed Links and Attach Files in the chosen channels.

When Pokétwo posts a spawn in a tracked, unpaused incense channel, a three-minute
timer starts for that server. While those spawns continue, one small Pokéball
appears every three minutes in a random accessible text channel in the
configured categories. The first person to press its button gets the reward;
the Pokéball message and image stay visible, but its button is disabled ten
seconds after posting if it hasn't been claimed already. A restart ends existing
claim sessions and starts a new timer after the next incense spawn.

Use `v!droplog #channel` or `v!droplog <channel id>` to select a text channel
for permanent drop logs, and `v!droplog off` to disable them. Manage Server
permission is required, and the bot needs View Channel and Send Messages in the
log channel. Each log records the drop channel and time, with a **Jump to drop**
button pointing to the exact message. The link continues to work after the
button expires, as long as the message hasn't been deleted and the viewer can
access the drop channel. Anyone viewing the log can see the drop channel; make
sure the log channel's permissions are appropriate.

Each claim normally awards either 0–500 XP or 0–1,000 Pokédollars, with equal
chance and an inclusive, uniformly random amount. Zero gets an unlucky message.
Levels are global across servers and start at 0: level 1 needs 500 XP, then
each following level costs 100 more XP than the previous one. The profile card
shows the member's Discord avatar, display name, and level.

Each claim rolls for a dye before XP or money: glow dyes are about 1 in 75,000,
radiant dyes 1 in 37,500 and normal dyes 1 in 17,500 (`DYE_ODDS` in
`pokeball_drops.py`). A rarity with no catalog entries awards XP or money
instead. `data/dyes.json` ships 150 dyes (50 normal, 50 radiant, 50 glow) with
cloth images in `assets/dyes/`. Every dye has its own code, so two people with
the same color have different codes. `v!dyeinv` lists your dyes as
`<cloth image> <code> - <name>`. `v!dye <dye code> <asset code>` uses a dye once
on any owned frame or background, and `v!useddyes` lists used dyes with
"used" after the name. Use `v!equip <asset code>` to wear a specific copy.
Normal dye adds a color filter, radiant a two-color sparkly filter, and glow
the same plus a glow.

To change the catalog, edit `data/dyes.json` (or set `DYE_CATALOG_FILE`):

```json
{
  "dyes": [
    {"name": "Pink", "type": "any", "rarity": "normal", "color": "#FF88CC", "image": "assets/dyes/normal/01.png"},
    {"name": "Gold", "type": "any", "rarity": "radiant", "color": "#FFD700", "color2": "#FF00FF"}
  ]
}
```

Each name must be unique; `type` is `any`, `frame` or `background`, `rarity` is
`normal`, `radiant` or `glow`, `color`/`color2` are six-digit hex colors and
`image` is an optional cloth image path. Edits are picked up on the next claim.
Categories, XP, owned and used dyes are saved in `data/pokeball_drops.json` (or
`POKEBALL_DATA_FILE`). Keep it and `profile_inventory.json` on persistent storage.

## Exchanging reservations

Reserve managers can move one member's reservations to others. Post a list
with one member per line (commas separate Pokémon, and `all <pokemon>` works):

```
@jade - pikachu, eevee
@bluebird - sylveon, hatterene
@snowii - all arceus
```

Then reply to that message with `v!r e @owner` (or `v!r exchange @owner`). The
bot shows an embed ("You want to exchange from @owner to those users") with
**Yes** and **No** buttons. **Yes** replies "Reserves exchanged." and moves each
listed Pokémon that `@owner` has reserved to the member on its line; **No**
replies "Exchange cancelled." If `@owner` doesn't have some listed Pokémon, small
text under the list names them and suggests "Do you mean @member?" for members
who do have them. Only the command user (with the reserve manager role) can
press the buttons (they appear even when `@owner` has none of the listed Pokémon), and unanswered prompts expire after 3 minutes.

In an exchange, `all <pokemon>` moves every form the owner has reserved, including regional forms such as Galarian or Alolan ones, not only the all-forms reservation.

Reserve lists (`v!r search @member`, `v!r list`) and the exchange prompt show an all-forms reservation as each form separately (for example, each Urshifu form) when form data is available. Species without form data still show as "all forms of <pokemon>". The same `all <pokemon>` prefix works for reserves, collections, and shiny hunts; use `remove all <pokemon>` to remove the matching all-forms entry.

## Grabbing a list with `v!grab`

Reply to any message or embed that contains Pokémon names, with `v!grab`: a `v!r search` result, a plain list, or a labelled list such as `Regional — @user - Zorua`. The bot finds the Pokémon names on each line (ignoring labels, emojis and formatting); the list shows only Pokémon names, and the `@user` beside each Pokémon is remembered for Add reserves. Use `|` to separate owner groups on one line (for example, `@user1 - Sneasel | @user2 Amaura`) so each Pokémon stays with its own owner. Names come from `pokemon_names.json`; listed Pokémon are not expanded into their other forms. The bot builds
a separate list of every Pokémon (not just the visible page), all in one message with no page limit. Only the person who ran `v!grab` can use its buttons:

- **Order** – sorts the list alphabetically (click again to restore the original order).
- **All forms off / on** – turns green when on and preserves `All` only for
  Pokémon marked as an all-forms entry in the source list. It does not infer
  all-forms reservations from a Pokémon having alternate forms.
- **Custom emoji** – opens a box for emojis separated by commas; they are put in
  front of the Pokémon in order and repeat (emoji 1, emoji 2, emoji 1, ...).
- **Copy** – sends you the current list (with the order, All forms and emojis as shown) as a plain private message containing only the list, with any emojis added through Custom emoji, so you can copy it directly. Discord doesn't let bots write to your clipboard directly. Custom server emojis stay as text and display once pasted.
- **Add reserves** – reserve managers only, and only when the list has an `@user`
  behind the Pokémon (`pikachu - @user1`). Shows an embed of which Pokémon goes to which user and asks "Are you sure you want to add all
  reserves?" with Yes/No; Yes adds each Pokémon to its user like `v!r add`
  (using `all <pokemon>` where All forms is on). Pokémon without an `@user` are skipped. After Yes, the bot posts each reserve as two separate messages, one at a time: `v!r add <pokemon> @user`, then `<Pokémon> added to @user` (without pinging anyone). Large lists take a while because Discord rate-limits message sending.

After a bot restart, `v!grab` on an old search message only sees the page shown in it.

## Org bot API

Vivillon can expose a small HTTP API so your org bot can manage reserves. It is off unless you set:

| Variable | Meaning |
| --- | --- |
| `ORG_BOT_API_KEY` | Secret the org bot sends as `Authorization: Bearer <key>`. Enables the API. |
| `ORG_GUILD_ID` | Server whose Vivillon reserves the org bot adds to / removes from. |
| `ORG_API_PORT` | Port to listen on (falls back to `SERVER_PORT`, then `PORT`, then `8080`). The host must expose this port publicly. |
| `ORG_RESERVES_FILE` | Optional. Org list file, default `org_reserves.json`. |
| `ORG_RESTRICTIONS_FILE` | Optional. Slot rules, default `org_restrictions.json`. |

Restriction file (optional; slots without a rule allow anything). A shared rule
can be assigned to a list of slot names, or individual slot rules can be
specified using the legacy mapping format. `allowed` is a whitelist: when
present, Pokémon not listed are rejected. `blocked` rejects listed Pokémon and
can also be used alongside `allowed`.

```json
{"shared": {"allowed": ["Pikachu", "Eevee"]}, "slots": ["slot1", "slot2"]}
```

Legacy per-slot rules remain supported:

```json
{"slots": {"slot1": {"allowed": ["Pikachu", "Eevee"]}, "slot2": {"blocked": ["Mewtwo"]}}}
```

All requests except the health endpoint need the `Authorization: Bearer <ORG_BOT_API_KEY>` header and return JSON with `"success"`. Errors use `{"success": false, "error": "..."}`: `400` invalid request, `401` unauthorized, `403` not allowed in that slot, `404` Pokémon not found / not reserved.

- `GET /api/org/health` needs no key; open it in a browser to check the URL works (`{"success": true, "status": "ok"}`).
- `POST /api/org/validate` with `{"pokemon": "Pikachu", "slot": "slot1"}` checks the name exists and the slot allows it. `slot` is optional; `"All Eevee"` is accepted for all forms.
- `POST /api/org/reserves` with `{"action": "add" or "remove", "pokemon": "Pikachu", "userId": "123456789012345678", "slot": "slot1"}` adds/removes the reserve in the org list and Vivillon's saved reserves. Individual adds return `409` if the Pokémon belongs to a configured category, including overlapping "All" forms; use the category endpoint instead. `slot` is optional for add, but required for remove. Removal matches Pokémon, user ID, and slot exactly; another slot's reserve for the same Pokémon/user is preserved. Success: `{"success": true, "action": "remove", "pokemon": "Pikachu", "userId": "...", "slot": "slot1", "changed": true}`.
- `GET /api/org/categories` lists categories for `ORG_GUILD_ID`: `{"success": true, "count": 1, "categories": [{"name": "regional", "pokemon": ["Pikachu", "Eevee"], "count": 2}]}`. Vivillon reads this from its `RESERVE_CATEGORIES_FILE` data.
- `POST /api/org/reserves/category` with `{"category": "regional", "userId": "123456789012345678"}` reserves every Pokémon in that category for the user. Success returns `{"success": true, "category": "regional", "userId": "...", "count": 2, "pokemon": ["Pikachu", "Eevee"], "changed": true}`. Repeating the same claim is idempotent (`changed: false`); conflicts return `409` without applying a partial claim.
- `GET /api/org/reserves` lists the org's reserves: `{"success": true, "count": 1, "reserves": [{"pokemon": "Pikachu", "userId": "...", "slot": "slot1", "type": "individual"}]}`. Every entry includes `slot` (category entries use `null`). Category reservations have `"type": "category"` and a `"category"` name. Use this for `!res list` and slot-specific releases.
- `POST /api/org/reset` (for `!org start`) clears all Org entries, including category claims, and all Vivillon reservations for `ORG_GUILD_ID`. It returns `{"success": true, "cleared": 2, "clearedVivillon": 3}`. Reserves for other guilds are preserved.

Example:

```
curl -X POST https://YOUR-HOST:PORT/api/org/reserves \
  -H "Authorization: Bearer YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"action":"add","pokemon":"Pikachu","userId":"123456789012345678"}'
```

## Reference images (faster recognition)

Put each Pokémon's spawn pictures in its own folder inside `pokemon_images/`, named exactly like the Pokémon (`pokemon_images/Abomasnow/`, `pokemon_images/Mega Absol/`). Use real spawn images Pokétwo posts, ideally with different backgrounds (about 10 to 25 each).

Files named `user-reference-*` are indexed separately as exact byte-for-byte
references, rather than adding their features to the general bank. An exact
image gets its assigned name; a resized or re-encoded image still uses regular
recognition. If identical files have conflicting names, they are excluded from
the exact index and a warning is logged.

You can place a bulk archive of per-Pokémon image folders anywhere under `pokemon_images/` (for example `pokemon_images/archive/`). The builder searches recursively, merges duplicate folders, skips ambiguous composite images, and recognizes species, known forms, regional forms and event-costume names. Raw archive images are git-ignored; only upload the generated bank.
Gender-coded folders such as `nidoran-f` and `nidoran-m` retain their separate
Nidoran labels; mixed Nidoran composites are skipped as ambiguous.

Hand-added special forms can use a folder named for the form, such as
`pokemon_images/Gliding Build Koraidon/image.png`. Add its form-to-species entry
to `CUSTOM_FORM_SPECIES` in `image_match.py` when catch commands should use the
base species. A matching alphanumeric filename in `assets/thumbnails/` supplies
the catch-card and normal-starboard artwork. This also supports themed variants
such as Enchanted Applin and Cauldron Reuniclus: the form name is shown while
catch commands and reservations use the base species. The vision fallback is
also given these custom labels and base species, and only returns a custom
label when the visible image supports it.

Build the feature file after adding images:

```
python build_image_bank.py
```

This writes `image_bank.npz`. Only the changed Pokémon are recomputed on later runs (cached in `.bank_cache/`). The bot loads `image_bank.npz` next to `bot.py` at startup, or the path configured by `IMAGE_BANK_FILE`; it logs the exact loaded path. The pictures themselves don't need to be on the host. Upload `image_bank.npz`, `image_match.py` and `bot.py`, then restart.

Reference-image matching checks both the original and horizontally flipped
spawn image, so Pokémon can be recognized facing either direction without
adding flipped copies to the image bank. If the usual passes do not find a
match, smaller images are also retried at a larger size with the same vote
requirements. This can recover details lost when an image is downscaled.

When the reference matcher finds a clear winner, the bot names it without
calling OpenAI and reports 100.00%. This is a match indicator, not a measured
probability of correctness. A Pokémon being in the bank does not guarantee
every image of it will match: backgrounds, image size, other Pokémon with
similar features, or limited reference features can make the result unclear.
This needs `numpy` and `opencv-python-headless` (in `requirements.txt`).

`OPENAI_API_KEY` is optional. When no clear local match is found, the bot uses
OpenAI if configured; otherwise it considers its best local guess.
Unconfirmed local guesses are capped below 50%. The bot posts the best
available name even below 50%, and also reports it to the configured error
channel. These guesses can be wrong. If neither recognizer can produce a
name, the bot alerts the error channel instead.
Add correctly labelled spawn images to improve future matches.

## Music Activity

The profile **Music** picker launches a Discord Activity that loops
`activity/return_to_me.wav` and keeps playing while the member browses other
channels. If the Activity can't launch, the member gets the song by DM instead.

Set `MUSIC_ACTIVITY_PORT` to the port your host forwards to a public HTTPS
address; the bot then serves the Activity page from `activity/` on that port.
In the Discord Developer Portal, open the application, enable **Activities**,
and add a URL mapping with root `/` pointing at that HTTPS address (without
`https://`). Leave `MUSIC_ACTIVITY_PORT` unset to disable it.

## PostgreSQL storage (shiny hunts and collections)

Set `DATABASE_URL` to store shiny hunts and user collections in PostgreSQL
(tables `shiny_hunts` and `collections`, created automatically). Without it the
bot keeps using `shinyhunts.json` / `collections.json`. Existing JSON data is
imported once on first start.

```bash
export DATABASE_URL="postgresql://vivillon:vivillon_dev@localhost:5432/vivillon"
```

On hosts like bot-hosting.net or heavencloud.in you cannot run your own
PostgreSQL server, so use a free hosted one (Neon, Supabase, Aiven) and set its
connection string as `DATABASE_URL` in the host's environment/`.env`.

Back up / restore (works from JSON files or from Postgres):

```bash
python pg_backup.py backup backups/today
DATABASE_URL=... python pg_backup.py restore backups/today
```

## Data folder

All JSON files (static catalogs and saved settings) live in `data/`. Set
`DATA_DIR` to use a different folder; the per-file environment variables such as
`SHINYHUNTS_FILE` still override individual paths. Any file name in this README
without a folder (e.g. `reserves.json`) means `data/<name>`.
