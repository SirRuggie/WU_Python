import { useId, type Ref } from "react";
import { parseManualWeight, type ManualWeightDraft } from "./manualWeight";
import { Button } from "./rosterUi/primitives";

export function compactWeightState(value: ManualWeightDraft) {
  try {
    return { weight: parseManualWeight(value), error: "" };
  } catch (error) {
    return { weight: null, error: (error as Error).message };
  }
}

export default function CompactWeightField({
  value,
  onChange,
  disabled,
  inputRef,
  name,
  error,
}: {
  value: ManualWeightDraft;
  onChange: (value: ManualWeightDraft) => void;
  disabled: boolean;
  inputRef: Ref<HTMLInputElement>;
  name: string;
  error?: string;
}) {
  const id = useId();
  const state = compactWeightState(value);
  const message = state.error || error;
  return (
    <div className="compact-weight-field">
      <div className="compact-weight-controls">
        <input
          ref={inputRef}
          type="text"
          inputMode="decimal"
          aria-label={`${value.unit === "loot" ? "Loot" : "Full weight"} for ${name}`}
          aria-describedby={`${id}-feedback`}
          aria-invalid={!!message}
          placeholder={value.unit === "loot" ? "Loot" : "Full weight"}
          value={value.text}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, text: event.target.value })}
        />
        <div
          className="compact-weight-units"
          role="group"
          aria-label={`Weight unit for ${name}`}
        >
          {(["loot", "full"] as const).map((unit) => (
            <Button
              key={unit}
              aria-pressed={value.unit === unit}
              disabled={disabled}
              onClick={() => onChange({ ...value, unit })}
            >
              {unit === "loot" ? "Loot" : "Full"}
            </Button>
          ))}
        </div>
        <Button
          type="submit"
          variant="primary"
          disabled={disabled || state.weight === null || !!state.error}
        >
          Save
        </Button>
      </div>
      <div
        id={`${id}-feedback`}
        className={`compact-weight-feedback${message ? " is-error" : ""}`}
        aria-live="polite"
      >
        {message ||
          (state.weight !== null &&
            `= ${state.weight.toLocaleString("en-US")}${value.unit === "loot" ? " full weight" : ""} · saved for future seasons`)}
      </div>
    </div>
  );
}
