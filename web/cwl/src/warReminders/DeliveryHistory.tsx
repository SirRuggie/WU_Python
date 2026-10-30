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
          Last checked {new Date(data.status.checked_at).toLocaleString()}
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
                  <small>{new Date(receipt.at).toLocaleString()}</small>
                </div>
                <span>
                  {statuses[receipt.status] || "? Unknown delivery status"}
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
                {receipt.detail && <p>{receipt.detail}</p>}
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
          Each Discord user is mentioned once, with only their pending accounts
          from this war listed beneath them. Unlinked accounts are listed
          separately. No reminder is sent when everyone is done. After downtime,
          reminders more than five minutes late are skipped.
        </p>
      </details>
    </section>
  );
}
