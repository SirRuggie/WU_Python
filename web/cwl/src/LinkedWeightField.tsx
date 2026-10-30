import { useId } from "react";
import { Button } from "./rosterUi/primitives";
import { editDraft, validateDraft, type Draft } from "./weightTrial/model";

export default function LinkedWeightField({
  value,
  onChange,
  disabled,
  unchanged,
  name,
  allowEmptyClear = false,
  onClear,
}: {
  value: Draft;
  onChange: (value: Draft) => void;
  disabled: boolean;
  unchanged: boolean;
  name: string;
  allowEmptyClear?: boolean;
  onClear?: () => void;
}) {
  const id = useId();
  let error = "";
  try {
    validateDraft(value);
  } catch (cause) {
    error = (cause as Error).message;
  }
  return (
    <div className="linked-weight-field">
      <div className="linked-weight-inputs">
        <label>
          Storages
          <select
            aria-label={`Storages for ${name}`}
            value={value.storages}
            disabled={disabled}
            onChange={(event) =>
              onChange(editDraft(value, "storages", event.target.value))
            }
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        {(["loot", "full"] as const).map((field) => (
          <label key={field}>
            {field === "full" ? "Full weight" : "Loot"}
            <input
              aria-label={`${field === "full" ? "Full weight" : "Loot"} for ${name}`}
              aria-invalid={!!error}
              aria-describedby={id}
              inputMode="decimal"
              type="text"
              value={value[field]}
              disabled={disabled}
              placeholder="Not Available"
              onChange={(event) =>
                onChange(editDraft(value, field, event.target.value))
              }
            />
          </label>
        ))}
      </div>
      <small id={id} aria-live="polite">
        {error || "Loot × storages = full weight. Blank means Not Available."}
      </small>
      <div className="linked-weight-actions">
        <Button
          disabled={
            disabled || (!value.full && !value.loot && !allowEmptyClear)
          }
          onClick={() => {
            onChange({ ...value, full: "", loot: "" });
            onClear?.();
          }}
        >
          Clear weight
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={disabled || unchanged || !!error}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
