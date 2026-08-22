from datetime import datetime, timezone
from pathlib import Path
import unittest

from reverbraid.constants import (
    ARCHETYPE_APPLICATION_EMOJI_NAMES,
    ARCHETYPE_EMOJIS,
    ARCHETYPE_ICON_FILES,
    ARCHETYPES,
    CLASS_APPLICATION_EMOJI_NAMES,
    CLASS_ICON_FILES,
)
from reverbraid.models import (
    RaidInputError,
    chunk_lines,
    format_minutes,
    group_roster,
    parse_duration,
    parse_raid_datetime,
    parse_reminder_minutes,
    reminder_recipient_ids,
    select_historic_events,
)


class DurationTests(unittest.TestCase):
    def test_plain_minutes(self):
        self.assertEqual(parse_duration("180"), 180)

    def test_compound_duration(self):
        self.assertEqual(parse_duration("2h 30m"), 150)

    def test_decimal_hours(self):
        self.assertEqual(parse_duration("1.5 hours"), 90)

    def test_out_of_range(self):
        with self.assertRaises(RaidInputError):
            parse_duration("10m")


class ReminderTests(unittest.TestCase):
    def test_reminder_duration_and_off(self):
        self.assertEqual(parse_reminder_minutes("1h 30m"), 90)
        self.assertEqual(parse_reminder_minutes("off"), 0)

    def test_reminder_range(self):
        with self.assertRaises(RaidInputError):
            parse_reminder_minutes("4m")
        with self.assertRaises(RaidInputError):
            parse_reminder_minutes("8 days")

    def test_format_minutes(self):
        self.assertEqual(format_minutes(0), "Off")
        self.assertEqual(format_minutes(60), "1 hour")
        self.assertEqual(format_minutes(1500), "1 day 1 hour")

    def test_reminder_recipients_exclude_bench_and_absent(self):
        roster = {
            "1": {"status": "attending"},
            "2": {"status": "tentative"},
            "3": {"status": "late"},
            "4": {"status": "bench"},
            "5": {"status": "absent"},
            "not-a-user": {"status": "attending"},
        }
        self.assertEqual(reminder_recipient_ids(roster), [1, 2, 3])


class HistoryTests(unittest.TestCase):
    def test_historic_events_include_started_and_archived(self):
        events = {
            "past": {"id": "past", "start_ts": 100, "roster": {"1": {}}},
            "future": {"id": "future", "start_ts": 300, "roster": {"1": {}}},
            "cancelled": {
                "id": "cancelled",
                "start_ts": 400,
                "archived": True,
                "roster": {"2": {}},
            },
        }
        self.assertEqual(
            [event["id"] for event in select_historic_events(events, 200)],
            ["cancelled", "past"],
        )

    def test_historic_events_filter_member(self):
        events = {
            "one": {"id": "one", "start_ts": 100, "roster": {"1": {}}},
            "two": {"id": "two", "start_ts": 90, "roster": {"2": {}}},
        }
        self.assertEqual(
            [
                event["id"]
                for event in select_historic_events(events, 200, member_id="2")
            ],
            ["two"],
        )


class DateTimeTests(unittest.TestCase):
    NOW = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)

    def test_local_time_converts_to_utc(self):
        result = parse_raid_datetime(
            "2026-08-28 8:00 PM",
            "America/New_York",
            now=self.NOW,
        )
        self.assertEqual(result, datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))

    def test_tomorrow(self):
        result = parse_raid_datetime(
            "tomorrow 8 PM",
            "America/New_York",
            now=self.NOW,
        )
        self.assertEqual(result, datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc))

    def test_explicit_offset(self):
        result = parse_raid_datetime(
            "2026-08-28 20:00 -04:00",
            "America/Los_Angeles",
            now=self.NOW,
        )
        self.assertEqual(result, datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc))

    def test_rejects_past(self):
        with self.assertRaises(RaidInputError):
            parse_raid_datetime("2020-01-01 8 PM", "America/New_York", now=self.NOW)

    def test_rejects_nonexistent_dst_time(self):
        with self.assertRaisesRegex(RaidInputError, "does not exist"):
            parse_raid_datetime(
                "2027-03-14 2:30 AM",
                "America/New_York",
                now=self.NOW,
            )


class RosterTests(unittest.TestCase):
    def test_groups_and_normalizes_roster(self):
        grouped, bench, absent = group_roster(
            {
                "1": {"class_name": "Paladin", "status": "late", "display_name": "A"},
                "2": {"class_name": "Wizard", "status": "attending", "display_name": "B"},
                "3": {"class_name": "Defiler", "status": "absent", "display_name": "C"},
                "4": {"status": "tentative", "display_name": "D"},
                "5": {"class_name": "Ranger", "status": "bench", "display_name": "E"},
                "6": {"status": "bench", "display_name": "F"},
            }
        )
        self.assertEqual(grouped["fighter"][0][0], "1")
        self.assertEqual(grouped["mage"][0][0], "2")
        self.assertEqual(grouped["unassigned"][0][0], "4")
        self.assertEqual([item[0] for item in bench], ["5", "6"])
        self.assertNotIn("5", [item[0] for item in grouped.get("scout", [])])
        self.assertEqual(absent[0][0], "3")

    def test_chunk_lines_honors_limit(self):
        chunks = chunk_lines(["a" * 10, "b" * 10], limit=15)
        self.assertEqual(chunks, ["a" * 10, "b" * 10])


class ComponentEmojiTests(unittest.TestCase):
    def test_default_component_emojis_are_discord_safe(self):
        self.assertEqual(
            ARCHETYPE_EMOJIS,
            {
                "fighter": "🛡️",
                "priest": "✨",
                "mage": "🔮",
                "scout": "🗡️",
            },
        )

    def test_bundled_icon_pack_is_complete_and_discord_sized(self):
        class_names = {
            class_name for class_names in ARCHETYPES.values() for class_name in class_names
        }
        self.assertEqual(set(CLASS_ICON_FILES), class_names)
        self.assertEqual(set(CLASS_APPLICATION_EMOJI_NAMES), class_names)
        self.assertEqual(set(ARCHETYPE_ICON_FILES), set(ARCHETYPES))
        self.assertEqual(set(ARCHETYPE_APPLICATION_EMOJI_NAMES), set(ARCHETYPES))

        icon_dir = Path(__file__).parents[1] / "reverbraid" / "assets" / "icons"
        filenames = set(ARCHETYPE_ICON_FILES.values()) | set(CLASS_ICON_FILES.values())
        self.assertEqual(len(filenames), 30)
        for filename in filenames:
            path = icon_dir / filename
            self.assertTrue(path.is_file(), filename)
            self.assertLessEqual(path.stat().st_size, 256 * 1024, filename)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n", filename)

    def test_application_emoji_names_are_unique_and_valid(self):
        names = [
            *ARCHETYPE_APPLICATION_EMOJI_NAMES.values(),
            *CLASS_APPLICATION_EMOJI_NAMES.values(),
        ]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertGreaterEqual(len(name), 2)
            self.assertLessEqual(len(name), 32)
            self.assertTrue(name.replace("_", "").isalnum(), name)


if __name__ == "__main__":
    unittest.main()
