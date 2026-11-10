import hikari

# The production Warriors United Discord server. Features that migrate older
# globally keyed configuration use this as their guild boundary.
WARRIORS_UNITED_GUILD_ID = 644963518025826315
# Staff-only channel for the "New Warrior" join alert.
NEW_WARRIOR_ALERT_CHANNEL_ID = 967257753804505108

# Primary brand colors. Keep these equal to the dashboard tokens in
# web/cwl/src/tokens.css; tests/test_brand_colors.py checks that they match.
WU_GOLD = hikari.Color.from_hex_code("#F2B62A")  # --wu-accent
WU_GREEN = hikari.Color.from_hex_code("#43E58C")  # --wu-success-border
WU_RED = hikari.Color.from_hex_code("#E00010")  # --wu-brand-red

RED_ACCENT = hikari.Color.from_hex_code("#AA0000")
GOLD_ACCENT = hikari.Color.from_hex_code("FFD700")
BLUE_ACCENT = hikari.Color.from_hex_code("0066FF")
GREEN_ACCENT = hikari.Color.from_hex_code("00B237")
MAGENTA_ACCENT = hikari.Color.from_hex_code("FF00FF")
GOLDENROD_ACCENT = hikari.Color.from_hex_code("EEEEAA")

# Clan Information
CLAN_TYPES = ["Tactical", "Flexible Fun", "FWA", "CWL"]
TH_LEVELS = [str(i) for i in range(3, 19)]

# FWA War Plans
MAX_OPPONENT_NAME_LENGTH = 50


# FWA Images
FWA_WAR_BASE = {}

FWA_ACTIVE_WAR_BASE = {}
