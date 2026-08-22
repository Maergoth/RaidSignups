# Reverb Raid Sign-up Helper

Reverb Raid is a Red-DiscordBot cog for planning EverQuest II raids directly in Discord. An organizer runs `/create`, completes a private DM wizard, and the bot posts a persistent signup panel modeled after the practical parts of Raid-Helper.

It was built and tested specifically for **Red 3.5.24**, **discord.py 2.7.1**, and **Python 3.11**.

## What it does

- Private, five-step DM creation wizard through `/create` or `/raid create`
- Native Discord configuration dashboard through `/raid setup`
- Skippable setup and feature walkthrough through `/raid gettingstarted`
- All 26 EQ2 classes grouped into Fighter, Priest, Mage, and Scout
- Attending, tentative, late, bench, absent, and withdraw responses
- Optional signup notes such as “30 minutes late”
- Live roster embed with Discord-localized timestamps
- Persistent buttons and dropdowns that resume after a Red restart
- Organizer roles plus automatic access for users with Manage Server
- Bundled authentic icons for all 26 classes and all four archetypes
- One-click application-emoji sync that does not consume server emoji slots
- Configurable archetype button icons with Unicode fallbacks
- Configurable, restart-safe reminders that ping attending, tentative, and late signups
- Close/reopen signups, edit events, archive events, and export CSV rosters
- Organizer-only raid history with server-wide and per-member CSV exports
- Both slash commands and traditional Red prefix commands
- Red-compatible end-user data export and deletion hooks
- No external API keys, database, website, or background web service

## Install from the cog repository

Run these commands in Discord as the Red bot owner. Replace `[p]` with your bot's prefix.

```text
[p]repo add reverb-raid https://github.com/Maergoth/RaidSignups
[p]cog install reverb-raid reverbraid
[p]load reverbraid
```

Enable and sync the slash commands:

```text
[p]slash enablecog reverbraid
[p]slash sync
```

Discord can take a few minutes to show globally synced commands. For immediate testing in one server, pass that server to Red's optional `[guild]` argument for `[p]slash sync`.

Then run:

```text
/raid setup
```

Choose a default raid channel and organizer roles, confirm the timezone, and set the default duration and description. You can now run `/create`.

As the Red bot owner, click **Sync EQ2 icons** in `/raid setup` once. The cog uploads its
30 bundled PNGs as application emojis and immediately refreshes active raid messages. The
same icon pack works across every server using the bot and does not consume guild emoji slots.

## Install from a downloaded folder or ZIP

Extract the project somewhere outside Red's core and data folders. The path supplied to `addpath` must be the folder that directly contains the `reverbraid` package.

Windows example:

```text
[p]addpath C:\Red-Cogs\reverb-raid-signup-helper
[p]load reverbraid
[p]slash enablecog reverbraid
[p]slash sync
```

This follows Red's standard local cog layout:

```text
reverb-raid-signup-helper/
├── info.json
└── reverbraid/
    ├── __init__.py
    ├── info.json
    ├── constants.py
    ├── assets/icons/ (30 bundled EQ2 icons)
    ├── models.py
    ├── reverbraid.py
    ├── views.py
    └── wizard.py
```

## Initial Discord permissions

The bot needs these permissions in the raid channel:

- View Channel
- Send Messages
- Embed Links
- Read Message History
- Attach Files (only needed for CSV export)

Members also need permission to use application commands. The bot does **not** need Administrator or Manage Events. Organizers must allow DMs from the server while using the creation wizard.

## Commands

Every slash command also works as a traditional text command. For example, `/raid list` becomes `[p]raid list`.

| Command | Who can use it | Purpose |
| --- | --- | --- |
| `/create` | Organizer | Start the private raid creation wizard |
| `/raid create` | Organizer | Alternate grouped form of `/create` |
| `/raid setup` | Manage Server | Open the Discord configuration dashboard |
| `/raid gettingstarted` | Manage Server | Open the skippable setup and feature walkthrough |
| `/raid syncicons` | Red bot owner | Install or repair all 30 bundled EQ2 application emojis |
| `/raid list` | Everyone | List upcoming, non-archived raids |
| `/raid history [member]` | Organizer | Browse completed/archived raids, optionally for one member |
| `/raid exporthistory [member]` | Organizer | Export all retained historic signups as CSV |
| `/raid show event_id` | Everyone | Show a current roster by event ID |
| `/raid manage event_id` | Event creator or organizer | Open edit, close, export, and archive controls |
| `/raid eventreminder event_id lead_time` | Event creator or organizer | Override one raid's reminder, such as `2h` or `off` |
| `/raid timezone timezone_name` | Manage Server | Set the IANA timezone |
| `/raid channel channel` | Manage Server | Set the default raid channel |
| `/raid duration duration` | Manage Server | Set the default duration |
| `/raid reminder lead_time` | Manage Server | Set the reminder inherited by new raids, such as `1h` or `off` |
| `/raid description description` | Manage Server | Set the default description |
| `/raid organizerrole add\|remove role` | Manage Server | Add or remove an organizer role |
| `/raid mentionrole [role]` | Manage Server | Set or clear the new-raid announcement role |

