from datetime import datetime, timezone
import unittest

from reverbraid.models import (
    RaidInputError,
    chunk_lines,
    group_roster,
    parse_duration,
    parse_raid_datetime,
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
        grouped, absent = group_roster(
            {
                "1": {"class_name": "Paladin", "status": "late", "display_name": "A"},
                "2": {"class_name": "Wizard", "status": "attending", "display_name": "B"},
                "3": {"class_name": "Defiler", "status": "absent", "display_name": "C"},
                "4": {"status": "tentative", "display_name": "D"},
            }
        )
        self.assertEqual(grouped["fighter"][0][0], "1")
        self.assertEqual(grouped["mage"][0][0], "2")
        self.assertEqual(grouped["unassigned"][0][0], "4")
        self.assertEqual(absent[0][0], "3")

    def test_chunk_lines_honors_limit(self):
        chunks = chunk_lines(["a" * 10, "b" * 10], limit=15)
        self.assertEqual(chunks, ["a" * 10, "b" * 10])


if __name__ == "__main__":
    unittest.main()
