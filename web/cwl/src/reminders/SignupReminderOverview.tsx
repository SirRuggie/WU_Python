import type { Pool } from "../api";
import {
  nextReminderOccurrence,
  type Campaign,
  type Occurrence,
} from "../reminderCampaign";

const pools = ["main", "lazy"] as const;
export function targetCwlMonth(cycle: string | null) {
  if (!cycle || !/^\d{4}-\d{2}$/.test(cycle)) return "CWL month unavailable";
  const [year, month] = cycle.split("-").map(Number);
  if (month < 1 || month > 12) return "CWL month unavailable";
  return new Date(Date.UTC(year, month, 1)).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
export function shortReminderTime(value?: string | null) {
  if (!value) return "No upcoming send";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}
export default function SignupReminderOverview({
  campaign,
  activated,
  cycle,
  schedule,
  destination,
  recipient,
  onEdit,
  onTiming,
}: {
  campaign: Campaign;
  activated: boolean;
  cycle: string | null;
  schedule: Occurrence[];
  destination: (id: string) => string;
  recipient: (ids: string[]) => string;
  onEdit: (id: string, pool: Pool) => void;
  onTiming: () => void;
}) {
  const messages = Object.entries(campaign.messages).filter(
    ([id]) => id !== "roster",
  );
  const common = Object.fromEntries(
    pools.map((pool) => {
      const values = messages.map(([, item]) => item.variants[pool]);
      return [
        pool,
        {
          destination:
            values.length &&
            values.every(
              (value) =>
                value.destination_channel_id ===
                values[0].destination_channel_id,
            )
              ? values[0].destination_channel_id
              : null,
          roles:
            values.length &&
            values.every(
              (value) =>
                JSON.stringify([...value.role_ids].sort()) ===
                JSON.stringify([...values[0].role_ids].sort()),
            )
              ? values[0].role_ids
              : null,
        },
      ];
    }),
  );
  return (
    <div className="reminder-overview">
      <div className="reminder-overview-head">
        <h3>Messages for {targetCwlMonth(cycle)} CWL</h3>
        <button type="button" onClick={onTiming}>
          Edit timing
        </button>
      </div>
      <p className="reminder-overview-note">
        Times in {Intl.DateTimeFormat().resolvedOptions().timeZone}.
      </p>
      <div
        className="signup-reminder-shared"
        aria-label="Shared message settings"
      >
        {pools.map((pool) => (
          <div key={pool}>
            <strong>{pool === "main" ? "Main" : "Lazy"}</strong>
            {common[pool].destination !== null && (
              <p>Destination: {destination(common[pool].destination)}</p>
            )}
            {common[pool].roles !== null && (
              <p>Notify: {recipient(common[pool].roles)}</p>
            )}
          </div>
        ))}
      </div>
      <div className="reminder-overview-list">
        {messages.map(([id, item]) => {
          const mainEnabled =
            item.enabled && item.variants.main.enabled !== false;
          const lazyEnabled =
            item.enabled && item.variants.lazy.enabled !== false;
          const sameState = mainEnabled === lazyEnabled;
          const mainNext = nextReminderOccurrence(schedule, id, "main")?.run_at;
          const lazyNext = nextReminderOccurrence(schedule, id, "lazy")?.run_at;
          const sameTime = sameState && mainNext === lazyNext;
          const status = (enabled: boolean) =>
            !activated || !enabled ? "Off" : campaign.paused ? "Paused" : "On";
          return (
            <article
              className="signup-reminder-row"
              key={id}
              aria-label={item.label || id}
            >
              <h4>{item.label || id}</h4>
              {(sameState || sameTime) && (
                <p className="signup-reminder-common">
                  {sameState && status(mainEnabled)}
                  {sameTime &&
                    ` · ${!activated ? "Not scheduled" : mainEnabled ? shortReminderTime(mainNext) : "Disabled"}`}
                </p>
              )}
              {pools.map((pool) => {
                const settings = item.variants[pool];
                const enabled = item.enabled && settings.enabled !== false;
                const next = nextReminderOccurrence(schedule, id, pool);
                return (
                  <div className="signup-reminder-pool" key={pool}>
                    <strong>{pool === "main" ? "Main" : "Lazy"}</strong>
                    {!sameState && <span>{status(enabled)}</span>}
                    {common[pool].destination === null && (
                      <p>
                        Destination:{" "}
                        {destination(settings.destination_channel_id)}
                      </p>
                    )}
                    {common[pool].roles === null && (
                      <p>Notify: {recipient(settings.role_ids)}</p>
                    )}
                    {!sameTime && (
                      <p>
                        {!activated
                          ? "Not scheduled"
                          : !enabled
                            ? "Disabled"
                            : shortReminderTime(next?.run_at)}
                      </p>
                    )}
                    <button type="button" onClick={() => onEdit(id, pool)}>
                      Edit
                      <span className="reminder-visually-hidden">
                        {" "}
                        {item.label || id} for{" "}
                        {pool === "main" ? "Main" : "Lazy"}
                      </span>
                    </button>
                  </div>
                );
              })}
            </article>
          );
        })}
      </div>
    </div>
  );
}
