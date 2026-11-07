import DiscordIdentity, { discordIdentityName } from "./DiscordIdentity";
import { eventTypes } from "./moderationSettingsModel";

export type MemberEvent = {
  id: string;
  user_id: string;
  event_type: string;
  display_name?: string | null;
  username?: string | null;
  avatar_url?: string | null;
  occurred_at: string;
  joined_at?: string | null;
  reason?: string | null;
  moderator_id?: string | null;
  moderator_name?: string | null;
  delivery_status?: string | null;
  details?: {
    roles?: unknown;
    changes?: unknown;
    name?: unknown;
    code?: unknown;
    duration_seconds?: unknown;
    until?: unknown;
  } | null;
};

const roleNameLimit = 5;

function roleSummary(item: MemberEvent) {
  if (item.event_type !== "roles_added" && item.event_type !== "roles_removed")
    return "";
  const roles = Array.isArray(item.details?.roles) ? item.details.roles : [];
  const names = roles.filter(
    (role): role is string => typeof role === "string" && role.trim() !== "",
  );
  if (!names.length) return "";
  const shown = names.slice(0, roleNameLimit).join(", ");
  return names.length > roleNameLimit
    ? `${shown} +${names.length - roleNameLimit} more`
    : shown;
}

const changeLimit = 3;
const fieldLabels: Record<string, string> = {
  nickname: "Nickname",
  username: "Username",
  global_name: "Display name",
  avatar: "Avatar",
  guild_avatar: "Server avatar",
  discriminator: "Discriminator",
};

function changeSummary(item: MemberEvent) {
  if (item.event_type !== "member_update") return "";
  const raw = Array.isArray(item.details?.changes) ? item.details.changes : [];
  const lines: string[] = [];
  for (const change of raw) {
    if (!change || typeof change !== "object") continue;
    const { field, before, after } = change as Record<string, unknown>;
    const label = typeof field === "string" ? fieldLabels[field] : undefined;
    if (!label) continue;
    const text = (value: unknown) =>
      typeof value === "string" && value.trim() ? value : "none";
    lines.push(
      field === "avatar" || field === "guild_avatar"
        ? `${label}: changed`
        : `${label}: ${text(before)} → ${text(after)}`,
    );
  }
  if (!lines.length) return "";
  const shown = lines.slice(0, changeLimit).join(" · ");
  return lines.length > changeLimit
    ? `${shown} +${lines.length - changeLimit} more`
    : shown;
}

function inviteSummary(item: MemberEvent) {
  if (item.event_type !== "invite_use") return "";
  const label = [item.details?.name, item.details?.code].find(
    (value): value is string =>
      typeof value === "string" && value.trim() !== "",
  );
  return label ? `via ${label}` : "";
}

function durationText(seconds: number) {
  const units: [string, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (seconds >= size && seconds % size === 0) {
      const count = seconds / size;
      return `${count} ${unit}${count === 1 ? "" : "s"}`;
    }
  }
  return "";
}

function timeoutSummary(item: MemberEvent) {
  if (item.event_type !== "timeout_add") return "";
  const seconds = item.details?.duration_seconds;
  const duration =
    typeof seconds === "number" && seconds > 0 ? durationText(seconds) : "";
  const until =
    typeof item.details?.until === "string" &&
    !Number.isNaN(new Date(item.details.until).getTime())
      ? `until ${formatDate(item.details.until)}`
      : "";
  return [duration && `For ${duration}`, until].filter(Boolean).join(" · ");
}

export const eventLabels: Record<string, string> = {
  join: "Joined",
  leave: "Left",
  kick: "Kicked",
  ban: "Banned",
  unban: "Unbanned",
  timeout_add: "Timed out",
  timeout_remove: "Timeout removed",
  member_update: "Profile changed",
  roles_added: "Roles added",
  roles_removed: "Roles removed",
  invite_use: "Invite used",
};
const moderationEvents = [
  "kick",
  "ban",
  "unban",
  "timeout_add",
  "timeout_remove",
];

const deliveryLabels: Record<string, string> = {
  queued: "Delivery queued",
  sending: "Delivery in progress",
  uncertain: "Delivery uncertain",
  skipped: "Delivery skipped while disabled",
};

export function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
}

export default function MemberEventRow({
  item,
  onViewMember,
}: {
  item: MemberEvent;
  onViewMember?: (userId: string) => void;
}) {
  const username =
    discordIdentityName(item.user_id, {
      id: item.user_id,
      username: item.username || undefined,
    }) || "";
  const name =
    discordIdentityName(item.user_id, {
      id: item.user_id,
      display_name: item.display_name || undefined,
      username,
    }) || "Discord member unavailable";
  const moderatorName = discordIdentityName(
    item.moderator_id,
    null,
    item.moderator_name,
  );
  const eventLabel = eventLabels[item.event_type] || "Activity";
  const eventIcon =
    eventTypes.find((event) => event.key === item.event_type)?.icon || "●";
  const isModeration = moderationEvents.includes(item.event_type);
  const deliveryText = item.delivery_status
    ? deliveryLabels[item.delivery_status] || ""
    : "";

  const roles = roleSummary(item);
  const summary =
    changeSummary(item) || inviteSummary(item) || timeoutSummary(item);

  return (
    <li className={`member-activity-row is-${item.event_type}`}>
      <div className="member-activity-identity">
        <DiscordIdentity
          userId={item.user_id}
          resolvedMember={{
            id: item.user_id,
            display_name: name,
            username: username || "",
            avatar_url: item.avatar_url,
          }}
          variant="compact"
          contact={false}
        />
      </div>
      <span className={`member-activity-kind ${item.event_type}`}>
        <span aria-hidden="true">{eventIcon}</span>
        {eventLabel}
      </span>
      {(isModeration || roles || summary) && (
        <div className="member-activity-body">
          {isModeration && (
            <div className="member-activity-moderation">
              <p className="member-activity-by">
                by{" "}
                {item.moderator_id ? (
                  <DiscordIdentity
                    userId={item.moderator_id}
                    displayName={moderatorName}
                    resolvedMember={null}
                    variant="compact"
                    contact={false}
                  />
                ) : (
                  "an unknown moderator"
                )}
              </p>
              <p className="member-activity-reason">
                “{item.reason?.trim() || "No reason given"}”
              </p>
            </div>
          )}
          {roles && <p className="member-activity-roles">{roles}</p>}
          {summary && <p className="member-activity-roles">{summary}</p>}
        </div>
      )}
      <div className="member-activity-meta">
        <time className="member-activity-date" dateTime={item.occurred_at}>
          {formatDate(item.occurred_at)}
        </time>
        {deliveryText && (
          <small
            className={`member-activity-delivery ${item.delivery_status === "uncertain" ? "uncertain" : ""}`}
          >
            {deliveryText}
          </small>
        )}
      </div>
      {onViewMember && (
        <button
          type="button"
          className="member-activity-view"
          onClick={() => onViewMember(item.user_id)}
        >
          View member
        </button>
      )}
      <details className="member-activity-details">
        <summary>Details</summary>
        <p title={item.user_id}>Member: {name}</p>
        {item.joined_at && <p>Member joined {formatDate(item.joined_at)}</p>}
        {item.reason && <p>Reason: {item.reason}</p>}
        {item.moderator_id && (
          <p title={item.moderator_id}>
            Moderator: {moderatorName || "Unknown moderator"}
          </p>
        )}
        {deliveryText && <p>{deliveryText}</p>}
        {!item.joined_at &&
          !item.reason &&
          !item.moderator_id &&
          !deliveryText && <p>No additional details recorded.</p>}
      </details>
    </li>
  );
}
