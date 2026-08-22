"""Discord-independent parsing and roster helpers for Reverb Raid."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Tuple

from dateutil import parser, tz

from .constants import ARCHETYPES, CLASS_TO_ARCHETYPE, REMINDER_STATUSES, STATUS_LABELS


class RaidInputError(ValueError):
    """Raised when a raid wizard value cannot be safely interpreted."""


_RELATIVE_DAY = re.compile(r"^(today|tomorrow)\b", re.IGNORECASE)
_DURATION = re.compile(
    r"^\s*(?:(?P<hours>\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours))?"
    r"\s*(?:(?P<minutes>\d+)\s*(?:m|min|mins|minute|minutes))?\s*$",
    re.IGNORECASE,
)


def get_timezone(timezone_name: str):
    """Return a dateutil timezone, raising a user-facing error when invalid."""
    zone = tz.gettz(timezone_name)
    if zone is None:
        raise RaidInputError(
            f"Unknown timezone `{timezone_name}`. Use an IANA name such as "
            "`America/New_York`."
        )
    return zone


def parse_raid_datetime(
    value: str,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> datetime:
    """Parse a raid date/time and return an aware UTC datetime.

    Inputs without an explicit offset are interpreted in the configured guild
    timezone. ``today`` and ``tomorrow`` are supported in addition to the forms
    accepted by :mod:`dateutil.parser`.
    """
    value = value.strip()
    if not value:
        raise RaidInputError("A date and time are required.")

    zone = get_timezone(timezone_name)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)

    relative_match = _RELATIVE_DAY.match(value)
    relative_days = 0
    parse_value = value
    if relative_match:
        relative_days = 1 if relative_match.group(1).lower() == "tomorrow" else 0
        parse_value = value[relative_match.end() :].strip()
        if not parse_value:
            raise RaidInputError("Include a time, for example `tomorrow 8:00 PM`.")

    default = local_now.replace(hour=20, minute=0, second=0, microsecond=0)
    if relative_match:
        default += timedelta(days=relative_days)

    try:
        parsed = parser.parse(parse_value, default=default, fuzzy=False)
    except (ValueError, OverflowError) as exc:
        raise RaidInputError(
            "I could not read that date. Try `2026-08-28 8:00 PM`, "
            "`Friday 8 PM`, or `tomorrow 20:00`."
        ) from exc

    if relative_match:
        parsed = parsed.replace(
            year=default.year,
            month=default.month,
            day=default.day,
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    if not tz.datetime_exists(parsed):
        raise RaidInputError(
            "That local time does not exist because of a daylight-saving change. "
            "Choose another time."
        )
    if tz.datetime_ambiguous(parsed):
        raise RaidInputError(
            "That time occurs twice because of a daylight-saving change. Include "
            "an offset such as `-04:00` or `-05:00`."
        )

    result = parsed.astimezone(timezone.utc)
    if result <= current.astimezone(timezone.utc) + timedelta(minutes=1):
        raise RaidInputError("The raid time must be in the future.")
    return result


def parse_duration(value: str) -> int:
    """Parse a duration string into minutes (15 minutes through 24 hours)."""
    value = value.strip().lower()
    if value.isdigit():
        minutes = int(value)
    else:
        match = _DURATION.fullmatch(value)
        if not match or not any(match.groupdict().values()):
            raise RaidInputError("Use minutes or a duration such as `3h` or `2h 30m`.")
        hours = float(match.group("hours") or 0)
        minutes = round(hours * 60) + int(match.group("minutes") or 0)

    if minutes < 15 or minutes > 24 * 60:
        raise RaidInputError("Duration must be between 15 minutes and 24 hours.")
    return minutes


def parse_reminder_minutes(value: str) -> int:
    """Parse a reminder lead time, or return zero when reminders are disabled."""
    value = value.strip().lower()
    if value in {"off", "none", "disable", "disabled", "0"}:
        return 0

    if value.isdigit():
        minutes = int(value)
    else:
        match = _DURATION.fullmatch(value)
        if not match or not any(match.groupdict().values()):
            raise RaidInputError(
                "Use `off`, minutes, or a lead time such as `1h` or `2h 30m`."
            )
        hours = float(match.group("hours") or 0)
        minutes = round(hours * 60) + int(match.group("minutes") or 0)

    if minutes < 5 or minutes > 7 * 24 * 60:
        raise RaidInputError("Reminder lead time must be between 5 minutes and 7 days.")
    return minutes


def format_minutes(minutes: int) -> str:
    """Format a minute count as a concise human-readable duration."""
    minutes = max(0, int(minutes))
    if minutes == 0:
        return "Off"
    days, remainder = divmod(minutes, 24 * 60)
    hours, remaining_minutes = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if remaining_minutes:
        parts.append(
            f"{remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"
        )
    return " ".join(parts)


def select_historic_events(
    events: Mapping[str, Mapping[str, Any]],
    now_ts: int,
    *,
    member_id: str | None = None,
) -> List[Dict[str, Any]]:
    """Return archived or started events, newest first, optionally filtered by member."""
    selected: List[Dict[str, Any]] = []
    for event_id, raw_event in events.items():
        event = dict(raw_event)
        event.setdefault("id", str(event_id))
        if not event.get("archived") and int(event.get("start_ts") or 0) > now_ts:
            continue
        if member_id is not None and str(member_id) not in event.get("roster", {}):
            continue
        selected.append(event)
    selected.sort(key=lambda event: int(event.get("start_ts") or 0), reverse=True)
    return selected


def reminder_recipient_ids(roster: Mapping[str, Mapping[str, Any]]) -> List[int]:
    """Return valid user IDs whose current signup status should receive a reminder."""
    recipients = []
    for user_id, raw_signup in roster.items():
        if normalize_signup(raw_signup)["status"] not in REMINDER_STATUSES:
            continue
        try:
            recipients.append(int(user_id))
        except (TypeError, ValueError):
            continue
    return recipients


def normalize_signup(signup: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize persisted signup data from current or earlier cog versions."""
    class_name = str(signup.get("class_name") or "").strip()
    status = str(signup.get("status") or "attending").lower()
    if status not in STATUS_LABELS:
        status = "attending"
    archetype = CLASS_TO_ARCHETYPE.get(class_name)
    return {
        "class_name": class_name or None,
        "archetype": archetype,
        "status": status,
        "note": str(signup.get("note") or "").strip(),
        "display_name": str(signup.get("display_name") or "Unknown member"),
        "updated_at": int(signup.get("updated_at") or 0),
    }


