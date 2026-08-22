"""Discord UI components for raid signups and configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord

from .constants import (
    ARCHETYPE_EMOJIS,
    ARCHETYPE_LABELS,
    ARCHETYPES,
    MAX_DESCRIPTION_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_TITLE_LENGTH,
    STATUS_EMOJIS,
    STATUS_LABELS,
)
from .models import RaidInputError, get_timezone, parse_duration, parse_raid_datetime, trim_text

if TYPE_CHECKING:
    from .reverbraid import ReverbRaid


async def ephemeral_error(interaction: discord.Interaction, message: str) -> None:
    """Reply to an interaction without ever leaking operational errors to chat."""
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class ClassButton(discord.ui.Button):
    def __init__(
        self,
        cog: "ReverbRaid",
        event_id: str,
        archetype: str,
        *,
        disabled: bool,
        emoji: str,
        class_emoji_map: dict,
    ):
        super().__init__(
            label=ARCHETYPE_LABELS[archetype],
            emoji=emoji,
            style=discord.ButtonStyle.primary,
            custom_id=f"reverbraid:class:{event_id}:{archetype}",
            row=0,
            disabled=disabled,
        )
        self.cog = cog
        self.event_id = event_id
        self.archetype = archetype
        self.display_emoji = emoji
        self.class_emoji_map = class_emoji_map

    async def callback(self, interaction: discord.Interaction) -> None:
        event = await self.cog.get_event(interaction.guild_id, self.event_id)
        if event is None:
            await ephemeral_error(interaction, "This raid no longer exists.")
            return
        if event.get("closed"):
            await ephemeral_error(interaction, "Signups for this raid are closed.")
            return
        view = ClassSelectView(
            self.cog,
            self.event_id,
            self.archetype,
            self.display_emoji,
            self.class_emoji_map,
        )
        await interaction.response.send_message(
            f"Choose your **{ARCHETYPE_LABELS[self.archetype]}** class:",
            view=view,
            ephemeral=True,
        )


class ClassSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "ReverbRaid",
        event_id: str,
        archetype: str,
        emoji: str,
        class_emoji_map: dict,
    ):
        options = [
            discord.SelectOption(
                label=class_name,
                value=class_name,
                emoji=class_emoji_map.get(class_name, emoji),
            )
            for class_name in ARCHETYPES[archetype]
        ]
        super().__init__(
            placeholder=f"Select a {ARCHETYPE_LABELS[archetype]} class…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            message = await self.cog.set_signup_class(
                interaction.guild_id,
                self.event_id,
                interaction.user,
                self.values[0],
            )
        except RaidInputError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.edit_original_response(content=message, view=None)


class ClassSelectView(discord.ui.View):
    def __init__(
        self,
        cog: "ReverbRaid",
        event_id: str,
        archetype: str,
        emoji: str,
        class_emoji_map: dict,
    ):
        super().__init__(timeout=120)
        self.add_item(ClassSelect(cog, event_id, archetype, emoji, class_emoji_map))


class StatusButton(discord.ui.Button):
    def __init__(self, cog: "ReverbRaid", event_id: str, *, disabled: bool):
        super().__init__(
            label="Status…",
            emoji="📋",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reverbraid:status:{event_id}",
            row=0,
            disabled=disabled,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        event = await self.cog.get_event(interaction.guild_id, self.event_id)
        if event is None:
            await ephemeral_error(interaction, "This raid no longer exists.")
            return
        if event.get("closed"):
            await ephemeral_error(interaction, "Signups for this raid are closed.")
            return
        await interaction.response.send_message(
            "Set your availability or withdraw your signup:",
            view=StatusSelectView(self.cog, self.event_id),
            ephemeral=True,
        )


class StatusSelect(discord.ui.Select):
    def __init__(self, cog: "ReverbRaid", event_id: str):
        options = [
            discord.SelectOption(label=label, value=status, emoji=STATUS_EMOJIS[status])
            for status, label in STATUS_LABELS.items()
        ]
        options.append(discord.SelectOption(label="Withdraw signup", value="withdraw", emoji="❌"))
        super().__init__(
            placeholder="Attending, tentative, late, absent, or withdraw…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            message = await self.cog.set_signup_status(
                interaction.guild_id,
                self.event_id,
                interaction.user,
                self.values[0],
            )
        except RaidInputError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.edit_original_response(content=message, view=None)


class StatusSelectView(discord.ui.View):
    def __init__(self, cog: "ReverbRaid", event_id: str):
        super().__init__(timeout=120)
        self.add_item(StatusSelect(cog, event_id))


class SignupNoteModal(discord.ui.Modal, title="Raid signup note"):
    note = discord.ui.TextInput(
        label="Note",
        placeholder="Example: About 30 minutes late",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_NOTE_LENGTH,
    )

    def __init__(self, cog: "ReverbRaid", event_id: str, existing_note: str = ""):
        super().__init__()
        self.cog = cog
        self.event_id = event_id
        self.note.default = existing_note

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            message = await self.cog.set_signup_note(
                interaction.guild_id,
                self.event_id,
                interaction.user,
                str(self.note),
            )
        except RaidInputError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(message, ephemeral=True)


class NoteButton(discord.ui.Button):
    def __init__(self, cog: "ReverbRaid", event_id: str, *, disabled: bool):
        super().__init__(
            label="Signup note",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reverbraid:note:{event_id}",
            row=1,
            disabled=disabled,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        event = await self.cog.get_event(interaction.guild_id, self.event_id)
        if event is None:
            await ephemeral_error(interaction, "This raid no longer exists.")
            return
        signup = event.get("roster", {}).get(str(interaction.user.id), {})
        if not signup:
            await ephemeral_error(interaction, "Choose a class or status before adding a note.")
            return
        await interaction.response.send_modal(
            SignupNoteModal(self.cog, self.event_id, str(signup.get("note") or ""))
        )


class ManageButton(discord.ui.Button):
    def __init__(self, cog: "ReverbRaid", event_id: str):
        super().__init__(
            label="Manage",
            emoji="⚙️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reverbraid:manage:{event_id}",
            row=1,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog.can_manage_event(interaction.user, interaction.guild_id, self.event_id):
            await ephemeral_error(interaction, "Only raid organizers can manage this event.")
            return
        await self.cog.send_manage_panel(interaction, self.event_id)


class RaidSignupView(discord.ui.View):
    """Persistent component view attached to every posted raid."""

    def __init__(
        self,
        cog: "ReverbRaid",
        event_id: str,
        *,
        closed: bool = False,
        emoji_map: Optional[dict] = None,
        class_emoji_map: Optional[dict] = None,
    ):
        super().__init__(timeout=None)
        emoji_map = emoji_map or {}
        class_emoji_map = class_emoji_map or {}
        for archetype in ARCHETYPES:
            self.add_item(
                ClassButton(
                    cog,
                    event_id,
                    archetype,
                    disabled=closed,
                    emoji=emoji_map.get(archetype, ARCHETYPE_EMOJIS[archetype]),
                    class_emoji_map=class_emoji_map,
                )
            )
        self.add_item(StatusButton(cog, event_id, disabled=closed))
        self.add_item(NoteButton(cog, event_id, disabled=closed))
        self.add_item(ManageButton(cog, event_id))


class RaidEditModal(discord.ui.Modal, title="Edit raid event"):
    raid_title = discord.ui.TextInput(label="Title", max_length=MAX_TITLE_LENGTH)
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_DESCRIPTION_LENGTH,
    )
    start_time = discord.ui.TextInput(
        label="Date and time",
        placeholder="2026-08-28 8:00 PM",
        max_length=80,
    )
    duration = discord.ui.TextInput(label="Duration", placeholder="3h", max_length=30)

    def __init__(self, cog: "ReverbRaid", event_id: str, event: dict, timezone_name: str):
        super().__init__()
        self.cog = cog
        self.event_id = event_id
        self.timezone_name = timezone_name
        self.raid_title.default = event.get("title", "")
        self.description.default = event.get("description", "")
        self.start_time.default = cog.format_local_time(event["start_ts"], timezone_name)
        self.duration.default = f"{event.get('duration_minutes', 180)}m"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            start = parse_raid_datetime(str(self.start_time), self.timezone_name)
            duration = parse_duration(str(self.duration))
        except RaidInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.edit_event(
                interaction.guild_id,
                self.event_id,
                interaction.user,
                title=trim_text(str(self.raid_title), MAX_TITLE_LENGTH),
                description=trim_text(str(self.description), MAX_DESCRIPTION_LENGTH),
                start_ts=int(start.timestamp()),
                duration_minutes=duration,
            )
        except RaidInputError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("Raid event updated.", ephemeral=True)


class ConfirmArchiveView(discord.ui.View):
    def __init__(self, cog: "ReverbRaid", event_id: str, owner_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.event_id = event_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await ephemeral_error(interaction, "This confirmation belongs to another organizer.")
            return False
        return True

    @discord.ui.button(label="Archive raid", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.cog.archive_event(interaction.guild_id, self.event_id, interaction.user)
        await interaction.edit_original_response(
            content="Raid archived and its signup controls removed.", view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Archive cancelled.", view=None)
        self.stop()


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, cog: "ReverbRaid", event_id: str, owner_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.event_id = event_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await ephemeral_error(interaction, "This confirmation belongs to another organizer.")
            return False
        return True

    @discord.ui.button(label="Permanently delete", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.cog.purge_event(interaction.guild_id, self.event_id, interaction.user)
        await interaction.edit_original_response(
            content="The event and its stored roster were permanently deleted.", view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Deletion cancelled.", view=None)
        self.stop()


class ManageEventView(discord.ui.View):
    def __init__(self, cog: "ReverbRaid", event_id: str, owner_id: int, closed: bool):
        super().__init__(timeout=300)
        self.cog = cog
        self.event_id = event_id
        self.owner_id = owner_id
        self.toggle.label = "Reopen signups" if closed else "Close signups"
        self.toggle.emoji = "🔓" if closed else "🔒"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await ephemeral_error(interaction, "Open your own management panel to use these controls.")
            return False
        if not await self.cog.can_manage_event(interaction.user, interaction.guild_id, self.event_id):
            await ephemeral_error(interaction, "You no longer have permission to manage this raid.")
            return False
        return True

    @discord.ui.button(label="Close signups", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        closed = await self.cog.toggle_event_closed(
            interaction.guild_id, self.event_id, interaction.user
        )
        await interaction.edit_original_response(
            content="Signups closed." if closed else "Signups reopened.", view=None
        )
        self.stop()

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        event = await self.cog.get_event(interaction.guild_id, self.event_id)
        if event is None:
            await ephemeral_error(interaction, "This raid no longer exists.")
            return
        timezone_name = await self.cog.get_guild_timezone(interaction.guild_id)
        await interaction.response.send_modal(
            RaidEditModal(self.cog, self.event_id, event, timezone_name)
        )

    @discord.ui.button(label="Export CSV", style=discord.ButtonStyle.secondary, emoji="📄")
    async def export(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        file = await self.cog.export_roster(interaction.guild_id, self.event_id)
        if file is None:
            await interaction.followup.send("This raid no longer exists.", ephemeral=True)
            return
        await interaction.followup.send(file=file, ephemeral=True)

    @discord.ui.button(label="Archive", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def archive(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Archive this raid? The roster is retained, but signup controls will be removed.",
            view=ConfirmArchiveView(self.cog, self.event_id, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Delete data", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def delete_data(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Permanently delete this event and its roster? This cannot be undone.",
            view=ConfirmDeleteView(self.cog, self.event_id, interaction.user.id),
            ephemeral=True,
        )


class TimezoneModal(discord.ui.Modal, title="Raid timezone"):
    timezone_name = discord.ui.TextInput(
        label="IANA timezone",
        placeholder="America/New_York",
        max_length=64,
    )

    def __init__(self, dashboard: "ConfigDashboardView", current: str):
        super().__init__()
        self.dashboard = dashboard
        self.timezone_name.default = current

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = str(self.timezone_name).strip()
        try:
            get_timezone(value)
        except RaidInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "timezone", value
        )
        await interaction.response.defer(ephemeral=True)
        await self.dashboard.refresh_message()
        await interaction.followup.send(f"Timezone set to `{value}`.", ephemeral=True)


class DescriptionModal(discord.ui.Modal, title="Default raid description"):
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=MAX_DESCRIPTION_LENGTH,
    )

    def __init__(self, dashboard: "ConfigDashboardView", current: str):
        super().__init__()
        self.dashboard = dashboard
        self.description.default = current

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id,
            "default_description",
            trim_text(str(self.description), MAX_DESCRIPTION_LENGTH),
        )
        await interaction.response.defer(ephemeral=True)
        await self.dashboard.refresh_message()
        await interaction.followup.send("Default description saved.", ephemeral=True)


class DurationModal(discord.ui.Modal, title="Default raid duration"):
    duration = discord.ui.TextInput(label="Duration", placeholder="3h", max_length=30)

    def __init__(self, dashboard: "ConfigDashboardView", current_minutes: int):
        super().__init__()
        self.dashboard = dashboard
        self.duration.default = f"{current_minutes}m"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minutes = parse_duration(str(self.duration))
        except RaidInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "default_duration_minutes", minutes
        )
        await interaction.response.defer(ephemeral=True)
        await self.dashboard.refresh_message()
        await interaction.followup.send(f"Default duration set to {minutes} minutes.", ephemeral=True)


class ArchetypeEmojiModal(discord.ui.Modal, title="Archetype button icons"):
    fighter = discord.ui.TextInput(label="Fighter emoji", required=False, max_length=100)
    priest = discord.ui.TextInput(label="Priest emoji", required=False, max_length=100)
    mage = discord.ui.TextInput(label="Mage emoji", required=False, max_length=100)
    scout = discord.ui.TextInput(label="Scout emoji", required=False, max_length=100)

    def __init__(self, dashboard: "ConfigDashboardView", current: dict):
        super().__init__()
        self.dashboard = dashboard
        for archetype in ARCHETYPES:
            getattr(self, archetype).default = current.get(
                archetype, ARCHETYPE_EMOJIS[archetype]
            )

    @staticmethod
    def _validate(value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        emoji = discord.PartialEmoji.from_str(value)
        if emoji.id is None and len(value) > 8:
            raise RaidInputError(
                "Use one Unicode emoji or paste a custom Discord emoji such as `<:fighter:1234567890>`."
            )
        return value

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            values = {
                archetype: self._validate(str(getattr(self, archetype)))
                for archetype in ARCHETYPES
            }
        except RaidInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        for value in values.values():
            emoji = discord.PartialEmoji.from_str(value)
            if (
                emoji.id is not None
                and interaction.guild.get_emoji(emoji.id) is None
                and not self.dashboard.cog.is_application_emoji_id(emoji.id)
            ):
                await interaction.response.send_message(
                    "Custom button icons must be uploaded to this Discord server or belong "
                    "to this bot's application emoji pack.",
                    ephemeral=True,
                )
                return
        values = {key: value for key, value in values.items() if value}
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "archetype_emojis", values
        )
        await interaction.response.defer(ephemeral=True)
        await self.dashboard.refresh_message()
        await interaction.followup.send(
            "Archetype button icons saved. Existing raid messages update on their next signup.",
            ephemeral=True,
        )


class DefaultChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, dashboard: "ConfigDashboardView"):
        super().__init__(
            placeholder="Choose the default raid channel…",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.dashboard = dashboard

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "default_channel_id", self.values[0].id
        )
        await interaction.response.edit_message(
            embed=await self.dashboard.cog.build_config_embed(interaction.guild_id),
            view=self.dashboard,
        )


class OrganizerRoleSelect(discord.ui.RoleSelect):
    def __init__(self, dashboard: "ConfigDashboardView"):
        super().__init__(
            placeholder="Choose organizer roles (select again to replace)…",
            min_values=0,
            max_values=10,
            row=1,
        )
        self.dashboard = dashboard

    async def callback(self, interaction: discord.Interaction) -> None:
        role_ids = [role.id for role in self.values if not role.is_default()]
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "organizer_role_ids", role_ids
        )
        await interaction.response.edit_message(
            embed=await self.dashboard.cog.build_config_embed(interaction.guild_id),
            view=self.dashboard,
        )


class MentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, dashboard: "ConfigDashboardView"):
        super().__init__(
            placeholder="Choose one role to mention when a raid is posted (optional)…",
            min_values=0,
            max_values=1,
            row=2,
        )
        self.dashboard = dashboard

    async def callback(self, interaction: discord.Interaction) -> None:
        role_id = None
        if self.values and not self.values[0].is_default():
            role_id = self.values[0].id
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "mention_role_id", role_id
        )
        await interaction.response.edit_message(
            embed=await self.dashboard.cog.build_config_embed(interaction.guild_id),
            view=self.dashboard,
        )


class ConfigDashboardView(discord.ui.View):
    def __init__(self, cog: "ReverbRaid", guild_id: int, owner_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.message: Optional[discord.Message] = None
        self.add_item(DefaultChannelSelect(self))
        self.add_item(OrganizerRoleSelect(self))
        self.add_item(MentionRoleSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await ephemeral_error(interaction, "Open your own setup panel to change these settings.")
            return False
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not permissions.manage_guild:
            await ephemeral_error(interaction, "You need **Manage Server** to change raid settings.")
            return False
        return True

    async def refresh_message(self) -> None:
        if self.message is not None:
            await self.message.edit(
                embed=await self.cog.build_config_embed(self.guild_id),
                view=self,
            )

    @discord.ui.button(label="Timezone", style=discord.ButtonStyle.primary, row=3)
    async def timezone(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.get_guild_timezone(interaction.guild_id)
        await interaction.response.send_modal(TimezoneModal(self, current))

    @discord.ui.button(label="Default description", style=discord.ButtonStyle.secondary, row=3)
    async def description(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        settings = await self.cog.get_guild_settings(interaction.guild_id)
        await interaction.response.send_modal(
            DescriptionModal(self, settings["default_description"])
        )

    @discord.ui.button(label="Duration", style=discord.ButtonStyle.secondary, row=3)
    async def duration(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        settings = await self.cog.get_guild_settings(interaction.guild_id)
        await interaction.response.send_modal(
            DurationModal(self, settings["default_duration_minutes"])
        )

    @discord.ui.button(label="Button icons", style=discord.ButtonStyle.secondary, row=3)
    async def icons(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        settings = await self.cog.get_guild_settings(interaction.guild_id)
        await interaction.response.send_modal(
            ArchetypeEmojiModal(
                self,
                self.cog.resolve_archetype_emoji_map(
                    interaction.guild, settings.get("archetype_emojis", {})
                ),
            )
        )

    @discord.ui.button(
        label="Sync EQ2 icons",
        style=discord.ButtonStyle.success,
        emoji="🎨",
        row=4,
    )
    async def sync_icons(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.bot.is_owner(interaction.user):
            await ephemeral_error(
                interaction,
                "Only the Red bot owner can change the bot's shared application emojis.",
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            created, reused, refreshed = await self.cog.sync_application_icons()
        except RaidInputError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await self.refresh_message()
        await interaction.followup.send(
            f"EQ2 icons are ready: **{created} created**, **{reused} reused**, and "
            f"**{refreshed} active raid message(s) refreshed**.",
            ephemeral=True,
        )


def disable_view(view: discord.ui.View) -> None:
    """Disable every component in a view before an archival edit."""
    for item in view.children:
        if hasattr(item, "disabled"):
            item.disabled = True
