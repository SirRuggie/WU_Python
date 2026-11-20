import { useId, useLayoutEffect, useRef, useState } from "react";
import { numericInputProps } from "../inputProps";

/** Keep incomplete input outside Campaign; never coerce a cleared field to zero. */
export default function ReminderNumberField({
  label,
  value,
  min,
  max,
  onChange,
  onInvalidChange = () => {},
}: {
  label: string;
  value: number;
  min: number;
  max?: number;
  onChange: (value: number) => void;
  onInvalidChange?: (invalid: boolean) => void;
}) {
  const [text, setText] = useState(String(value));
  const callback = useRef(onInvalidChange);
  callback.current = onInvalidChange;
  const previous = useRef(value);
  const issueId = useId();
  const number = Number(text);
  const invalid =
    !text.trim() ||
    !Number.isFinite(number) ||
    number < min ||
    (max !== undefined && number > max);
  useLayoutEffect(() => {
    if (previous.current !== value) {
      previous.current = value;
      setText(String(value));
    }
  }, [value]);
  useLayoutEffect(() => {
    callback.current(invalid);
    return () => callback.current(false);
  }, [invalid]);
  const message = !text.trim()
    ? "Enter a number."
    : max === undefined
      ? `Enter a number of at least ${min}.`
      : `Enter a number from ${min} to ${max}.`;
  return (
    <label>
      {label}
      <input
        {...numericInputProps}
        type="number"
        min={min}
        max={max}
        value={text}
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? issueId : undefined}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          const parsed = Number(next);
          if (
            next.trim() &&
            Number.isFinite(parsed) &&
            parsed >= min &&
            (max === undefined || parsed <= max)
          )
            onChange(parsed);
        }}
      />
      {invalid && (
        <small id={issueId} className="reminder-field-error" role="alert">
          {message}
        </small>
      )}
    </label>
  );
}
