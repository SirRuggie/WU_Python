import { CircleAlert } from "lucide-react";
import type { Campaign } from "../reminderCampaign";
import type { AnnouncementChannel } from "../announcements";
import { variantErrors, type ReminderLookups } from "./reminderErrors";
import {
  scopePools,
  variantIsOn,
  type ReminderPoolScope,
} from "./reminderList";
import { shortReminderTime } from "./reminderFormat";

export default function ReminderMessageRow({
  campaign,
  id,
  scope,
  next,
  activated,
  channels,
  lookups,
  unsaved,
  selected,
  busy,
  onOpen,
  rowRef,
}: {
  campaign: Campaign;
  id: string;
  scope: ReminderPoolScope;
  next?: string;
  activated: boolean;
  channels: AnnouncementChannel[];
  lookups: ReminderLookups;
  unsaved: boolean;
  selected: boolean;
  busy: boolean;
  onOpen: () => void;
  rowRef: (node: HTMLButtonElement | null) => void;
}) {
  const message = campaign.messages[id];
  const pools = scopePools(scope);
  const off = pools.every((pool) => !variantIsOn(campaign, id, pool));
  const time = !activated
    ? "Not scheduled"
    : off
      ? "Off"
      : shortReminderTime(next);
  return (
    <button
      type="button"
      className={`reminder-message-row${selected ? " is-selected" : ""}`}
      data-reminder-message={id}
      ref={rowRef}
      aria-pressed={selected}
      disabled={busy}
      onClick={onOpen}
    >
      <span className="reminder-message-row-top">
        <strong>{message.label || "Message"}</strong>
        <time dateTime={next}>{time}</time>
      </span>
      <span className="reminder-message-destinations">
        {pools.map((pool) => {
          const label = pool === "main" ? "Main" : "Lazy";
          const errors = variantErrors(campaign, id, pool, lookups);
          const settings = message.variants[pool];
          const destination = !variantIsOn(campaign, id, pool)
            ? "Off"
            : lookups.channels.loading || lookups.channels.error
              ? "Names unavailable"
              : channels.find(
                  (channel) => channel.id === settings.destination_channel_id,
                )?.name || "Unknown channel";
          return errors.length ? (
            <span className="reminder-row-error" key={pool}>
              <CircleAlert size={14} aria-hidden="true" />
              {label}: {errors.map((error) => error.label).join(", ")}
            </span>
          ) : (
            <span key={pool}>
              {label}: {destination}
            </span>
          );
        })}
        {unsaved && <span className="reminder-unsaved">Unsaved</span>}
      </span>
    </button>
  );
}
