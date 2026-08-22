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
from .models import (
    RaidInputError,
    format_minutes,
    get_timezone,
    parse_duration,
    parse_raid_datetime,
    parse_reminder_minutes,
    trim_text,
)

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
            placeholder="Attending, tentative, late, bench, absent, or withdraw…",
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


class EventReminderModal(discord.ui.Modal, title="Raid reminder"):
    lead_time = discord.ui.TextInput(
        label="Lead time",
        placeholder="1h, 90m, or off",
        max_length=30,
    )

    def __init__(self, cog: "ReverbRaid", event_id: str, current_minutes: int):
        super().__init__()
        self.cog = cog
        self.event_id = event_id
        self.lead_time.default = f"{current_minutes}m" if current_minutes else "off"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minutes = parse_reminder_minutes(str(self.lead_time))
            await self.cog.set_event_reminder(
                interaction.guild_id,
                self.event_id,
                interaction.user,
                minutes,
            )
        except RaidInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        value = f"{format_minutes(minutes)} before start" if minutes else "disabled"
        await interaction.response.send_message(
            f"This raid's reminder is now **{value}**.", ephemeral=True
        )


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

    @discord.ui.button(
        label="Reminder",
        style=discord.ButtonStyle.secondary,
        emoji="⏰",
        row=0,
    )
    async def reminder(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        event = await self.cog.get_event(interaction.guild_id, self.event_id)
        if event is None:
            await ephemeral_error(interaction, "This raid no longer exists.")
            return
        await interaction.response.send_modal(
            EventReminderModal(
                self.cog,
                self.event_id,
                int(event.get("reminder_minutes") or 0),
            )
        )

    @discord.ui.button(
        label="Archive", style=discord.ButtonStyle.danger, emoji="🗑️", row=1
    )
    async def archive(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Archive this raid? The roster is retained, but signup controls will be removed.",
            view=ConfirmArchiveView(self.cog, self.event_id, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Delete data", style=discord.ButtonStyle.danger, emoji="⚠️", row=1
    )
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


class ReminderModal(discord.ui.Modal, title="Default raid reminder"):
    lead_time = discord.ui.TextInput(
        label="Lead time for new raids",
        placeholder="1h, 90m, or off",
        max_length=30,
    )

    def __init__(self, dashboard, current_minutes: int):
        super().__init__()
        self.dashboard = dashboard
        self.lead_time.default = f"{current_minutes}m" if current_minutes else "off"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minutes = parse_reminder_minutes(str(self.lead_time))
        except RaidInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.dashboard.cog.set_guild_setting(
            interaction.guild_id, "default_reminder_minutes", minutes
        )
        await interaction.response.defer(ephemeral=True)
        await self.dashboard.refresh_message()
        value = f"{format_minutes(minutes)} before start" if minutes else "disabled"
        await interaction.followup.send(
            f"New raids will have reminders **{value}**.", ephemeral=True
        )


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


class GettingStartedChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, guide: "GettingStartedView"):
        super().__init__(
            placeholder="Choose the default raid channel, or skip this step…",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.guide = guide

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.guide.cog.set_guild_setting(
            interaction.guild_id, "default_channel_id", self.values[0].id
        )
        await interaction.response.edit_message(
            embed=await self.guide.build_embed(),
            view=self.guide,
        )


class GettingStartedOrganizerRoleSelect(discord.ui.RoleSelect):
    def __init__(self, guide: "GettingStartedView"):
        super().__init__(
            placeholder="Choose organizer roles, or skip this step…",
            min_values=0,
            max_values=10,
            row=0,
        )
        self.guide = guide

    async def callback(self, interaction: discord.Interaction) -> None:
        role_ids = [role.id for role in self.values if not role.is_default()]
        await self.guide.cog.set_guild_setting(
            interaction.guild_id, "organizer_role_ids", role_ids
        )
        await interaction.response.edit_message(
            embed=await self.guide.build_embed(),
            view=self.guide,
        )


class GettingStartedMentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, guide: "GettingStartedView"):
        super().__init__(
            placeholder="Choose an announcement role, or skip this step…",
            min_values=0,
            max_values=1,
            row=1,
        )
        self.guide = guide

    async def callback(self, interaction: discord.Interaction) -> None:
        role_id = None
        if self.values and not self.values[0].is_default():
            role_id = self.values[0].id
        await self.guide.cog.set_guild_setting(
            interaction.guild_id, "mention_role_id", role_id
        )
        await interaction.response.edit_message(
            embed=await self.guide.build_embed(),
            view=self.guide,
        )


class GettingStartedButton(discord.ui.Button):
    def __init__(
        self,
        guide: "GettingStartedView",
        action: str,
        label: str,
        *,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        emoji: Optional[str] = None,
        row: int = 4,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            style=style,
            emoji=emoji,
            row=row,
            disabled=disabled,
        )
        self.guide = guide
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.action == "back":
            self.guide.step = max(0, self.guide.step - 1)
            self.guide.rebuild_items()
            await interaction.response.edit_message(
                embed=await self.guide.build_embed(),
                view=self.guide,
            )
            return
        if self.action == "next":
            self.guide.step = min(self.guide.LAST_STEP, self.guide.step + 1)
            self.guide.rebuild_items()
            await interaction.response.edit_message(
                embed=await self.guide.build_embed(),
                view=self.guide,
            )
            return
        if self.action == "setup":
            dashboard = ConfigDashboardView(
                self.guide.cog,
                self.guide.guild_id,
                self.guide.owner_id,
            )
            dashboard.message = interaction.message
            self.guide.stop()
            await interaction.response.edit_message(
                embed=await self.guide.cog.build_config_embed(self.guide.guild_id),
                view=dashboard,
            )
            return
        if self.action == "finish":
            self.guide.stop()
            embed = await self.guide.build_embed()
            embed.set_footer(text="Getting started complete • Run /raid setup any time")
            await interaction.response.edit_message(embed=embed, view=None)
            return
        if self.action == "timezone":
            current = await self.guide.cog.get_guild_timezone(interaction.guild_id)
            await interaction.response.send_modal(TimezoneModal(self.guide, current))
            return
        if self.action == "description":
            settings = await self.guide.cog.get_guild_settings(interaction.guild_id)
            await interaction.response.send_modal(
                DescriptionModal(self.guide, settings["default_description"])
            )
            return
        if self.action == "duration":
            settings = await self.guide.cog.get_guild_settings(interaction.guild_id)
            await interaction.response.send_modal(
                DurationModal(self.guide, settings["default_duration_minutes"])
            )
            return
        if self.action == "reminder":
            settings = await self.guide.cog.get_guild_settings(interaction.guild_id)
            await interaction.response.send_modal(
                ReminderModal(self.guide, settings["default_reminder_minutes"])
            )
            return
        if self.action == "sync_icons":
            if not await self.guide.cog.bot.is_owner(interaction.user):
                await ephemeral_error(
                    interaction,
                    "Only the Red bot owner can change the bot's shared application emojis. "
                    "You can skip this step.",
                )
                return
            await interaction.response.defer(ephemeral=True)
            try:
                created, reused, refreshed = await self.guide.cog.sync_application_icons()
            except RaidInputError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            await self.guide.refresh_message()
            await interaction.followup.send(
                f"EQ2 icons are ready: **{created} created**, **{reused} reused**, and "
                f"**{refreshed} active raid message(s) refreshed**.",
                ephemeral=True,
            )


class GettingStartedView(discord.ui.View):
    """Skippable setup and feature walkthrough for a single administrator."""

    LAST_STEP = 5

    def __init__(self, cog: "ReverbRaid", guild_id: int, owner_id: int, *, step: int = 0):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.step = max(0, min(self.LAST_STEP, step))
        self.message: Optional[discord.Message] = None
        self.rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await ephemeral_error(
                interaction, "Open your own Getting Started guide to use these controls."
            )
            return False
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not permissions.manage_guild:
            await ephemeral_error(interaction, "You need **Manage Server** to change raid settings.")
            return False
        return True

    async def refresh_message(self) -> None:
        if self.message is not None:
            self.rebuild_items()
            await self.message.edit(embed=await self.build_embed(), view=self)

    def rebuild_items(self) -> None:
        self.clear_items()
        if self.step == 1:
            self.add_item(GettingStartedChannelSelect(self))
        elif self.step == 2:
            self.add_item(GettingStartedOrganizerRoleSelect(self))
            self.add_item(GettingStartedMentionRoleSelect(self))
        elif self.step == 3:
            self.add_item(
                GettingStartedButton(
                    self,
                    "timezone",
                    "Timezone",
                    style=discord.ButtonStyle.primary,
                    emoji="🌐",
                    row=0,
                )
            )
            self.add_item(
                GettingStartedButton(self, "duration", "Duration", emoji="🕒", row=0)
            )
            self.add_item(
                GettingStartedButton(self, "reminder", "Reminder", emoji="⏰", row=0)
            )
            self.add_item(
                GettingStartedButton(
                    self, "description", "Default description", emoji="📝", row=0
                )
            )
        elif self.step == 4:
            self.add_item(
                GettingStartedButton(
                    self,
                    "sync_icons",
                    "Sync EQ2 icons",
                    style=discord.ButtonStyle.success,
                    emoji="🎨",
                    row=0,
                )
            )

        if self.step > 0:
            self.add_item(GettingStartedButton(self, "back", "Back", emoji="⬅️"))
        if self.step < self.LAST_STEP:
            label = "Begin" if self.step == 0 else "Skip / Next"
            self.add_item(
                GettingStartedButton(
                    self,
                    "next",
                    label,
                    style=discord.ButtonStyle.primary,
                    emoji="➡️",
                )
            )
        self.add_item(GettingStartedButton(self, "setup", "Full setup", emoji="⚙️"))
        if self.step == self.LAST_STEP:
            self.add_item(
                GettingStartedButton(
                    self,
                    "finish",
                    "Finish",
                    style=discord.ButtonStyle.success,
                    emoji="✅",
                )
            )

    async def build_embed(self) -> discord.Embed:
        settings = await self.cog.get_guild_settings(self.guild_id)
        channel_id = settings.get("default_channel_id")
        role_ids = settings.get("organizer_role_ids", [])
        mention_role_id = settings.get("mention_role_id")
        icon_count = len(self.cog._archetype_icon_emojis) + len(self.cog._class_icon_emojis)

        pages = (
            (
                "👋 Getting started with Reverb Raid",
                "This walkthrough explains the setup and the complete raid flow. Nothing is "
                "required: use **Skip / Next** on any setting you do not want to change.",
                (
                    (
                        "What you will configure",
                        "Raid channel, organizer access, defaults, reminders, and EQ2 icons.",
                    ),
                    (
                        "What you will learn",
                        "Creating raids, signing up, Bench/Absent behavior, reminders, "
                        "history, CSV exports, and organizer tools.",
                    ),
                ),
            ),
            (
                "📣 Step 1 — Raid channel",
                "Choose where new signup messages should normally be posted. If you skip this, "
                "the creation wizard uses the channel where the command was started.",
                (("Current default", f"<#{channel_id}>" if channel_id else "*Command channel*"),),
            ),
            (
                "🛡️ Step 2 — Organizers and announcements",
                "Organizer roles may create and manage raids. Manage Server users always retain "
                "access. The optional announcement role is mentioned when a raid is posted.",
                (
                    ("Organizer roles", ", ".join(f"<@&{role_id}>" for role_id in role_ids) or "*Manage Server only*"),
                    ("Announcement role", f"<@&{mention_role_id}>" if mention_role_id else "*None*"),
                ),
            ),
            (
                "🗓️ Step 3 — Creation defaults",
                "These values pre-fill the private `/create` wizard. Change any of them below, "
                "or skip the entire page.",
                (
                    ("Timezone", f"`{settings['timezone']}`"),
                    ("Duration", f"{settings['default_duration_minutes']} minutes"),
                    (
                        "Reminder",
                        (
                            f"{format_minutes(settings['default_reminder_minutes'])} before start"
                            if settings["default_reminder_minutes"]
                            else "Off"
                        ),
                    ),
                    ("Description", trim_text(settings["default_description"], 500) or "*None*"),
                ),
            ),
            (
                "🎨 Step 4 — EQ2 class icons",
                "The bundled pack provides an icon for every class and archetype without using "
                "server emoji slots. Only the Red bot owner can perform the one-time sync.",
                (("Icon pack", f"**{icon_count}/30 ready**" if icon_count else "*Not synced*"),),
            ),
            (
                "⚔️ Step 5 — How raids work",
                "You are ready. Organizers run `/create` or `/raid create` and complete the "
                "private DM prompts. The bot posts a persistent signup panel in the chosen channel.",
                (
                    (
                        "Member controls",
                        "Choose any EQ2 class, then set Attending, Tentative, Late, Bench, "
                        "or Absent. Class and availability remain independent. Members can "
                        "also add a note or withdraw.",
                    ),
                    (
                        "Organizer controls",
                        "Edit details, close or reopen signups, export CSV, archive the raid, "
                        "adjust its reminder, or permanently delete its stored data.",
                    ),
                    (
                        "Reminders",
                        "New raids inherit the server's reminder setting. The channel reminder "
                        "pings Attending, Tentative, and Late members, but never Bench or "
                        "Absent members. Organizers can override each event from `/raid manage`.",
                    ),
                    (
                        "History and useful commands",
                        "`/raid list` shows upcoming raids. `/raid show` displays a roster. "
                        "`/raid manage` opens organizer controls. `/raid history` browses "
                        "retained raids or one member's entries, and `/raid exporthistory` "
                        "downloads all historic signups as CSV.",
                    ),
                ),
            ),
        )
        title, description, fields = pages[self.step]
        embed = discord.Embed(title=title, description=description, color=0x6D4AFF)
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text=f"Step {self.step + 1} of {self.LAST_STEP + 1} • Changes save immediately")
        return embed


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

    @discord.ui.button(label="Reminder", style=discord.ButtonStyle.secondary, emoji="⏰", row=3)
    async def reminder(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        settings = await self.cog.get_guild_settings(interaction.guild_id)
        await interaction.response.send_modal(
            ReminderModal(self, settings["default_reminder_minutes"])
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
        label="Getting started",
        style=discord.ButtonStyle.primary,
        emoji="📖",
        row=4,
    )
    async def getting_started(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        guide = GettingStartedView(self.cog, self.guild_id, self.owner_id)
        guide.message = interaction.message
        self.stop()
        await interaction.response.edit_message(embed=await guide.build_embed(), view=guide)

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

    @discord.ui.button(
        label="Raid history",
        style=discord.ButtonStyle.secondary,
        emoji="📚",
        row=4,
    )
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await self.cog.build_history_embed(interaction.guild),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Export history",
        style=discord.ButtonStyle.secondary,
        emoji="📄",
        row=4,
    )
    async def export_history(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        file = await self.cog.export_history(interaction.guild_id)
        await interaction.followup.send(file=file, ephemeral=True)


def disable_view(view: discord.ui.View) -> None:
    """Disable every component in a view before an archival edit."""
    for item in view.children:
        if hasattr(item, "disabled"):
            item.disabled = True
