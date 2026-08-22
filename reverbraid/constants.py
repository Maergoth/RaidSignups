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
    "fighter": "🛡️",
    "priest": "✨",
    "mage": "🔮",
    "scout": "🗡️",
}

# Discord components only accept Unicode or Discord-managed emoji objects. These
# bundled images are uploaded once as application emojis by the bot owner, making
# them available in every server without consuming guild emoji slots.
ARCHETYPE_ICON_FILES = {
    "fighter": "Fighter_Icon.png",
    "priest": "Priest_Icon.png",
    "mage": "Mage_Icon.png",
    "scout": "Scout_Icon.png",
}

CLASS_ICON_FILES = {
    class_name: f"{class_name}_Icon.png"
    for class_names in ARCHETYPES.values()
    for class_name in class_names
}

ARCHETYPE_APPLICATION_EMOJI_NAMES = {
    archetype: f"eq2_{archetype}" for archetype in ARCHETYPES
}

CLASS_APPLICATION_EMOJI_NAMES = {
    class_name: f"eq2_{class_name.casefold()}" for class_name in CLASS_ICON_FILES
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
