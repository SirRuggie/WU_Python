import { useEffect, useState } from "react";
import { api } from "./api";
import ChangeHistory from "./ChangeHistory";
import SearchPicker from "./SearchPicker";

export default function DeletedCommands({
  disabled,
  onBusy,
  onRestored,
}: {
  disabled: boolean;
  onBusy: (busy: boolean) => void;
  onRestored: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false),
    [names, setNames] = useState<string[]>([]),
    [selected, setSelected] = useState(""),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setError("");
    api<{ commands: string[] }>("/manage/text-command-deleted")
      .then((result) => {
        if (alive) {
          setNames(result.commands);
          setSelected(result.commands[0] ?? "");
        }
      })
      .catch(() => {
        if (alive) setError("Could not load deleted commands.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open]);
  return (
    <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Deleted commands</summary>
      {loading && <p role="status">Loading history…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && !names.length && <p>No deleted commands.</p>}
      {names.length > 0 && (
        <>
          <SearchPicker
            label="Command"
            value={selected}
            options={names.map((name) => ({ value: name, label: name }))}
            disabled={disabled}
            placeholder="Select a command"
            searchPlaceholder="Search deleted commands"
            emptyText="No deleted commands match."
            onChange={setSelected}
          />
          {selected && (
            <ChangeHistory
              key={selected}
              target={"/manage/text-commands/" + encodeURIComponent(selected)}
              revision=""
              disabled={disabled}
              onBusy={onBusy}
              onRestored={onRestored}
            />
          )}
        </>
      )}
    </details>
  );
}
