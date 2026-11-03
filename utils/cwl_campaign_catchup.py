"""Startup-only policy for persisted scheduled CWL jobs, without transport."""

from datetime import timedelta
import re

import pendulum

from utils import cwl_campaign as campaign


MAX_CATCHUP_AGE = timedelta(hours=6)
CATCHUP_JOB_KIND = "catchup"


def original_due(row):
    if row.get("job_kind") == CATCHUP_JOB_KIND:
        context = row.get("catchup")
        if (
            not isinstance(context, dict)
            or context.get("protocol") != 1
            or isinstance(context.get("protocol"), bool)
            or not context.get("original_due_at")
        ):
            raise ValueError("Original catch-up time is missing")
        value = context["original_due_at"]
    else:
        value = row.get("run_time")
    if not isinstance(value, str) or not re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", value):
        raise ValueError("Original scheduled time needs a timezone")
    return pendulum.parse(value)


def scheduled_candidate(row):
    """Retries, manual sends, ledger recovery and rosters retain their rules."""
    candidate = (
        row.get("kind") == "campaign"
        and row.get("job_kind", "scheduled") in {"scheduled", CATCHUP_JOB_KIND}
        and row.get("status", "scheduled") != "ledger_pending"
        and row.get("message_id") != "roster"
    )
    if not candidate:
        return False
    failures = row.get("failure_count", 0)
    if not isinstance(failures, int) or isinstance(failures, bool):
        raise ValueError("Invalid scheduled failure count")
    return failures == 0


def exclusion_reason(loaded, row, variant, generation, now):
    """Return a terminal reason, or None; equality at six hours is eligible."""
    due = original_due(row)
    timezone = loaded["campaign"].get("timezone", campaign.DEFAULT_TIMEZONE)
    current_cycle = campaign.cycle_key(pendulum.instance(now).in_timezone(timezone), timezone)
    if row.get("cycle") != current_cycle:
        return "Skipped: another month"
    if row.get("generation") != generation:
        return "Skipped: settings changed"
    if not loaded.get("activated"):
        return "Skipped: automation is off"
    if loaded["campaign"].get("paused"):
        return "Skipped: paused"
    message = loaded["campaign"].get("messages", {}).get(row.get("message_id"))
    item = (message or {}).get("variants", {}).get(variant)
    if not message or not message.get("enabled", True) or not item or not item.get("enabled", True):
        return "Skipped: message is off"
    if now - due > MAX_CATCHUP_AGE:
        return "Skipped: too late"
    message_id = str(row.get("message_id", ""))
    if (
        message_id == "signup" or message_id.startswith("reminder:")
    ) and now >= pendulum.parse(loaded["deadline"]):
        return "Skipped: signups closed"
    return None


def handled_occurrences(loaded, state):
    """Any receipt, including failure/uncertainty, excludes automatic catch-up."""
    return (
        set(loaded.get("sent_occurrences", ()))
        | set(loaded.get("skipped", ()))
        | set(state.get("reported", ()))
        | {
            row["occurrence_id"]
            for row in loaded.get("deliveries", ())
            if row.get("occurrence_id")
        }
    )


def late_receipt(due, now):
    return {
        "late": True,
        "original_due_at": due.isoformat(),
        "late_by_seconds": max(0, int((now - due).total_seconds())),
    }
