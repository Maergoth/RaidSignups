"""Static EverQuest II raid data and display constants."""

from __future__ import annotations

ARCHETYPES = {
    "fighter": (
        "Guardian",
        "Berserker",
        "Paladin",
        "Shadowknight",
        "Monk",
        "Bruiser",
    ),
    "priest": (
        "Templar",
        "Inquisitor",
        "Warden",
        "Fury",
        "Mystic",
        "Defiler",
        "Channeler",
    ),
    "mage": (
        "Wizard",
        "Warlock",
        "Illusionist",
        "Coercer",
        "Conjuror",
        "Necromancer",
    ),
    "scout": (
        "Brigand",
        "Swashbuckler",
        "Troubador",
        "Dirge",
        "Ranger",
        "Assassin",
        "Beastlord",
    ),
}

ARCHETYPE_LABELS = {
    "fighter": "Fighter",
    "priest": "Priest",
    "mage": "Mage",
    "scout": "Scout",
}

ARCHETYPE_EMOJIS = {
    "fighter": "⛨️",
    "priest": "✨",
    "mage": "🔮",
    "scout": "🗡️",
}

STATUS_LABELS = {
    "attending": "Attending",
    "tentative": "Tentative",
    "late": "Late",
    "absent": "Absent",
}

STATUS_EMOJIS = {
    "attending": "✅",
    "tentative": "⚖️",
    "late": "🕒",
    "absent": "🚫",
}

CLASS_TO_ARCHETYPE = {
    class_name: archetype
    for archetype, class_names in ARCHETYPES.items()
    for class_name in class_names
}

DEFAULT_DESCRIPTION = (
    "The target will be decided once we see the roster. Sign up below with your class "
    "and update your status if you will be tentative, late, or absent."
)

DEFAULT_GUILD = {
    "timezone": "America/New_York",
    "default_channel_id": None,
    "default_description": DEFAULT_DESCRIPTION,
    "default_duration_minutes": 180,
    "organizer_role_ids": [],
    "mention_role_id": None,
    "archetype_emojis": {},
    "events": {},
}

EMBED_COLOR = 0x6D4AFF
CONFIG_IDENTIFIER = 84739251020260822
MAX_NOTE_LENGTH = 120
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 1500