def group_roster(
    roster: Mapping[str, Mapping[str, Any]],
) -> Tuple[
    Dict[str, List[Tuple[str, Dict[str, Any]]]],
    List[Tuple[str, Dict[str, Any]]],
    List[Tuple[str, Dict[str, Any]]],
]:
    """Group active signups by archetype and return bench/absence lists separately."""
    grouped: MutableMapping[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    bench: List[Tuple[str, Dict[str, Any]]] = []
    absent: List[Tuple[str, Dict[str, Any]]] = []

    for user_id, raw_signup in roster.items():
        signup = normalize_signup(raw_signup)
        item = (str(user_id), signup)
        if signup["status"] == "bench":
            bench.append(item)
        elif signup["status"] == "absent":
            absent.append(item)
        else:
            grouped[signup["archetype"] or "unassigned"].append(item)

    class_order = {
        class_name: index
        for archetype in ARCHETYPES.values()
        for index, class_name in enumerate(archetype)
    }

    def sort_key(item: Tuple[str, Dict[str, Any]]) -> Tuple[int, str]:
        signup = item[1]
        return (
            class_order.get(signup.get("class_name"), 999),
            signup.get("display_name", "").casefold(),
        )

    for values in grouped.values():
        values.sort(key=sort_key)
    bench.sort(key=lambda item: item[1].get("display_name", "").casefold())
    absent.sort(key=lambda item: item[1].get("display_name", "").casefold())
    return dict(grouped), bench, absent


def trim_text(value: str, limit: int) -> str:
    """Trim text without splitting the final display across Discord limits."""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def chunk_lines(lines: Iterable[str], limit: int = 1024) -> List[str]:
    """Pack lines into chunks that fit in a Discord embed field."""
    chunks: List[str] = []
    current = ""
    for line in lines:
        line = trim_text(line, limit)
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or ["—"]
