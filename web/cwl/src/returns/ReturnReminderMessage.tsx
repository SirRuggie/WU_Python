export default function ReturnReminderMessage({
  destinations,
  names,
  loading,
  error,
}: {
  destinations: Record<"FWA" | "MAIN", string | null>;
  names: Record<string, string>;
  loading: boolean;
  error: string;
}) {
  return (
    <section className="return-message-panel">
      <p>Message text is not editable on this page.</p>
      <dl>
        {(["FWA", "MAIN"] as const).map((section) => {
          const id = destinations[section];
          return (
            <div key={section}>
              <dt>{section === "MAIN" ? "Main" : "FWA"}</dt>
              <dd>
                {loading
                  ? "Checking destination…"
                  : id
                    ? names[id]
                      ? `#${names[id]}`
                      : "Unknown channel"
                    : error
                      ? "Destination unavailable"
                      : "No channel configured"}
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="small">
        Automatic schedules apply to FWA clans. Main reminders are sent
        manually.
      </p>
    </section>
  );
}
