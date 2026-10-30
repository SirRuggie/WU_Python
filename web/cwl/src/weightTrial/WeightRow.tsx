import {
  useState,
  type RefCallback,
  type KeyboardEvent,
  type ClipboardEvent,
} from "react";
import TownHallIcon from "../TownHallIcon";
import {
  editDraft,
  formatFull,
  whole,
  validateDraft,
  type Draft,
  type Member,
} from "./model";

export default function WeightRow({
  row,
  draft,
  position,
  warning = "",
  busy,
  last,
  onChange,
  inputRef,
  onKey,
  onPaste,
}: {
  row: Member;
  draft: Draft;
  position?: number;
  warning?: string;
  busy: boolean;
  last: boolean;
  onChange: (draft: Draft) => void;
  inputRef: (field: keyof Draft) => RefCallback<HTMLInputElement>;
  onKey: (event: KeyboardEvent<HTMLInputElement>, field: keyof Draft) => void;
  onPaste?: (
    event: ClipboardEvent<HTMLInputElement>,
    field: keyof Draft,
  ) => void;
}) {
  const [focused, setFocused] = useState<keyof Draft | null>(null);
  let invalid = "";
  try {
    validateDraft(draft);
  } catch (cause) {
    invalid = cause instanceof Error ? cause.message : "Correct this weight.";
  }
  const id = `weight-message-${row.tag.replace("#", "")}`;
  const display = (field: keyof Draft) => {
    if (focused === field || !draft[field].trim()) return draft[field];
    try {
      return field === "full"
        ? formatFull(draft.full)
        : whole(draft[field], 999999).toLocaleString("en-US");
    } catch {
      return draft[field];
    }
  };
  return (
    <div
      className={`weight-trial-row${invalid || warning ? " has-weight-issue" : ""}`}
      data-player={row.tag}
    >
      <strong className="weight-trial-position">{position ?? "—"}</strong>
      <div className="weight-trial-player">
        <TownHallIcon level={row.town_hall} />
        <span>
          <strong title={row.name}>{row.name}</strong>
          <small>{row.tag}</small>
        </span>
      </div>
      <label className="weight-trial-storages">
        <span className="weight-trial-sr-only">Storages for {row.name}</span>
        <select
          aria-label={`Storages for ${row.name}`}
          value={draft.storages}
          disabled={busy}
          onChange={(event) =>
            onChange(editDraft(draft, "storages", event.target.value))
          }
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              ×{n}
            </option>
          ))}
        </select>
      </label>
      {(["loot", "full"] as const).map((field) => (
        <label
          className={`weight-trial-field weight-trial-${field}`}
          key={field}
        >
          <span>{field === "loot" ? "Loot" : "Full weight"}</span>
          <input
            ref={inputRef(field)}
            type="text"
            inputMode="decimal"
            enterKeyHint={last ? "done" : "next"}
            aria-label={`${field === "full" ? "Full weight" : "Loot"} for ${row.name} ${row.tag}`}
            aria-invalid={!!invalid}
            aria-describedby={invalid || warning ? id : undefined}
            value={display(field)}
            placeholder="N/A"
            maxLength={16}
            disabled={busy}
            onFocus={(event) => {
              setFocused(field);
              event.currentTarget.select();
            }}
            onBlur={() => setFocused(null)}
            onChange={(event) =>
              onChange(editDraft(draft, field, event.target.value))
            }
            onKeyDown={(event) => onKey(event, field)}
            onPaste={(event) => onPaste?.(event, field)}
          />
        </label>
      ))}
      <span className="weight-trial-phone-full">
        Full <strong>{formatFull(draft.full)}</strong>
      </span>
      {(invalid || warning) && (
        <small
          id={id}
          className={
            invalid ? "weight-trial-row-error" : "weight-trial-row-warning"
          }
        >
          {invalid || `Check weight: ${warning}`}
        </small>
      )}
    </div>
  );
}
