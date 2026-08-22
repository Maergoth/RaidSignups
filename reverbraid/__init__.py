"""Reverb Raid Sign-up Helper entrypoint."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redbot.core.bot import Red

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs, display names, raid signup classes, availability "
    "statuses, and optional signup notes. Archived rosters are retained until an organizer "
    "permanently deletes the event or the data is deleted through Red's data-deletion system."
)


async def setup(bot: "Red") -> None:
    from .reverbraid import ReverbRaid

    await bot.add_cog(ReverbRaid(bot))
