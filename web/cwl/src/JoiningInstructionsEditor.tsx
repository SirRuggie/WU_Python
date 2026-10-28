import { useId, useLayoutEffect, useRef } from "react";
import JoiningInstructionsCard from "./JoiningInstructionsCard";
export default function JoiningInstructionsEditor({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (text: string) => void;
  disabled: boolean;
}) {
  const id = useId();
  const textarea = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight + element.offsetHeight - element.clientHeight}px`;
  }, [value]);
  const tooLong = value.length > 2000;
  return (
    <div className="joining-instructions-editor">
      <label htmlFor={id}>Joining instructions</label>
      <p id={`${id}-hint`}>Shown to members with their clan</p>
      <textarea
        id={id}
        ref={textarea}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        rows={3}
        aria-invalid={tooLong}
        aria-describedby={`${id}-hint${tooLong ? ` ${id}-error` : ""}`}
      />
      {value.length >= 1800 && (
        <p aria-live="polite">
          {value.length.toLocaleString("en-US")} / 2,000 characters
        </p>
      )}
      {tooLong && (
        <p id={`${id}-error`} role="alert">
          Keep joining instructions to 2,000 characters or fewer.
        </p>
      )}
      <details>
        <summary>Preview as members see it ›</summary>
        <JoiningInstructionsCard text={value} />
      </details>
    </div>
  );
}
