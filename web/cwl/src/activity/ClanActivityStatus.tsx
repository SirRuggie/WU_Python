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
      <LoadError
        message={error}
        note={checkedAt ? "Showing the last update." : undefined}
        onRetry={refresh}
        busy={busy}
      />
      {warnings.map((note) => (
        <p className="notice" role="status" key={note}>
          {note}
        </p>
      ))}
    </>
  );
}
