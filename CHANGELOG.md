# Changelog

## 1.1.1 - 2026-08-22

- Added a Bench availability status for members who can be contacted if needed.
- Added a separate Bench roster section that does not count members in active class columns.
- Allowed Bench selection without a class, matching Absent behavior.
- Kept class and availability independent, including when Bench or Absent is selected first.

## 1.1.0 - 2026-08-22

- Bundled authentic artwork for all 26 EverQuest II classes and all four archetypes.
- Added owner-only application-emoji syncing through `/raid setup` and `/raid syncicons`.
- Added class-specific icons to class selectors and live roster entries.
- Added archetype artwork to signup buttons and roster headings without consuming guild emoji slots.
- Added icon completeness, file-size, format, and emoji-name regression tests.

## 1.0.2 - 2026-08-22

- Replaced the unsupported Fighter glyph with Discord's valid shield emoji.
- Added a regression test for the default component emoji set.

## 1.0.1 - 2026-08-22

- Corrected the case-sensitive Red slash-enablement command to use `reverbraid`.

## 1.0.0 - 2026-08-22

- Added private DM raid creation wizard through `/create` and `/raid create`.
- Added all 26 EverQuest II classes grouped by Fighter, Priest, Mage, and Scout.
- Added attending, tentative, late, absent, and withdraw signup controls.
- Added optional per-player notes, including late-arrival details.
- Added restart-safe persistent Discord component views.
- Added native Discord configuration UI through `/raid setup`.
- Added organizer roles, configurable timezone, channel, description, and duration.
- Added configurable Fighter, Priest, Mage, and Scout custom Discord emojis.
- Added event edit, close/reopen, archive, and CSV roster export controls.
- Added Red end-user data export and deletion hooks.
