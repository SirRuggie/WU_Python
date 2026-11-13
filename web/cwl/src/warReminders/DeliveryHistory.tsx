import { formatDateTime } from "../format";
import { timeLabel, type ReminderData } from "./types";

const statuses: Record<string, string> = {
  sent: "✓ Sent",
  failed: "! Failed",
  skipped: "– Skipped",
  uncertain: "? Uncertain",
  sending: "? Delivery unconfirmed",
};

export default function DeliveryHistory({
  data,
  enabled,
}: {
  data: ReminderData;
  enabled: boolean;
}) {
  const unconfirmed = data.history.filter((receipt) =>
    ["sending", "uncertain", "failed"].includes(receipt.status),
  ).length;
  return (
    <section className="war-deliveries">
      <h3>Reminder status</h3>
      <p>
        {enabled
          ? data.status?.detail || "Waiting for the bot’s first check."
          : "Automatic reminders are disabled."}
      </p>
      {data.status?.checked_at && (
        <small>
          Last checked {formatDateTime(new Date(data.status.checked_at))}
        </small>
      )}
      <details className="war-disclosure">
        <summary>
          Delivery history
          {unconfirmed
            ? ` · ${unconfirmed} need review`
            : ` · ${data.history.length} recent`}
        </summary>
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
      </details>
      <details className="war-disclosure">
        <summary>How reminders work</summary>
        <p className="small">
          The reminder names each Discord user one time. Under each name it
          lists only that user's accounts with attacks left in this war. It
          lists unlinked accounts in a separate group. The bot sends no reminder
          when all attacks are used. After the bot was off, it skips reminders
          that are more than five minutes late.
        </p>
      </details>
    </section>
  );
}
