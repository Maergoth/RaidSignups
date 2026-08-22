"""Private-message raid creation wizard."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Optional

import discord

from .constants import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH
from .models import RaidInputError, parse_duration, parse_raid_datetime, trim_text


class WizardCancelled(Exception):
    """Raised when the organizer cancels or times out of the wizard."""


@dataclass
class RaidDraft:
    title: str
    description: str
    start_ts: int
    duration_minutes: int
    channel_id: int


class ConfirmCreateView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.confirmed: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This raid wizard belongs to another organizer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Create raid", style=discord.ButtonStyle.success, emoji="✅")
    async def create(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Creating raid…", view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Raid creation cancelled.", view=self)
        self.stop()


class RaidCreationWizard:
    """Collect a complete raid draft in an organizer's DMs."""

    def __init__(self, cog, user: discord.Member, guild: discord.Guild, origin_channel):
        self.cog = cog
        self.bot = cog.bot
        self.user = user
        self.guild = guild
        self.origin_channel = origin_channel
        self.dm: Optional[discord.DMChannel] = None

    async def _ensure_dm(self) -> discord.DMChannel:
        if self.dm is None:
            self.dm = self.user.dm_channel or await self.user.create_dm()
        return self.dm

    async def _ask_text(
        self,
        title: str,
        prompt: str,
        *,
        default: Optional[str] = None,
        allow_skip: bool = False,
    ) -> str:
        dm = await self._ensure_dm()
        description = prompt
        if default is not None:
            description += f"\n\nReply `default` to use:\n> {trim_text(default, 700)}"
        if allow_skip:
            description += "\n\nReply `skip` to leave this blank."
        description += "\n\nReply `cancel` at any time to stop."
        embed = discord.Embed(title=title, description=description, color=0x6D4AFF)
        await dm.send(embed=embed)

        def check(message: discord.Message) -> bool:
            return message.author.id == self.user.id and message.channel.id == dm.id

        try:
            message = await self.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError as exc:
            raise WizardCancelled("The raid wizard timed out after five minutes.") from exc

        value = message.content.strip()
        if value.casefold() == "cancel":
            raise WizardCancelled("Raid creation cancelled.")
        if default is not None and value.casefold() == "default":
            return default
        if allow_skip and value.casefold() == "skip":
            return ""
        if not value:
            raise RaidInputError("Please send a text response.")
        return value

    async def _ask_validated(self, title: str, prompt: str, parser_callback, **kwargs):
        while True:
            value = await self._ask_text(title, prompt, **kwargs)
            try:
                return parser_callback(value)
            except RaidInputError as exc:
                await (await self._ensure_dm()).send(f"⚠️ {exc} Please try again.")

    def _resolve_channel(self, value: str, default_channel_id: int):
        if value.casefold() in {"default", "current"}:
            channel_id = default_channel_id
        else:
            match = re.fullmatch(r"<?#?(\d{15,22})>?", value.strip())
            if not match:
                raise RaidInputError("Reply `default`, a channel mention, or a channel ID.")
            channel_id = int(match.group(1))

        channel = self.guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise RaidInputError("That is not a text channel in this server.")
        return channel

    async def run(self) -> RaidDraft:
        settings = await self.cog.get_guild_settings(self.guild.id)
        timezone_name = settings["timezone"]
        configured_channel_id = settings.get("default_channel_id")
        origin_id = getattr(self.origin_channel, "id", None)
        default_channel_id = configured_channel_id or origin_id
        default_channel = self.guild.get_channel(default_channel_id) if default_channel_id else None
        if not isinstance(default_channel, (discord.TextChannel, discord.Thread)):
            raise RaidInputError(
                "No usable raid channel is configured. Run `/raid setup` in the server first."
            )

        dm = await self._ensure_dm()
        intro = discord.Embed(
            title="Reverb Raid Sign-up Helper",
            description=(
                f"Let's create a raid for **{self.guild.name}**. I will ask five short "
                "questions, then show you a final preview. Times without an offset use "
                f"`{timezone_name}`."
            ),
            color=0x6D4AFF,
        )
        await dm.send(embed=intro)

        title = await self._ask_validated(
            "1 of 5 — Raid title",
            "What should this event be called?",
            lambda value: self._validate_title(value),
        )
        description = await self._ask_validated(
            "2 of 5 — Description",
            "Describe the target, expectations, or anything raiders should know.",
            lambda value: trim_text(value, MAX_DESCRIPTION_LENGTH),
            default=settings["default_description"],
            allow_skip=True,
        )
        start = await self._ask_validated(
            "3 of 5 — Date and time",
            (
                "When does the raid start? Examples: `2026-08-28 8:00 PM`, "
                "`Friday 8 PM`, or `tomorrow 20:00`."
            ),
            lambda value: parse_raid_datetime(value, timezone_name),
        )
        duration = await self._ask_validated(
            "4 of 5 — Duration",
            "How long is the raid? Use minutes, `3h`, or `2h 30m`.",
            parse_duration,
            default=f"{settings['default_duration_minutes']}m",
        )
        channel = await self._ask_validated(
            "5 of 5 — Raid channel",
            (
                f"Where should I post it? The current default is **#{default_channel.name}**. "
                "Reply `default`, mention another text channel, or paste its ID."
            ),
            lambda value: self._resolve_channel(value, default_channel.id),
            default="default",
        )

        draft = RaidDraft(
            title=title,
            description=description,
            start_ts=int(start.timestamp()),
            duration_minutes=duration,
            channel_id=channel.id,
        )
        preview = discord.Embed(
            title=f"⚔️ {draft.title}",
            description=draft.description or "*No description*",
            color=0x6D4AFF,
        )
        preview.add_field(name="Starts", value=f"<t:{draft.start_ts}:F>\n<t:{draft.start_ts}:R>")
        preview.add_field(name="Duration", value=f"{draft.duration_minutes} minutes")
        preview.add_field(name="Channel", value=channel.mention)
        preview.set_footer(text="Review the details, then create or cancel.")
        view = ConfirmCreateView(self.user.id)
        await dm.send(embed=preview, view=view)
        timed_out = await view.wait()
        if timed_out or not view.confirmed:
            raise WizardCancelled("Raid creation cancelled or timed out.")
        return draft

    @staticmethod
    def _validate_title(value: str) -> str:
        value = trim_text(value, MAX_TITLE_LENGTH)
        if len(value) < 3:
            raise RaidInputError("The title must be at least three characters.")
        return value
