"""Reverb Raid Sign-up Helper cog for Red-DiscordBot."""

from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
import logging
import secrets
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from dateutil import tz
from discord.ext import tasks
from redbot.core import Config, app_commands, commands
from redbot.core.bot import Red

from .constants import (
    ARCHETYPE_APPLICATION_EMOJI_NAMES,
    ARCHETYPE_EMOJIS,
    ARCHETYPE_ICON_FILES,
    ARCHETYPE_LABELS,
    CLASS_APPLICATION_EMOJI_NAMES,
    CLASS_ICON_FILES,
    CLASS_TO_ARCHETYPE,
    CONFIG_IDENTIFIER,
    DEFAULT_GUILD,
    EMBED_COLOR,
    MAX_DESCRIPTION_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_TITLE_LENGTH,
    STATUS_EMOJIS,
    STATUS_LABELS,
)
from .models import (
    RaidInputError,
    chunk_lines,
    format_minutes,
    get_timezone,
    group_roster,
    normalize_signup,
    parse_duration,
    parse_reminder_minutes,
    reminder_recipient_ids,
    select_historic_events,
    trim_text,
)
from .views import ConfigDashboardView, GettingStartedView, ManageEventView, RaidSignupView
from .wizard import RaidCreationWizard, RaidDraft, WizardCancelled

log = logging.getLogger("red.Maergoth.ReverbRaid")