An **organizer** is any user who has Manage Server, is the Red bot owner, or holds one of the roles selected in `/raid setup`. The creator of an event can always manage that event.

### Getting started walkthrough

Run `/raid gettingstarted`, or open `/raid setup` and select **Getting started**. The guide
walks through the raid channel, organizer and announcement roles, creation defaults, EQ2 icon
pack, and the complete creation/signup/management flow. Every configuration page has
**Skip / Next**; skipped settings are left unchanged. **Full setup** opens the complete dashboard
at any point.

## Signup behavior

The posted message has one button per EQ2 archetype:

- Fighter: Guardian, Berserker, Paladin, Shadowknight, Monk, Bruiser
- Priest: Templar, Inquisitor, Warden, Fury, Mystic, Defiler, Channeler
- Mage: Wizard, Warlock, Illusionist, Coercer, Conjuror, Necromancer
- Scout: Brigand, Swashbuckler, Troubador, Dirge, Ranger, Assassin, Beastlord

Choosing a class signs the user up as attending. **Status…** changes that response to tentative,
late, bench, or absent, or withdraws it entirely. Bench members appear in their own section so
organizers can contact them if needed without counting them in the active class roster. A user
can select Bench or Absent with or without a class. Class and availability are independent, so
the member keeps the selected status regardless of which choice they make first.

### Bundled EQ2 artwork

Discord buttons and dropdowns cannot display ordinary local PNG files directly. Reverb Raid
therefore includes all 30 supplied EQ2 icons and installs them as bot-owned application emojis.
Run `/raid syncicons`, or use `/raid setup` → **Sync EQ2 icons**, once as the Red bot owner.

The four archetype icons appear on signup buttons and roster headings. Each of the 26 class
icons appears in its class dropdown and beside that class in the live roster. Existing active
raid messages are refreshed after a sync. If Discord's application-emoji service is unavailable,
the cog retains safe Unicode archetype fallbacks. Server-specific archetype overrides remain
available through `/raid setup` → **Button icons**.

## Time handling

The server timezone defaults to `America/New_York` and can be changed to any IANA timezone in `/raid setup`. Creation accepts forms such as:

```text
2026-08-28 8:00 PM
Friday 8 PM
tomorrow 20:00
2026-08-28 20:00 -04:00
```

Times are stored in UTC and displayed with Discord timestamps, so each member sees the raid in their own local timezone. Ambiguous and nonexistent daylight-saving times are rejected with a useful correction prompt.

## Reminders

New servers default to one reminder **1 hour before raid start**. Change it with `/raid setup`
→ **Reminder** or `/raid reminder 2h`; use `off` to disable it. The value is copied onto each
new raid, so changing the server default does not silently alter raids that are already posted.
Use the **Reminder** button in `/raid manage` or `/raid eventreminder` to override one event.

The bot checks persisted events once per minute. This survives restarts and records which raid
start time was reminded, preventing duplicate reminders. Moving a raid to a new start time safely
resets its reminder. The reminder is posted in the raid channel and pings Attending, Tentative,
and Late signups. Bench and Absent entries are deliberately not pinged. Existing raids created
before version 1.3.0 start with reminders off until an organizer explicitly enables one.

## Raid history and CSV exports

Completed and archived raids remain available to organizers through `/raid history`. Supply a
member to see that person's retained class and status history. `/raid exporthistory` downloads a
UTF-8 CSV containing every retained historic signup; supplying a member exports only that member.
The export includes event metadata, UTC start time, Discord user ID, display name, class,
archetype, status, note, and signup update time. Individual event exports remain available from
`/raid manage event_id`.

## Persistence, privacy, and backups

Raid settings and rosters use Red's `Config` storage for the guild. Buttons use stable custom IDs and are re-registered during `cog_load`, so active raid messages continue working after restarts and cog reloads.

The cog stores only data needed for the roster: Discord user ID, display name, class, status, optional note, and the event creator ID. It implements Red's `red_get_data_for_user` and `red_delete_data_for_user` hooks. Archiving disables the message controls but deliberately retains the roster for organizer-only history and CSV export.

Back up this cog the same way you back up the rest of the Red instance data. Do not copy or commit Red's `config.json`, bot token, or complete data directory into this repository.

## Development and verification

Run the domain tests without starting Discord:

```bash
python -m unittest discover -s tests -v
python -m compileall -q reverbraid
```

The GitHub Actions workflow repeats these checks after installing Red 3.5.24 on Python 3.11 and performs a full cog import.

## License

MIT
