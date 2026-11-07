"""Public dashboard destinations shared by bot messages and HTTP routing."""

DASHBOARD_ORIGIN = "https://dash.warriorsunited.cc"
LEGACY_DASHBOARD_HOST = "cwl.ruggie.zone"
SIGNUP_URL = DASHBOARD_ORIGIN + "/signup"
ASSIGNMENTS_URL = DASHBOARD_ORIGIN + "/assignments"
TASKS_URL = DASHBOARD_ORIGIN + "/tasks"
WARS_URL = DASHBOARD_ORIGIN + "/wars"
LEGACY_DASHBOARD_ORIGIN = "https://" + LEGACY_DASHBOARD_HOST
CLANS_URL = DASHBOARD_ORIGIN + "/clans"


def member_history_url(user_id) -> str | None:
    """Dashboard moderation history page for one member; None without a base."""
    if not DASHBOARD_ORIGIN:
        return None
    return f"{DASHBOARD_ORIGIN}/server/moderation/member/{user_id}"
