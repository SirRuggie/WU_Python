import LoadError from "../LoadError";

export default function ClanActivityStatus({
  error,
  busy,
  checkedAt,
  warnings,
  refresh,
}: {
  error: string;
  busy: boolean;
  checkedAt?: string;
  warnings: string[];
  refresh: () => void;
}) {
  return (
    <>
      <div className="activity-refresh">
        <span role="status">
          {busy
            ? "Checking clan activity…"
            : checkedAt
              ? `Checked ${new Date(checkedAt).toLocaleTimeString()}`
              : "Not checked yet"}
          {error && checkedAt ? " · Showing the last update" : ""}
        </span>
        <button aria-busy={busy || undefined} onClick={refresh} disabled={busy}>
          {busy ? "Checking…" : "Refresh"}
        </button>
      </div>
      <LoadError message={error} onRetry={refresh} busy={busy} />
      {warnings.map((note) => (
        <p className="notice" role="status" key={note}>
          {note}
        </p>
      ))}
    </>
  );
}
