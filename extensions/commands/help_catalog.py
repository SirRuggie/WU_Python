"""Single structured catalog for the Components V2 help command.

Keep public command paths here in the same change that adds, renames, or removes
a command. The renderer deliberately stays separate so this inventory can be
tested without constructing Discord components.
"""

from utils.startup import RETIRED_EXTENSIONS


HELP_CATEGORIES = {
    "start": {
        "name": "Start Here",
        "emoji": "🧭",
        "description": "Everyday commands and self-service tools",
        "commands": [
            ("/help", "Open this command guide."),
            ("/ping", "Check whether the bot is online and responding."),
            ("/accounts", "Show every Clash account linked to your Discord."),
            ("/cards", "Update your card collection and find family trade matches."),
            ("/todo", "Show what your linked Clash accounts still need to do."),
            ("/clear-my-dms", "Delete this bot's past messages from your private DM."),
            ("/family-links", "Manage your own family roles and open clan links."),
            ("/slap", "Send a playful slap GIF to another member."),
        ],
        "notes": [
            "Right-click a user → **Apps → Get User ID** to copy their Discord ID.",
            "Right-click a message → **Apps → Get Message ID** to copy its ID.",
        ],
    },
    "roles": {
        "name": "Roles & Recruits",
        "emoji": "👥",
        "description": "Member roles and recruit onboarding",
        "commands": [
            ("/recruit questions", "Send the recruitment questionnaire to a recruit."),
            ("/warrior setup", "Open the new-member onboarding dashboard."),
        ],
    },
    "manage": {
        "name": "Management", "emoji": "🛡️", "description": "Private dashboards for server staff",
        "commands": [
            ("/manage", "Open management home or choose Server, Roles, Recruit Gauntlet, FWA (bases, war messages, blacklist, points, sync reminders), Recruitment Questions, CWL, or CWL Rosters."),
        ],
    },
    "clan_fwa": {
        "name": "Clans & FWA",
        "emoji": "⚔️",
        "description": "Clan information, FWA tools, bases, and LazyCWL",
        "commands": [
            ("/fwa bases", "Select and display an FWA base layout."),
            ("/fwa chocolate", "Look up a player or clan on FWA Chocolate."),
            ("/fwa links", "Open FWA verification and war-weight links."),
            ("/fwa new-th-upgrade", "Display FWA Town Hall upgrade notes."),
            ("/fwa war-plans", "Generate a war plan for win, loss, blacklist, or mismatch."),
            ("/fwa weight", "Calculate war weight from a storage value."),
        ],
    },
    "tickets_v2": {
        "name": "Tickets",
        "emoji": "🧪",
        "description": "Recruitment tickets, console, history, flags, and administration",
        "commands": [
            ("/tickets approve", "Approve the current thread ticket. Recruiter/Admin only."),
            ("/tickets deny", "Deny the current thread ticket. Recruiter/Admin only."),
            ("/tickets find", "Search permanent thread-ticket history. Recruiter/Admin only."),
            ("/tickets history", "Open one member's ticket history. Recruiter/Admin only."),
            ("/tickets flags", "View active applicant flags. Recruiter/Admin only."),
            ("/tickets flag-add", "Add or update an applicant flag. Recruiter/Admin only."),
            ("/tickets flag-remove", "Deactivate an applicant flag. Recruiter/Admin only."),
            ("/tickets testing", "Open isolated test tickets. Admins manage temporary tester access."),
            ("/tickets setup", "Post and bind the restricted pilot panel. Admin only."),
            ("/tickets configure-threads", "Validate candidate/staff thread parents. Admin only."),
            ("/tickets thread-config", "Revalidate thread configuration. Admin only."),
            ("/tickets console", "Post or repair the recruiter console. Admin only."),
            ("/tickets config", "Inspect thread-ticket settings. Admin only."),
            ("/tickets pilot-user", "Manage pilot user access. Admin only."),
            ("/tickets pilot-role", "Manage pilot role access. Admin only."),
            ("/tickets rollout-status", "Show phase, bindings, and drain blockers. Admin only."),
            ("/tickets rollout-prepare", "Validate and stage the pilot. Admin only."),
            ("/tickets rollout-pilot", "Enable allowlisted pilot intake. Admin only."),
            ("/tickets rollout-promote", "Promote thread intake publicly. Admin only."),
            ("/tickets rollout-drain", "Verify legacy drain and enter thread-only. Admin only."),
        ],
    },
    "cwl": {
        "name": "CWL & Reminders",
        "emoji": "📅",
        "description": "One CWL announcement dashboard plus the separate bonus lottery",
        "commands": [
            ("/lazycwl-bonuses", "Randomly select LazyCWL bonus recipients."),
        ],
    },
    "admin": {
        "name": "Admin Tools",
        "emoji": "🛠️",
        "description": "Bot operations, monitors, diagnostics, and privileged utilities",
        "commands": [
            ("/poll create", "Create a timed poll with named votes. Admin only."),
            ("/poll view", "View recent polls or named voters for one poll. Admin only."),
            ("/poll active", "List polls that are currently open. Admin only."),
            ("/say", "Send a message as the bot. Restricted role only."),
            ("/steal", "Copy an emoji into the bot application."),
            ("/reboot", "Restart the bot process. Owner only."),
        ],
    },
}

# The /cards command is retired along with the Clash of Cards event (see
# utils.startup.RETIRED_EXTENSIONS). Hide its row while the extension is
# switched off; the tuple stays above so re-enabling is a one-line revert
# in startup.py.
if "extensions.commands.cards" in RETIRED_EXTENSIONS:
    HELP_CATEGORIES["start"]["commands"] = [
        row for row in HELP_CATEGORIES["start"]["commands"] if row[0] != "/cards"
    ]


def command_paths() -> set[str]:
    """Return every documented slash-command path."""
    return {
        command
        for category in HELP_CATEGORIES.values()
        for command, _description in category["commands"]
    }