class ReverbRaid(commands.Cog):
    """Plan EQ2 raids with private creation prompts and persistent signup panels."""

    __author__ = "Maergoth"
    __version__ = "1.3.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=CONFIG_IDENTIFIER,
            force_registration=True,
        )
        self.config.register_guild(**copy.deepcopy(DEFAULT_GUILD))
        self._event_locks: Dict[tuple[int, str], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._active_wizards: set[tuple[int, int]] = set()
        self._persistent_views: Dict[tuple[int, str], RaidSignupView] = {}
        self._archetype_icon_emojis: Dict[str, str] = {}
        self._class_icon_emojis: Dict[str, str] = {}

    async def cog_load(self) -> None:
        """Restore persistent button callbacks after a bot restart or cog reload."""
        await self.load_application_icon_cache()
        all_guilds = await self.config.all_guilds()
        for raw_guild_id, settings in all_guilds.items():
            guild_id = int(raw_guild_id)
            guild = self.bot.get_guild(guild_id)
            # Existing events predate reminders. Leave them disabled so installing an
            # update cannot unexpectedly ping an old roster; organizers can enable a
            # reminder for any active event from its management panel.
            async with self.config.guild_from_id(guild_id).events() as events:
                for event in events.values():
                    event.setdefault("reminder_minutes", 0)
                    event.setdefault("reminder_sent_for_start_ts", None)
                restored_events = copy.deepcopy(events)
            for event_id, event in restored_events.items():
                if event.get("archived"):
                    continue
                view = RaidSignupView(
                    self,
                    event_id,
                    closed=bool(event.get("closed")),
                    emoji_map=self.resolve_archetype_emoji_map(
                        guild, settings.get("archetype_emojis", {})
                    ),
                    class_emoji_map=self.class_emoji_map,
                )
                self.bot.add_view(view, message_id=event.get("message_id"))
                self._persistent_views[(guild_id, event_id)] = view
        if not self.reminder_dispatch.is_running():
            self.reminder_dispatch.start()

    def cog_unload(self) -> None:
        if self.reminder_dispatch.is_running():
            self.reminder_dispatch.cancel()
        for view in self._persistent_views.values():
            view.stop()
        self._persistent_views.clear()

    # ---------------------------------------------------------------------
    # Configuration and authorization
    # ---------------------------------------------------------------------

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        return await self.config.guild_from_id(guild_id).all()

    async def get_guild_timezone(self, guild_id: int) -> str:
        return await self.config.guild_from_id(guild_id).timezone()

    async def set_guild_setting(self, guild_id: int, key: str, value: Any) -> None:
        allowed = {
            "timezone",
            "default_channel_id",
            "default_description",
            "default_duration_minutes",
            "default_reminder_minutes",
            "organizer_role_ids",
            "mention_role_id",
            "archetype_emojis",
        }
        if key not in allowed:
            raise ValueError(f"Unsupported Reverb Raid setting: {key}")
        await self.config.guild_from_id(guild_id).set_raw(key, value=value)

    async def is_organizer(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        if await self.bot.is_owner(member):
            return True
        role_ids = set(await self.config.guild(member.guild).organizer_role_ids())
        return any(role.id in role_ids for role in member.roles)

    async def require_organizer(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.author, discord.Member) or not await self.is_organizer(ctx.author):
            raise commands.UserFeedbackCheckFailure(
                "You need **Manage Server** or a configured raid organizer role to do that."
            )

    async def can_manage_event(
        self,
        member: discord.abc.User,
        guild_id: Optional[int],
        event_id: str,
    ) -> bool:
        if guild_id is None:
            return False
        event = await self.get_event(guild_id, event_id)
        if event is None:
            return False
        if member.id == event.get("creator_id"):
            return True
        return isinstance(member, discord.Member) and await self.is_organizer(member)

    async def build_config_embed(self, guild_id: int) -> discord.Embed:
        settings = await self.get_guild_settings(guild_id)
        guild = self.bot.get_guild(guild_id)
        channel_id = settings.get("default_channel_id")
        role_ids = settings.get("organizer_role_ids", [])
        channel_value = f"<#{channel_id}>" if channel_id else "*Use the command channel*"
        roles_value = ", ".join(f"<@&{role_id}>" for role_id in role_ids) or "*Manage Server only*"
        mention_role_id = settings.get("mention_role_id")
        mention_value = f"<@&{mention_role_id}>" if mention_role_id else "*No automatic mention*"
        emoji_map = self.resolve_archetype_emoji_map(
            guild, settings.get("archetype_emojis", {})
        )
        emoji_value = "  ".join(
            f"{emoji_map.get(key, ARCHETYPE_EMOJIS[key])} {ARCHETYPE_LABELS[key]}"
            for key in ("fighter", "priest", "mage", "scout")
        )
        embed = discord.Embed(
            title="⚙️ Reverb Raid configuration",
            description=(
                "Use the controls below to configure the creation wizard. Changes are saved "
                "for this server immediately."
            ),
            color=EMBED_COLOR,
        )
        embed.add_field(name="Timezone", value=f"`{settings['timezone']}`", inline=True)
        embed.add_field(name="Default channel", value=channel_value, inline=True)
        embed.add_field(
            name="Default duration",
            value=f"{settings['default_duration_minutes']} minutes",
            inline=True,
        )
        embed.add_field(
            name="Raid reminder",
            value=(
                f"{format_minutes(settings['default_reminder_minutes'])} before start"
                if settings["default_reminder_minutes"]
                else "*Disabled*"
            ),
            inline=True,
        )
        embed.add_field(name="Organizer roles", value=roles_value, inline=False)
        embed.add_field(name="Announcement role", value=mention_value, inline=False)
        embed.add_field(name="Button icons", value=emoji_value, inline=False)
        icon_count = len(self._archetype_icon_emojis) + len(self._class_icon_emojis)
        icon_state = (
            f"**{icon_count}/30 ready** — authentic icons appear on archetype buttons, "
            "class choices, and roster entries."
            if icon_count
            else "*Not installed yet.* The Red bot owner can use **Sync EQ2 icons** below."
        )
        embed.add_field(name="EQ2 icon pack", value=icon_state, inline=False)
        embed.add_field(
            name="Default description",
            value=trim_text(settings["default_description"], 900) or "*None*",
            inline=False,
        )
        embed.set_footer(text="Administrators always retain access.")
        return embed

    @property
    def class_emoji_map(self) -> dict:
        return dict(self._class_icon_emojis)

    def resolve_archetype_emoji_map(
        self, guild: Optional[discord.Guild], configured: dict
    ) -> dict:
        """Merge the bundled icon pack with valid per-guild overrides."""
        resolved = {
            archetype: self._archetype_icon_emojis.get(
                archetype, ARCHETYPE_EMOJIS[archetype]
            )
            for archetype in ARCHETYPE_LABELS
        }
        for archetype, value in configured.items():
            if archetype not in ARCHETYPE_LABELS or not value:
                continue
            emoji = discord.PartialEmoji.from_str(str(value))
            if emoji.id is not None and (
                guild is None
                or (
                    guild.get_emoji(emoji.id) is None
                    and emoji.id not in self._application_emoji_ids
                )
            ):
                continue
            resolved[archetype] = str(value)
        return resolved

    @property
    def _application_emoji_ids(self) -> set[int]:
        values = (*self._archetype_icon_emojis.values(), *self._class_icon_emojis.values())
        return {
            emoji.id
            for value in values
            if (emoji := discord.PartialEmoji.from_str(value)).id is not None
        }

    def is_application_emoji_id(self, emoji_id: int) -> bool:
        return emoji_id in self._application_emoji_ids

    @staticmethod
    def _icon_asset_path(filename: str) -> Path:
        return Path(__file__).with_name("assets") / "icons" / filename

    async def load_application_icon_cache(self) -> None:
        """Discover already-installed Reverb Raid application emojis."""
        self._archetype_icon_emojis.clear()
        self._class_icon_emojis.clear()
        fetcher = getattr(self.bot, "fetch_application_emojis", None)
        if fetcher is None:
            log.warning("discord.py does not expose application emoji support")
            return
        try:
            emojis = await fetcher()
        except (discord.HTTPException, discord.MissingApplicationID):
            log.exception("Could not load Reverb Raid application emojis")
            return
        by_name = {emoji.name: str(emoji) for emoji in emojis}
        self._archetype_icon_emojis.update(
            {
                key: by_name[name]
                for key, name in ARCHETYPE_APPLICATION_EMOJI_NAMES.items()
                if name in by_name
            }
        )
        self._class_icon_emojis.update(
            {
                key: by_name[name]
                for key, name in CLASS_APPLICATION_EMOJI_NAMES.items()
                if name in by_name
            }
        )

    async def sync_application_icons(self) -> tuple[int, int, int]:
        """Create missing bundled application emojis and refresh active raids."""
        fetcher = getattr(self.bot, "fetch_application_emojis", None)
        creator = getattr(self.bot, "create_application_emoji", None)
        if fetcher is None or creator is None:
            raise RaidInputError(
                "This Red installation does not support application emojis. "
                "Reverb Raid requires discord.py 2.5 or newer for the bundled icon pack."
            )
        try:
            existing = await fetcher()
        except (discord.HTTPException, discord.MissingApplicationID) as exc:
            raise RaidInputError(f"Discord would not list the bot's application emojis: {exc}") from exc
        by_name = {emoji.name: emoji for emoji in existing}
        created = 0
        reused = 0

        definitions = [
            ("archetype", key, ARCHETYPE_APPLICATION_EMOJI_NAMES[key], filename)
            for key, filename in ARCHETYPE_ICON_FILES.items()
        ]
        definitions.extend(
            ("class", key, CLASS_APPLICATION_EMOJI_NAMES[key], filename)
            for key, filename in CLASS_ICON_FILES.items()
        )
        resolved_archetypes: Dict[str, str] = {}
        resolved_classes: Dict[str, str] = {}
        for kind, key, emoji_name, filename in definitions:
            emoji = by_name.get(emoji_name)
            if emoji is None:
                asset_path = self._icon_asset_path(filename)
                if not asset_path.is_file():
                    raise RaidInputError(f"The bundled icon `{filename}` is missing from the cog.")
                try:
                    emoji = await creator(name=emoji_name, image=asset_path.read_bytes())
                except discord.HTTPException as exc:
                    # Keep any successfully-created icons discoverable on the next attempt.
                    await self.load_application_icon_cache()
                    raise RaidInputError(
                        f"Discord stopped the icon sync after {created} new icon(s): {exc}"
                    ) from exc
                by_name[emoji_name] = emoji
                created += 1
            else:
                reused += 1
            target = resolved_archetypes if kind == "archetype" else resolved_classes
            target[key] = str(emoji)

        self._archetype_icon_emojis = resolved_archetypes
        self._class_icon_emojis = resolved_classes
        refreshed = await self.refresh_all_active_events()
        return created, reused, refreshed

    async def refresh_all_active_events(self) -> int:
        refreshed = 0
        for raw_guild_id, settings in (await self.config.all_guilds()).items():
            guild_id = int(raw_guild_id)
            for event_id, event in settings.get("events", {}).items():
                if event.get("archived") or not event.get("message_id"):
                    continue
                await self.refresh_event_message(guild_id, event_id)
                refreshed += 1
        return refreshed

    # ---------------------------------------------------------------------
    # Event persistence and rendering
    # ---------------------------------------------------------------------

    async def get_event(self, guild_id: Optional[int], event_id: str) -> Optional[dict]:
        if guild_id is None:
            return None
        events = await self.config.guild_from_id(guild_id).events()
        event = events.get(event_id)
        return copy.deepcopy(event) if event is not None else None

    async def _store_event(self, guild_id: int, event_id: str, event: dict) -> None:
        async with self.config.guild_from_id(guild_id).events() as events:
            events[event_id] = event

    async def create_event(
        self,
        guild: discord.Guild,
        creator: discord.Member,
        draft: RaidDraft,
    ) -> tuple[str, discord.Message]:
        channel = guild.get_channel(draft.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise RaidInputError("The selected raid channel no longer exists.")
        me = guild.me
        if me is None:
            raise RaidInputError("I could not resolve my server permissions.")
        permissions = channel.permissions_for(me)
        required = permissions.view_channel and permissions.send_messages and permissions.embed_links
        if not required:
            raise RaidInputError(
                f"I need **View Channel**, **Send Messages**, and **Embed Links** in {channel.mention}."
            )

        settings = await self.config.guild(guild).all()
        event_id = secrets.token_hex(6)
        event = {
            "id": event_id,
            "guild_id": guild.id,
            "title": trim_text(draft.title, MAX_TITLE_LENGTH),
            "description": trim_text(draft.description, MAX_DESCRIPTION_LENGTH),
            "start_ts": draft.start_ts,
            "duration_minutes": draft.duration_minutes,
            "channel_id": channel.id,
            "message_id": None,
            "creator_id": creator.id,
            "created_ts": int(datetime.now(timezone.utc).timestamp()),
            "closed": False,
            "archived": False,
            "reminder_minutes": int(settings.get("default_reminder_minutes", 60)),
            "reminder_sent_for_start_ts": None,
            "roster": {},
        }
        await self._store_event(guild.id, event_id, event)
        view = RaidSignupView(
            self,
            event_id,
            emoji_map=self.resolve_archetype_emoji_map(
                guild, settings.get("archetype_emojis", {})
            ),
            class_emoji_map=self.class_emoji_map,
        )
        mention_role_id = settings.get("mention_role_id")
        content = f"<@&{mention_role_id}>" if mention_role_id else None
        try:
            message = await channel.send(
                content=content,
                embed=await self.build_event_embed(guild, event),
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=bool(mention_role_id),
                ),
            )
        except discord.HTTPException as exc:
            async with self.config.guild(guild).events() as events:
                events.pop(event_id, None)
            raise RaidInputError(f"Discord would not let me post the raid: {exc}") from exc

        async with self.config.guild(guild).events() as events:
            events[event_id]["message_id"] = message.id
        self._persistent_views[(guild.id, event_id)] = view
        return event_id, message

    async def build_event_embed(self, guild: discord.Guild, event: dict) -> discord.Embed:
        roster = event.get("roster", {})
        emoji_map = self.resolve_archetype_emoji_map(
            guild, await self.config.guild(guild).archetype_emojis()
        )
        grouped, bench, absent = group_roster(roster)
        counts = defaultdict(int)
        for raw in roster.values():
            counts[normalize_signup(raw)["status"]] += 1

        description = event.get("description") or "*No description provided.*"
        embed = discord.Embed(
            title=f"⚔️ {event.get('title', 'Raid')}",
            description=trim_text(description, MAX_DESCRIPTION_LENGTH),
            color=0x555555 if event.get("closed") else EMBED_COLOR,
            timestamp=datetime.fromtimestamp(event["start_ts"], timezone.utc),
        )
        start_ts = int(event["start_ts"])
        end_ts = start_ts + int(event.get("duration_minutes", 180)) * 60
        creator_id = event.get("creator_id")
        leader = f"<@{creator_id}>" if creator_id else "Former member"
        embed.add_field(name="Raid lead", value=leader, inline=True)
        embed.add_field(
            name="Date and time",
            value=f"<t:{start_ts}:F>\n<t:{start_ts}:R>",
            inline=True,
        )
        embed.add_field(name="Expected end", value=f"<t:{end_ts}:t>", inline=True)
        reminder_minutes = int(event.get("reminder_minutes") or 0)
        reminder_value = (
            f"{format_minutes(reminder_minutes)} before start"
            if reminder_minutes
            else "Off"
        )
        if event.get("reminder_sent_for_start_ts") == start_ts:
            reminder_value += " • sent"
        embed.add_field(name="Reminder", value=reminder_value, inline=True)

        field_count = 4
        used_characters = sum(
            len(field.name) + len(field.value) for field in embed.fields
        ) + len(embed.title or "") + len(embed.description or "")
        roster_budget = max(0, 5500 - used_characters)

        def add_roster_field(name: str, value: str, *, inline: bool) -> bool:
            nonlocal field_count, roster_budget
            if field_count >= 24 or roster_budget <= len(name) + 1:
                return False
            value = trim_text(value, min(1024, roster_budget - len(name)))
            if not value:
                return False
            embed.add_field(name=name, value=value, inline=inline)
            field_count += 1
            roster_budget -= len(name) + len(value)
            return True

        for archetype in ("fighter", "priest", "mage", "scout"):
            entries = grouped.get(archetype, [])
            lines = [self._format_signup_line(user_id, signup) for user_id, signup in entries]
            chunks = chunk_lines(lines)
            for index, chunk in enumerate(chunks):
                suffix = f" ({len(entries)})" if index == 0 else " (continued)"
                if not add_roster_field(
                    f"{emoji_map.get(archetype, ARCHETYPE_EMOJIS[archetype])} "
                    f"{ARCHETYPE_LABELS[archetype]}{suffix}",
                    chunk,
                    inline=True,
                ):
                    break

        unassigned = grouped.get("unassigned", [])
        if unassigned:
            lines = [self._format_signup_line(user_id, signup) for user_id, signup in unassigned]
            add_roster_field(
                f"📋 Class not selected ({len(unassigned)})",
                chunk_lines(lines)[0],
                inline=False,
            )
        if bench:
            lines = [self._format_signup_line(user_id, signup) for user_id, signup in bench]
            for index, chunk in enumerate(chunk_lines(lines)):
                name = f"🪑 Bench ({len(bench)})" if index == 0 else "Bench (continued)"
                if not add_roster_field(name, chunk, inline=False):
                    break
        if absent:
            lines = [self._format_signup_line(user_id, signup) for user_id, signup in absent]
            for index, chunk in enumerate(chunk_lines(lines)):
                name = f"🚫 Absent ({len(absent)})" if index == 0 else "Absent (continued)"
                if not add_roster_field(name, chunk, inline=False):
                    break

        status_summary = "  ".join(
            f"{STATUS_EMOJIS[status]} {counts[status]} {label.lower()}"
            for status, label in STATUS_LABELS.items()
            if counts[status]
        ) or "No responses yet"
        state = "Signups closed" if event.get("closed") else "Choose a class below to sign up"
        embed.set_footer(text=f"{state}  •  {status_summary}  •  Event ID: {event['id']}")
        return embed

    def _format_signup_line(self, user_id: str, signup: dict) -> str:
        class_name = signup.get("class_name") or "Unassigned"
        status = signup.get("status", "attending")
        note = trim_text(str(signup.get("note") or ""), MAX_NOTE_LENGTH)
        note_suffix = f" — *{note}*" if note else ""
        class_icon = self._class_icon_emojis.get(class_name)
        icon_prefix = f"{class_icon} " if class_icon else ""
        return (
            f"{STATUS_EMOJIS.get(status, '•')} {icon_prefix}**{class_name}** — "
            f"<@{user_id}>{note_suffix}"
        )

    async def refresh_event_message(self, guild_id: int, event_id: str) -> None:
        async with self._event_locks[(guild_id, event_id)]:
            event = await self.get_event(guild_id, event_id)
            guild = self.bot.get_guild(guild_id)
            if event is None or guild is None or event.get("message_id") is None:
                return
            channel = guild.get_channel(event.get("channel_id"))
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return
            view = None
            if not event.get("archived"):
                emoji_map = await self.config.guild_from_id(guild_id).archetype_emojis()
                view = RaidSignupView(
                    self,
                    event_id,
                    closed=bool(event.get("closed")),
                    emoji_map=self.resolve_archetype_emoji_map(guild, emoji_map),
                    class_emoji_map=self.class_emoji_map,
                )
            key = (guild_id, event_id)
            old_view = self._persistent_views.pop(key, None)
            if old_view is not None:
                # Stop the old dispatcher before discord.py registers the replacement.
                # Stopping it afterward would remove callbacks with the same custom IDs.
                old_view.stop()
            try:
                message = await channel.fetch_message(event["message_id"])
                await message.edit(
                    embed=await self.build_event_embed(guild, event),
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                if view is not None:
                    self._persistent_views[key] = view
            except (discord.NotFound, discord.Forbidden):
                log.warning("Could not refresh raid message %s in guild %s", event_id, guild_id)
            except discord.HTTPException:
                log.exception("Discord error while refreshing raid %s", event_id)
                if view is not None:
                    # Preserve working callbacks even when only the visual edit failed.
                    self.bot.add_view(view, message_id=event["message_id"])
                    self._persistent_views[key] = view

    # ---------------------------------------------------------------------
    # Restart-safe raid reminders
    # ---------------------------------------------------------------------

    def _build_reminder_content(self, guild: discord.Guild, event: dict) -> tuple[str, list]:
        start_ts = int(event["start_ts"])
        title = discord.utils.escape_markdown(str(event.get("title") or "Raid"))
        message_id = event.get("message_id")
        channel_id = event.get("channel_id")
        link = (
            f"https://discord.com/channels/{guild.id}/{channel_id}/{message_id}"
            if channel_id and message_id
            else None
        )
        first_line = f"⏰ **{title}** starts <t:{start_ts}:R> — <t:{start_ts}:F>."
        if link:
            first_line += f" [Open the signup]({link})"

        recipient_ids = reminder_recipient_ids(event.get("roster", {}))

        # Keep the post comfortably below Discord's content limit. A normal EQ2
        # raid fits easily, while this also protects unusually large rosters.
        selected_ids = []
        content = first_line
        for user_id in recipient_ids:
            mention = f"<@{user_id}>"
            candidate = f"{content}\n{mention}" if not selected_ids else f"{content} {mention}"
            if len(candidate) > 1850:
                break
            content = candidate
            selected_ids.append(user_id)
        omitted = len(recipient_ids) - len(selected_ids)
        if omitted:
            content += f"\n*{omitted} additional signup(s) could not be mentioned in one post.*"
        return content, [discord.Object(id=user_id) for user_id in selected_ids]

    async def _send_due_reminder(self, guild_id: int, event_id: str, now_ts: int) -> bool:
        async with self._event_locks[(guild_id, event_id)]:
            event = await self.get_event(guild_id, event_id)
            if event is None or event.get("archived"):
                return False
            start_ts = int(event.get("start_ts") or 0)
            reminder_minutes = int(event.get("reminder_minutes") or 0)
            if (
                reminder_minutes <= 0
                or start_ts <= now_ts
                or now_ts < start_ts - reminder_minutes * 60
                or event.get("reminder_sent_for_start_ts") == start_ts
            ):
                return False

            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(event.get("channel_id")) if guild else None
            if guild is None or not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return False

            content, recipients = self._build_reminder_content(guild, event)
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                    users=recipients,
                    replied_user=False,
                ),
            )
            async with self.config.guild_from_id(guild_id).events() as events:
                current = events.get(event_id)
                if current is not None and int(current.get("start_ts") or 0) == start_ts:
                    current["reminder_sent_for_start_ts"] = start_ts
            return True

    @tasks.loop(seconds=60)
    async def reminder_dispatch(self) -> None:
        """Find due reminders in Red Config and deliver each event exactly once."""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        for raw_guild_id, settings in (await self.config.all_guilds()).items():
            guild_id = int(raw_guild_id)
            for event_id in settings.get("events", {}):
                try:
                    await self._send_due_reminder(guild_id, event_id, now_ts)
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "Discord rejected the reminder for raid %s in guild %s",
                        event_id,
                        guild_id,
                    )
                except Exception:
                    log.exception(
                        "Unexpected reminder failure for raid %s in guild %s",
                        event_id,
                        guild_id,
                    )

    @reminder_dispatch.before_loop
    async def before_reminder_dispatch(self) -> None:
        await self.bot.wait_until_red_ready()

    # ---------------------------------------------------------------------
    # Signup mutations
    # ---------------------------------------------------------------------

    async def _mutate_signup(self, guild_id: int, event_id: str, member, mutator) -> dict:
        lock = self._event_locks[(guild_id, event_id)]
        async with lock:
            async with self.config.guild_from_id(guild_id).events() as events:
                event = events.get(event_id)
                if event is None or event.get("archived"):
                    raise RaidInputError("This raid no longer exists.")
                if event.get("closed"):
                    raise RaidInputError("Signups for this raid are closed.")
                roster = event.setdefault("roster", {})
                user_id = str(member.id)
                signup = normalize_signup(roster.get(user_id, {}))
                signup["display_name"] = getattr(member, "display_name", member.name)
                signup["updated_at"] = int(datetime.now(timezone.utc).timestamp())
                result = mutator(roster, user_id, signup)
                if result is not None:
                    roster[user_id] = result
        await self.refresh_event_message(guild_id, event_id)
        return signup

    async def set_signup_class(
        self, guild_id: int, event_id: str, member, class_name: str
    ) -> str:
        from .constants import CLASS_TO_ARCHETYPE

        archetype = CLASS_TO_ARCHETYPE.get(class_name)
        if archetype is None:
            raise RaidInputError("That is not a supported EverQuest II class.")

        def mutate(_roster, _user_id, signup):
            signup["class_name"] = class_name
            signup["archetype"] = archetype
            return signup

        await self._mutate_signup(guild_id, event_id, member, mutate)
        return f"You are signed up as **{class_name}**. Use **Status…** if needed."

    async def set_signup_status(
        self, guild_id: int, event_id: str, member, status: str
    ) -> str:
        if status != "withdraw" and status not in STATUS_LABELS:
            raise RaidInputError("That is not a valid signup status.")

        def mutate(roster, user_id, signup):
            if status == "withdraw":
                roster.pop(user_id, None)
                return None
            signup["status"] = status
            return signup

        await self._mutate_signup(guild_id, event_id, member, mutate)
        if status == "withdraw":
            return "Your signup was removed."
        return f"Your status is now **{STATUS_LABELS[status]}**."

    async def set_signup_note(
        self, guild_id: int, event_id: str, member, note: str
    ) -> str:
        note = trim_text(note, MAX_NOTE_LENGTH)

        def mutate(roster, user_id, signup):
            if user_id not in roster:
                raise RaidInputError("Choose a class or status before adding a note.")
            signup["note"] = note
            return signup

        await self._mutate_signup(guild_id, event_id, member, mutate)
        return "Your signup note was saved." if note else "Your signup note was cleared."

    # ---------------------------------------------------------------------
    # Organizer operations
    # ---------------------------------------------------------------------

    async def toggle_event_closed(self, guild_id: int, event_id: str, member) -> bool:
        if not await self.can_manage_event(member, guild_id, event_id):
            raise RaidInputError("You cannot manage this raid.")
        async with self._event_locks[(guild_id, event_id)]:
            async with self.config.guild_from_id(guild_id).events() as events:
                event = events.get(event_id)
                if event is None or event.get("archived"):
                    raise RaidInputError("This raid no longer exists.")
                event["closed"] = not bool(event.get("closed"))
                closed = event["closed"]
        await self.refresh_event_message(guild_id, event_id)
        return closed

    async def edit_event(self, guild_id: int, event_id: str, member, **changes) -> None:
        if not await self.can_manage_event(member, guild_id, event_id):
            raise RaidInputError("You cannot manage this raid.")
        async with self._event_locks[(guild_id, event_id)]:
            async with self.config.guild_from_id(guild_id).events() as events:
                event = events.get(event_id)
                if event is None or event.get("archived"):
                    raise RaidInputError("This raid no longer exists.")
                old_start_ts = int(event.get("start_ts") or 0)
                event.update(changes)
                if int(event.get("start_ts") or 0) != old_start_ts:
                    event["reminder_sent_for_start_ts"] = None
        await self.refresh_event_message(guild_id, event_id)

    async def set_event_reminder(
        self, guild_id: int, event_id: str, member, reminder_minutes: int
    ) -> None:
        if not await self.can_manage_event(member, guild_id, event_id):
            raise RaidInputError("You cannot manage this raid.")
        async with self._event_locks[(guild_id, event_id)]:
            async with self.config.guild_from_id(guild_id).events() as events:
                event = events.get(event_id)
                if event is None or event.get("archived"):
                    raise RaidInputError("This raid no longer exists.")
                event["reminder_minutes"] = int(reminder_minutes)
                event["reminder_sent_for_start_ts"] = None
        await self.refresh_event_message(guild_id, event_id)

    async def archive_event(self, guild_id: int, event_id: str, member) -> None:
        if not await self.can_manage_event(member, guild_id, event_id):
            raise RaidInputError("You cannot manage this raid.")
        async with self._event_locks[(guild_id, event_id)]:
            async with self.config.guild_from_id(guild_id).events() as events:
                event = events.get(event_id)
                if event is None:
                    raise RaidInputError("This raid no longer exists.")
                event["archived"] = True
                event["closed"] = True
        await self.refresh_event_message(guild_id, event_id)

    async def purge_event(self, guild_id: int, event_id: str, member) -> None:
        """Permanently remove event data while leaving a neutral Discord tombstone."""
        if not await self.can_manage_event(member, guild_id, event_id):
            raise RaidInputError("You cannot manage this raid.")
        event = await self.get_event(guild_id, event_id)
        if event is None:
            raise RaidInputError("This raid no longer exists.")
        async with self._event_locks[(guild_id, event_id)]:
            async with self.config.guild_from_id(guild_id).events() as events:
                events.pop(event_id, None)

        old_view = self._persistent_views.pop((guild_id, event_id), None)
        if old_view is not None:
            old_view.stop()

        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(event.get("channel_id")) if guild else None
        if isinstance(channel, (discord.TextChannel, discord.Thread)) and event.get("message_id"):
            try:
                message = await channel.fetch_message(event["message_id"])
                embed = discord.Embed(
                    title="Archived Reverb Raid",
                    description="This event and its stored roster were permanently deleted.",
                    color=0x555555,
                )
                await message.edit(embed=embed, view=None, allowed_mentions=discord.AllowedMentions.none())
            except (discord.NotFound, discord.Forbidden):
                pass
            except discord.HTTPException:
                log.exception("Discord error while replacing purged raid %s", event_id)

    async def send_manage_panel(self, interaction: discord.Interaction, event_id: str) -> None:
        event = await self.get_event(interaction.guild_id, event_id)
        if event is None:
            await interaction.response.send_message("This raid no longer exists.", ephemeral=True)
            return
        view = ManageEventView(
            self,
            event_id,
            interaction.user.id,
            bool(event.get("closed")),
        )
        await interaction.response.send_message(
            f"Manage **{event['title']}** (`{event_id}`):",
            view=view,
            ephemeral=True,
        )

    async def export_roster(self, guild_id: int, event_id: str) -> Optional[discord.File]:
        event = await self.get_event(guild_id, event_id)
        if event is None:
            return None
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Discord user ID", "Display name", "Class", "Archetype", "Status", "Note"])
        for user_id, raw in event.get("roster", {}).items():
            signup = normalize_signup(raw)
            writer.writerow(
                [
                    user_id,
                    self._csv_safe(signup["display_name"]),
                    signup["class_name"] or "",
                    signup["archetype"] or "",
                    signup["status"],
                    self._csv_safe(signup["note"]),
                ]
            )
        payload = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        return discord.File(payload, filename=f"reverb-raid-{event_id}-roster.csv")

    async def build_history_embed(
        self, guild: discord.Guild, member: Optional[discord.Member] = None
    ) -> discord.Embed:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        events = select_historic_events(
            await self.config.guild(guild).events(),
            now_ts,
            member_id=str(member.id) if member else None,
        )
        title = f"Raid history for {member.display_name}" if member else "Reverb Raid history"
        if not events:
            description = (
                "That member has no retained raid signup history."
                if member
                else "There are no completed or archived raids yet."
            )
            return discord.Embed(title=title, description=description, color=EMBED_COLOR)

        lines = []
        for event in events:
            event_title = discord.utils.escape_markdown(str(event.get("title") or "Raid"))
            message_id = event.get("message_id")
            channel_id = event.get("channel_id")
            link = (
                f"https://discord.com/channels/{guild.id}/{channel_id}/{message_id}"
                if channel_id and message_id
                else None
            )
            title_display = f"[{event_title}]({link})" if link else event_title
            state = "archived" if event.get("archived") else "completed"
            if member:
                signup = normalize_signup(event.get("roster", {}).get(str(member.id), {}))
                response = STATUS_LABELS[signup["status"]]
                class_name = signup["class_name"] or "No class"
                detail = f"**{class_name}** • {response}"
            else:
                count = len(event.get("roster", {}))
                detail = f"{count} response{'s' if count != 1 else ''}"
            line = (
                f"• {title_display} — <t:{int(event.get('start_ts') or 0)}:d> — "
                f"{detail} — `{state}` — `{event['id']}`"
            )
            if len("\n".join((*lines, line))) > 3900 or len(lines) >= 20:
                break
            lines.append(line)

        embed = discord.Embed(title=title, description="\n".join(lines), color=EMBED_COLOR)
        if len(events) > len(lines):
            embed.set_footer(
                text=f"Showing the newest {len(lines)} of {len(events)} entries • CSV export includes all"
            )
        else:
            embed.set_footer(text=f"{len(events)} retained historic raid(s)")
        return embed

    async def export_history(
        self, guild_id: int, member_id: Optional[int] = None
    ) -> discord.File:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        events = select_historic_events(
            await self.config.guild_from_id(guild_id).events(),
            now_ts,
            member_id=str(member_id) if member_id else None,
        )
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "Event ID",
                "Event title",
                "Start time (UTC)",
                "Start timestamp",
                "Duration minutes",
                "Archived",
                "Discord user ID",
                "Display name",
                "Class",
                "Archetype",
                "Status",
                "Note",
                "Signup updated (UTC)",
            ]
        )
        for event in events:
            start_ts = int(event.get("start_ts") or 0)
            start_utc = datetime.fromtimestamp(start_ts, timezone.utc).isoformat()
            roster = event.get("roster", {})
            rows = list(roster.items())
            if member_id is not None:
                raw = roster.get(str(member_id))
                rows = [(str(member_id), raw)] if raw is not None else []
            if not rows:
                rows = [("", None)]
            for user_id, raw in rows:
                signup = normalize_signup(raw or {}) if raw is not None else None
                updated_ts = signup["updated_at"] if signup else 0
                writer.writerow(
                    [
                        event["id"],
                        self._csv_safe(event.get("title", "Raid")),
                        start_utc,
                        start_ts,
                        int(event.get("duration_minutes") or 0),
                        bool(event.get("archived")),
                        user_id,
                        self._csv_safe(signup["display_name"]) if signup else "",
                        signup["class_name"] or "" if signup else "",
                        signup["archetype"] or "" if signup else "",
                        signup["status"] if signup else "",
                        self._csv_safe(signup["note"]) if signup else "",
                        (
                            datetime.fromtimestamp(updated_ts, timezone.utc).isoformat()
                            if updated_ts
                            else ""
                        ),
                    ]
                )
        payload = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        suffix = f"-member-{member_id}" if member_id else ""
        return discord.File(
            payload,
            filename=f"reverb-raid-history{suffix}-{datetime.now(timezone.utc):%Y%m%d}.csv",
        )

    @staticmethod
    def _csv_safe(value: str) -> str:
        """Prevent member-controlled CSV values from becoming spreadsheet formulas."""
        value = str(value)
        return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

    def format_local_time(self, timestamp: int, timezone_name: str) -> str:
        zone = tz.gettz(timezone_name) or timezone.utc
        value = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(zone)
        return value.strftime("%Y-%m-%d %I:%M %p")

    # ---------------------------------------------------------------------
    # Commands (hybrid commands work as slash and traditional text commands)
    # ---------------------------------------------------------------------

    async def _run_creation_wizard(self, ctx: commands.Context) -> None:
        await self.require_organizer(ctx)
        key = (ctx.guild.id, ctx.author.id)
        if key in self._active_wizards:
            raise commands.UserFeedbackCheckFailure(
                "You already have a raid creation wizard open in your DMs."
            )
        self._active_wizards.add(key)
        try:
            try:
                await ctx.author.send("📨 Starting your Reverb Raid creation wizard…")
            except discord.Forbidden as exc:
                raise commands.UserFeedbackCheckFailure(
                    "I cannot DM you. Allow direct messages from server members, then try again."
                ) from exc
            await ctx.send(
                "I've sent the raid creation wizard to your DMs.",
                ephemeral=ctx.interaction is not None,
            )
            wizard = RaidCreationWizard(self, ctx.author, ctx.guild, ctx.channel)
            draft = await wizard.run()
            event_id, message = await self.create_event(ctx.guild, ctx.author, draft)
            await ctx.author.send(
                f"✅ **{draft.title}** was created.\n{message.jump_url}\nEvent ID: `{event_id}`"
            )
        except WizardCancelled as exc:
            await ctx.author.send(str(exc))
        except RaidInputError as exc:
            await ctx.author.send(f"⚠️ {exc}")
        finally:
            self._active_wizards.discard(key)

    @commands.hybrid_command(name="create")
    @app_commands.guild_only()
    @commands.guild_only()
    async def create_raid(self, ctx: commands.Context) -> None:
        """Create an EQ2 raid through a private guided wizard."""
        await self._run_creation_wizard(ctx)

    @commands.hybrid_group(name="raid")
    @app_commands.guild_only()
    @commands.guild_only()
    async def raid_group(self, ctx: commands.Context) -> None:
        """Create, list, and manage Reverb Raid events."""
        await ctx.send_help()

    @raid_group.command(name="create")
    async def raid_create(self, ctx: commands.Context) -> None:
        """Create a raid through a private guided wizard."""
        await self._run_creation_wizard(ctx)

    @raid_group.command(name="setup")
    async def raid_setup(self, ctx: commands.Context) -> None:
        """Open the server's interactive raid configuration panel."""
        if not ctx.author.guild_permissions.manage_guild:
            raise commands.UserFeedbackCheckFailure("You need **Manage Server** to use setup.")
        view = ConfigDashboardView(self, ctx.guild.id, ctx.author.id)
        message = await ctx.send(
            embed=await self.build_config_embed(ctx.guild.id),
            view=view,
            ephemeral=ctx.interaction is not None,
        )
        view.message = message

    @raid_group.command(name="gettingstarted")
    async def raid_getting_started(self, ctx: commands.Context) -> None:
        """Open the skippable setup and feature walkthrough."""
        if not ctx.author.guild_permissions.manage_guild:
            raise commands.UserFeedbackCheckFailure(
                "You need **Manage Server** to use the setup walkthrough."
            )
        view = GettingStartedView(self, ctx.guild.id, ctx.author.id)
        message = await ctx.send(
            embed=await view.build_embed(),
            view=view,
            ephemeral=ctx.interaction is not None,
        )
        view.message = message

    @raid_group.command(name="syncicons")
    @commands.is_owner()
    async def raid_sync_icons(self, ctx: commands.Context) -> None:
        """Install or repair the bundled EQ2 application emoji pack."""
        try:
            if ctx.interaction is not None:
                await ctx.defer(ephemeral=True)
                created, reused, refreshed = await self.sync_application_icons()
            else:
                async with ctx.typing():
                    created, reused, refreshed = await self.sync_application_icons()
        except RaidInputError as exc:
            raise commands.UserFeedbackCheckFailure(str(exc)) from exc
        await ctx.send(
            f"EQ2 icons are ready: **{created} created**, **{reused} reused**, and "
            f"**{refreshed} active raid message(s) refreshed**.",
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="list")
    async def raid_list(self, ctx: commands.Context) -> None:
        """List upcoming, non-archived raids."""
        events = await self.config.guild(ctx.guild).events()
        now_ts = int(datetime.now(timezone.utc).timestamp())
        upcoming = sorted(
            (
                event
                for event in events.values()
                if not event.get("archived") and event.get("start_ts", 0) >= now_ts - 12 * 3600
            ),
            key=lambda event: event.get("start_ts", 0),
        )[:20]
        if not upcoming:
            await ctx.send("There are no upcoming Reverb Raid events.", ephemeral=ctx.interaction is not None)
            return
        lines = []
        for event in upcoming:
            link = (
                f"https://discord.com/channels/{ctx.guild.id}/{event['channel_id']}/{event['message_id']}"
                if event.get("message_id")
                else None
            )
            title = discord.utils.escape_markdown(event.get("title", "Raid"))
            title_display = f"[{title}]({link})" if link else title
            state = "closed" if event.get("closed") else "open"
            lines.append(f"• {title_display} — <t:{event['start_ts']}:F> — `{event['id']}` ({state})")
        embed = discord.Embed(
            title="Upcoming Reverb Raids",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        await ctx.send(embed=embed, ephemeral=ctx.interaction is not None)

    @raid_group.command(name="history")
    async def raid_history(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ) -> None:
        """View retained completed and archived raids, optionally for one member."""
        await self.require_organizer(ctx)
        await ctx.send(
            embed=await self.build_history_embed(ctx.guild, member),
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="exporthistory")
    async def raid_export_history(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ) -> None:
        """Export all retained historic signup entries as CSV."""
        await self.require_organizer(ctx)
        file = await self.export_history(ctx.guild.id, member.id if member else None)
        await ctx.send(file=file, ephemeral=ctx.interaction is not None)

    @raid_group.command(name="show")
    async def raid_show(self, ctx: commands.Context, event_id: str) -> None:
        """Show the link and current roster for an event ID."""
        event = await self.get_event(ctx.guild.id, event_id)
        if event is None:
            raise commands.UserFeedbackCheckFailure("No raid has that event ID.")
        await ctx.send(
            embed=await self.build_event_embed(ctx.guild, event),
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="manage")
    async def raid_manage(self, ctx: commands.Context, event_id: str) -> None:
        """Open organizer controls for an event ID."""
        if not await self.can_manage_event(ctx.author, ctx.guild.id, event_id):
            raise commands.UserFeedbackCheckFailure("You cannot manage that raid.")
        event = await self.get_event(ctx.guild.id, event_id)
        view = ManageEventView(
            self,
            event_id,
            ctx.author.id,
            bool(event.get("closed")),
        )
        await ctx.send(
            f"Manage **{event['title']}** (`{event_id}`):",
            view=view,
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="eventreminder")
    async def raid_event_reminder(
        self, ctx: commands.Context, event_id: str, lead_time: str
    ) -> None:
        """Set this raid's reminder lead time, such as 1h, or use off."""
        try:
            minutes = parse_reminder_minutes(lead_time)
            await self.set_event_reminder(ctx.guild.id, event_id, ctx.author, minutes)
        except RaidInputError as exc:
            raise commands.UserFeedbackCheckFailure(str(exc)) from exc
        value = f"{format_minutes(minutes)} before start" if minutes else "disabled"
        await ctx.send(
            f"That raid's reminder is now **{value}**.",
            ephemeral=ctx.interaction is not None,
        )

    async def _require_manage_guild(self, ctx: commands.Context) -> None:
        if not ctx.author.guild_permissions.manage_guild:
            raise commands.UserFeedbackCheckFailure(
                "You need **Manage Server** to change raid configuration."
            )

    @raid_group.command(name="timezone")
    async def raid_timezone(self, ctx: commands.Context, timezone_name: str) -> None:
        """Set the raid timezone, such as America/New_York."""
        await self._require_manage_guild(ctx)
        try:
            get_timezone(timezone_name)
        except RaidInputError as exc:
            raise commands.UserFeedbackCheckFailure(str(exc)) from exc
        await self.set_guild_setting(ctx.guild.id, "timezone", timezone_name)
        await ctx.send(
            f"Raid timezone set to `{timezone_name}`.",
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="channel")
    async def raid_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the default channel where raid signup messages are posted."""
        await self._require_manage_guild(ctx)
        await self.set_guild_setting(ctx.guild.id, "default_channel_id", channel.id)
        await ctx.send(
            f"Default raid channel set to {channel.mention}.",
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="duration")
    async def raid_duration(self, ctx: commands.Context, duration: str) -> None:
        """Set the default raid duration, such as 3h or 150m."""
        await self._require_manage_guild(ctx)
        try:
            minutes = parse_duration(duration)
        except RaidInputError as exc:
            raise commands.UserFeedbackCheckFailure(str(exc)) from exc
        await self.set_guild_setting(ctx.guild.id, "default_duration_minutes", minutes)
        await ctx.send(
            f"Default raid duration set to {minutes} minutes.",
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="reminder")
    async def raid_reminder(self, ctx: commands.Context, lead_time: str) -> None:
        """Set the default reminder for new raids, such as 1h, or use off."""
        await self._require_manage_guild(ctx)
        try:
            minutes = parse_reminder_minutes(lead_time)
        except RaidInputError as exc:
            raise commands.UserFeedbackCheckFailure(str(exc)) from exc
        await self.set_guild_setting(ctx.guild.id, "default_reminder_minutes", minutes)
        value = f"{format_minutes(minutes)} before start" if minutes else "disabled"
        await ctx.send(
            f"New raids will have reminders **{value}**.",
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="description")
    async def raid_description(self, ctx: commands.Context, *, description: str) -> None:
        """Set the default description used by the creation wizard."""
        await self._require_manage_guild(ctx)
        description = trim_text(description, MAX_DESCRIPTION_LENGTH)
        await self.set_guild_setting(ctx.guild.id, "default_description", description)
        await ctx.send("Default raid description saved.", ephemeral=ctx.interaction is not None)

    @raid_group.command(name="organizerrole")
    async def raid_organizer_role(
        self,
        ctx: commands.Context,
        action: str,
        role: discord.Role,
    ) -> None:
        """Add or remove a role that may create and manage raids."""
        await self._require_manage_guild(ctx)
        action = action.casefold()
        if action not in {"add", "remove"}:
            raise commands.UserFeedbackCheckFailure("Action must be `add` or `remove`.")
        role_ids = set(await self.config.guild(ctx.guild).organizer_role_ids())
        if action == "add":
            role_ids.add(role.id)
        else:
            role_ids.discard(role.id)
        await self.set_guild_setting(ctx.guild.id, "organizer_role_ids", sorted(role_ids))
        await ctx.send(
            f"{role.mention} was {'added to' if action == 'add' else 'removed from'} raid organizers.",
            ephemeral=ctx.interaction is not None,
        )

    @raid_group.command(name="mentionrole")
    async def raid_mention_role(
        self,
        ctx: commands.Context,
        role: Optional[discord.Role] = None,
    ) -> None:
        """Set the role mentioned for new raids, or omit it to clear."""
        await self._require_manage_guild(ctx)
        await self.set_guild_setting(
            ctx.guild.id,
            "mention_role_id",
            role.id if role else None,
        )
        message = f"New raids will mention {role.mention}." if role else "New raids will not mention a role."
        await ctx.send(message, ephemeral=ctx.interaction is not None)

    # ---------------------------------------------------------------------
    # Red end-user data hooks
    # ---------------------------------------------------------------------

    async def red_get_data_for_user(self, *, user_id: int) -> Dict[str, io.BytesIO]:
        records = []
        for guild_id, settings in (await self.config.all_guilds()).items():
            for event_id, event in settings.get("events", {}).items():
                signup = event.get("roster", {}).get(str(user_id))
                if signup is not None or event.get("creator_id") == user_id:
                    records.append(
                        {
                            "guild_id": guild_id,
                            "event_id": event_id,
                            "event_title": event.get("title"),
                            "creator": event.get("creator_id") == user_id,
                            "signup": signup,
                        }
                    )
        payload = io.BytesIO(json.dumps(records, indent=2).encode("utf-8"))
        return {"reverbraid.json": payload}

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        refresh: List[tuple[int, str]] = []
        for raw_guild_id in (await self.config.all_guilds()).keys():
            guild_id = int(raw_guild_id)
            changed_ids = []
            async with self.config.guild_from_id(guild_id).events() as events:
                for event_id, event in events.items():
                    if event.get("roster", {}).pop(str(user_id), None) is not None:
                        changed_ids.append(event_id)
                    if event.get("creator_id") == user_id:
                        event["creator_id"] = 0
                        changed_ids.append(event_id)
            refresh.extend((guild_id, event_id) for event_id in set(changed_ids))
        for guild_id, event_id in refresh:
            await self.refresh_event_message(guild_id, event_id)
