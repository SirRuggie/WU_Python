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
};

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
      {isModeration && (
        <p className="member-activity-moderation">
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
          {" · "}“{item.reason?.trim() || "No reason given"}”
        </p>
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
