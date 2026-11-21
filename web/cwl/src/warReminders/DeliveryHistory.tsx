import "./maintenance.css";
import { TriangleAlert } from "lucide-react";
import { formatDateTime } from "../format";
import { timeLabel, type ReminderData } from "./types";

const statuses: Record<string, string> = {
  sent: "✓ Sent",
  failed: "! Failed",
  skipped: "– Skipped",
  uncertain: "? Uncertain",
  sending: "? Delivery unconfirmed",
};

const needReview = (data: ReminderData) =>
  data.history.filter((receipt) =>
    ["sending", "uncertain", "failed"].includes(receipt.status),
  ).length;

/** The outer disclosure summary; unresolved deliveries stay flagged while it is closed. */
export const historySummary = (data: ReminderData) =>
  `Test & history${needReview(data) ? ` · ${needReview(data)} need review` : ""}`;

export function DeliveryStatus({
  data,
  enabled,
}: {
  data: ReminderData;
  enabled: boolean;
}) {
  return (
    <section className="war-status">
      <h3>Reminder status</h3>
      {enabled && data.health?.category === "attention" ? (
        <p className="notice error" role="status">
          <strong>{data.health.label}</strong>
          <span>{data.health.detail}</span>
        </p>
      ) : enabled && data.health?.category === "maintenance" ? (
        <p className="notice reminder-maintenance" role="status">
          <strong>
            <TriangleAlert size={16} aria-hidden="true" />
            Clash maintenance
          </strong>
          <span>Reminders continue when it ends.</span>
        </p>
      ) : (
        <p>
          {enabled
            ? data.status?.detail || "Waiting for the first check."
            : "Automatic reminders are disabled."}
        </p>
      )}
      {data.status?.checked_at && (
        <small>
          Last checked {formatDateTime(new Date(data.status.checked_at))}
        </small>
      )}
      <p className="small">
        Each player is named once, with only their accounts that have attacks
        left.
      </p>
    </section>
  );
}

export default function DeliveryHistory({ data }: { data: ReminderData }) {
  return (
    <section className="war-deliveries">
      <h4>Delivery history · {data.history.length} recent</h4>
      {data.history.length ? (
        <div className="war-history">
          {data.history.map((receipt, index) => (
            <article key={`${receipt.at}-${index}`}>
              <div>
                <strong>
                  {receipt.test ? "Test · " : ""}
                  {receipt.event === "start"
                    ? "War started"
                    : `${timeLabel(Number(receipt.event))} reminder`}
                </strong>
                <small>{formatDateTime(new Date(receipt.at))}</small>
              </div>
              <span>
                {statuses[receipt.status] || "? Unknown delivery status"}
                {receipt.status === "skipped" && receipt.detail
                  ? ` · ${receipt.detail}`
                  : ""}
              </span>
              {(receipt.urls?.length
                ? receipt.urls
                : receipt.url
                  ? [receipt.url]
                  : []
              ).map((url, part) => (
                <a
                  className="war-delivery-link"
                  key={url}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                >
                  View{part ? ` part ${part + 1}` : ""} ↗
                </a>
              ))}
              {receipt.detail && receipt.status !== "skipped" && (
                <p>{receipt.detail}</p>
              )}
            </article>
          ))}
        </div>
      ) : (
        <p>No deliveries yet. Send a test to see your first receipt.</p>
      )}
    </section>
  );
}
