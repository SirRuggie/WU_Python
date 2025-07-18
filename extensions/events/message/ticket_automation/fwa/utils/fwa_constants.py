# extensions/events/message/ticket_automation/fwa/utils/fwa_constants.py
"""
Constants specific to FWA ticket automation.
"""

# Ticket patterns
FWA_TICKET_PATTERN = "𝔽𝕎𝔸"  # Production FWA pattern (disabled initially)
FWA_TEST_PATTERN = "𝕋-𝔽𝕎𝔸"  # Test pattern for development

# FWA flow steps - Updated to include questionnaire steps
FWA_STEPS = [
    "war_weight",
    "account_collection",
    "interview_selection",
    "fwa_explanation",
    "lazy_cwl",
    "agreement",
    "discord_skills",
    "age_bracket",
    "timezone",
    "completion"
]

# Expected text responses (case-insensitive)
EXPECTED_RESPONSES = {
    "fwa_explanation": "understood",
    "lazy_cwl": "understood",
    "agreement": "i agree"
}

# Timeout settings
FWA_TIMEOUT_SECONDS = 300  # 5 minutes for responses
FWA_REMINDER_TIMEOUT = 120  # 2 minutes before reminder

# FWA-specific settings
FWA_BASE_REQUIRED = True
FWA_HEROES_CAN_UPGRADE = True
FWA_MINIMUM_TOWNHALL = 9

# Chocolate clash base URL
CHOCOLATE_BASE_URL = "https://cc.fwafarm.com/cc_n/"