"""Concise, concrete review of a CWL draft before activating its changes."""
import pendulum

from utils import cwl_campaign


def change_summary(before_campaign, after_campaign, cycle):
    lines = []
    if before_campaign.get("timezone") != after_campaign.get("timezone"):
        lines.append(f"• Timezone: **{after_campaign.get('timezone')}**")
    if before_campaign.get("signup_deadline") != after_campaign.get("signup_deadline"):
        close = cwl_campaign.signup_deadline(after_campaign, cycle)
        lines.append(f"• Signup deadline: <t:{int(close.timestamp())}:F>")
    if bool(before_campaign.get("paused")) != bool(after_campaign.get("paused")):
        lines.append("• Campaign will be **paused**." if after_campaign.get("paused") else "• Campaign will be **active**.")
    next_times = {}
    for item in cwl_campaign.resolve_schedule(after_campaign, cycle):
        next_times.setdefault(item["message_id"], item.get("run_at"))
    previous_times = {}
    for item in cwl_campaign.resolve_schedule(before_campaign, cycle):
        previous_times.setdefault(item["message_id"], item.get("run_at"))
    before_messages = before_campaign.get("messages", {})
    after_messages = after_campaign.get("messages", {})
    for key, message in after_messages.items():
        old = before_messages.get(key)
        label = str(message.get("label") or key)[:80]
        if old is None:
            lines.append(f"• Added **{label}**.")
            old = {}
        elif old.get("label") != message.get("label"):
            lines.append(f"• Renamed **{str(old.get('label') or key)[:80]}** to **{label}**.")
        if old.get("schedule") != message.get("schedule") or previous_times.get(key) != next_times.get(key):
            at = next_times.get(key)
            timing = f"<t:{int(pendulum.parse(at).timestamp())}:F>" if at else "manual delivery"
            lines.append(f"• **{label}** timing: {timing}.")
        for audience, variant in message.get("variants", {}).items():
            previous = old.get("variants", {}).get(audience, {})
            changes = []
            if any(previous.get(field) != variant.get(field) for field in ("title", "body")):
                changes.append("text")
            if previous.get("media_url") != variant.get("media_url"):
                changes.append("artwork")
            if previous.get("buttons") != variant.get("buttons"):
                changes.append("links")
            if previous.get("destination_channel_id") != variant.get("destination_channel_id"):
                changes.append(f"channel → <#{variant.get('destination_channel_id')}>")
            if previous.get("role_ids", []) != variant.get("role_ids", []):
                roles = " ".join(f"<@&{role}>" for role in variant.get("role_ids", [])) or "none"
                changes.append(f"pings → {roles}")
            if previous.get("enabled", True) != variant.get("enabled", True):
                changes.append("enabled" if variant.get("enabled", True) else "disabled")
            if changes:
                lines.append(f"• **{label} · {audience.title()}**: {', '.join(changes)}.")
    for key, old in before_messages.items():
        if key not in after_messages:
            lines.append(f"• Removed **{str(old.get('label') or key)[:80]}**.")
    if not lines:
        return "No content or timing changes."
    kept, size = [], 0
    for line in lines:
        if size + len(line) > 2600:
            kept.append(f"• Plus {len(lines) - len(kept)} further changes. Review the message previews before applying.")
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept)
