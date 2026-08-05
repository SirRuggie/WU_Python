"""Single structured catalog for the Components V2 help command.

Keep public command paths here in the same change that adds, renames, or removes
a command. The renderer deliberately stays separate so this inventory can be
tested without constructing Discord components.
"""


HELP_CATEGORIES = {
    "start": {
        "name": "Start Here",
        "emoji": "🧭",
        "description": "Everyday commands and self-service tools",
        "commands": [
            ("/help", "Open this command guide."),
            ("/todo", "Show what your linked Clash accounts still need to do."),
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
            ("/role add", "Add one server role to a member. Recruiter/Admin only."),
            ("/role remove", "Remove one server role from a member. Recruiter/Admin only."),
            ("/role manage", "Open bulk role management for a member. Recruiter/Admin only."),
            ("/recruit questions", "Send the recruitment questionnaire to a recruit."),
            ("/recruit dashboard", "Open the complete new-member onboarding dashboard."),
            ("/setup recruit-aboutus", "Post the family overview and onboarding flow."),
            ("/setup recruit-familyparticulars", "Post family particulars and war rules."),
            ("/setup recruit-strikesystem", "Post the strike-system rules."),
        ],
    },
    "clan_fwa": {
        "name": "Clans & FWA",
        "emoji": "⚔️",
        "description": "Clan information, FWA tools, bases, and LazyCWL",
        "commands": [
            ("/clan dashboard", "Open clan administration and FWA data tools."),
            ("/clan info", "View information about every family clan."),
            ("/clan list", "Pick a clan to view or assign to a recruit."),
            ("/clan upload-images", "Upload a clan logo and banner."),
            ("/fwa bases", "Select and display an FWA base layout."),
            ("/fwa chocolate", "Look up a player or clan on FWA Chocolate."),
            ("/fwa links", "Open FWA verification and war-weight links."),
            ("/fwa new-th-upgrade", "Display FWA Town Hall upgrade notes."),
            ("/fwa points", "Show the latest stored FWA points verdicts."),
            ("/fwa upload-images", "Upload FWA war and active base images."),
            ("/fwa war-plans", "Generate a war plan for win, loss, blacklist, or mismatch."),
            ("/fwa weight", "Calculate war weight from a storage value."),
            ("/fwa lazycwl-snapshot", "Snapshot FWA rosters for LazyCWL tracking."),
            ("/fwa lazycwl-ping", "Ping missing players to return for FWA sync."),
            ("/fwa lazycwl-status", "List active LazyCWL snapshots."),
            ("/fwa lazycwl-roster", "View a LazyCWL snapshot roster."),
            ("/fwa lazycwl-reset", "Deactivate completed LazyCWL snapshots."),
            ("/fwa lazycwl-autopings-start", "Start periodic missing-player pings."),
            ("/fwa lazycwl-autopings-stop", "Stop periodic pings for a snapshot."),
            ("/fwa lazycwl-autopings-status", "Show active auto-ping schedules."),
            ("/fwa lazycwl-remove-player", "Remove players from snapshot tracking."),
        ],
    },
    "tickets": {
        "name": "Tickets",
        "emoji": "🎫",
        "description": "Recruitment tickets and maintenance",
        "commands": [
            ("/ticket claim", "Claim the current ticket. Recruiter only."),
            ("/ticket release", "Release your claim on the current ticket."),
            ("/ticket approve", "Approve the current ticket. Recruiter/Admin only."),
            ("/ticket deny", "Deny the current ticket. Recruiter/Admin only."),
            ("/ticket list", "List all currently open tickets. Recruiter only."),
            ("/ticket dashboard", "Open the ticket management dashboard. Recruiter only."),
            ("/ticket setup", "Post the ticket entry panel. Admin only."),
            ("/ticket config", "Configure ticket roles and categories. Admin only."),
            ("/ticket change-category", "Change the category used for new tickets. Admin only."),
            ("/ticket reset-counter", "Reset Main/FWA ticket counters. Admin only."),
            ("/ticket diagnostics", "Compare ticket channels and stored records. Admin only."),
            ("/ticket cleanup-ghosts", "Close records whose Discord channel is gone. Admin only."),
            ("/ticket fix-mismatched", "Repair status/channel-name mismatches. Admin only."),
            ("/ticket migrate-store", "Copy legacy ticket rows to the tickets collection. Admin only."),
        ],
    },
    "cwl": {
        "name": "CWL & Reminders",
        "emoji": "📅",
        "description": "CWL announcements, schedules, and bonuses",
        "commands": [
            ("/cwl-announcement", "Post a CWL announcement."),
            ("/lazycwl-bonuses", "Randomly select LazyCWL bonus recipients."),
            ("/lazyprep", "Post LazyCWL preparation announcements."),
            ("/cwl-reminder schedule", "Schedule the monthly CWL reminder."),
            ("/cwl-reminder status", "Show the active reminder schedule."),
            ("/cwl-reminder cancel", "Cancel the scheduled reminder."),
            ("/cwl-reminder test", "Send a test reminder."),
            ("/cwl-reminder add-followup", "Add or update a follow-up reminder."),
            ("/cwl-reminder remove-followup", "Remove a follow-up reminder."),
            ("/cwl-reminder list", "List every configured reminder."),
            ("/cwl-reminder test-all", "Test all reminders in sequence. Admin only."),
            ("/cwl-reminder send-now", "Send all reminders immediately. Admin only."),
        ],
    },
    "admin": {
        "name": "Admin Tools",
        "emoji": "🛠️",
        "description": "Bot operations, monitors, diagnostics, and privileged utilities",
        "commands": [
            ("/say", "Send a message as the bot. Restricted role only."),
            ("/steal", "Copy an emoji into the bot application."),
            ("/reboot", "Restart the bot process. Owner only."),
            ("/toggle-debug", "Toggle verbose BAND monitor logging. Admin only."),
            ("/test-band-api", "Test the BAND API connection. Admin only."),
            ("/test-war-sync", "Send a test war-sync notification. Admin only."),
            ("/fwasync enable", "Enable BAND iCal sync alerts. Admin only."),
            ("/fwasync disable", "Disable BAND iCal sync alerts. Admin only."),
            ("/fwasync status", "Show BAND sync configuration and state. Admin only."),
            ("/fwasync check", "Fetch feeds and report upcoming syncs without DMs. Admin only."),
            ("/fwasync preview", "Preview the next sync alert in your DMs. Admin only."),
            ("/fwasync set-recipients", "Replace sync-alert recipients. Admin only."),
            ("/fwasync set-offsets", "Replace sync-alert timing offsets. Admin only."),
            ("/fwapoints enable", "Enable the FWA points monitor. Admin only."),
            ("/fwapoints disable", "Disable the FWA points monitor. Admin only."),
            ("/fwapoints watch-add", "Add a clan to the points watch list. Admin only."),
            ("/fwapoints watch-remove", "Remove a clan from the watch list. Admin only."),
            ("/fwapoints status", "Show points-monitor status and records. Admin only."),
        ],
    },
}


def command_paths() -> set[str]:
    """Return every documented slash-command path."""
    return {
        command
        for category in HELP_CATEGORIES.values()
        for command, _description in category["commands"]
    }
