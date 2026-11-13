import { useState } from "react";
import "./LoadError.css";

/** Splits "… Reference: ABC123" (added by api.ts) off the message. */
export function splitReference(message: string) {
  const match = /\s*Reference:\s*(\S+)\s*$/.exec(message);
  return match
    ? { text: message.slice(0, match.index), reference: match[1] }
    : { text: message, reference: "" };
}

/** Copy state for an issue reference; the status is announced outside any alert. */
export function useReferenceCopy() {
  const [copied, setCopied] = useState<"" | "done" | "failed">("");
  async function copy(reference: string) {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied("done");
    } catch {
      setCopied("failed");
    }
  }
  return { copied, copy };
}

/** Visually hidden copy result; render it outside any role="alert". */
export function CopyStatus({ copied }: { copied: "" | "done" | "failed" }) {
  return (
    <span className="load-error-status" role="status">
      {copied === "done"
        ? "Reference copied"
        : copied === "failed"
          ? "Could not copy. Select the reference to copy it."
          : ""}
    </span>
  );
}

/**
 * The one block for "this section could not load": the message, an optional
 * note, a copyable issue reference, and Try again.
 */
export default function LoadError({
  message,
  note,
  onRetry,
  busy = false,
  disabled = false,
  retryLabel = "Try again",
  className = "",
}: {
  message: string;
  /** Extra context, e.g. "Showing the last update." */
  note?: string;
  onRetry?: () => void;
  busy?: boolean;
  disabled?: boolean;
  retryLabel?: string;
  className?: string;
}) {
  const { copied, copy } = useReferenceCopy();
  if (!message) return null;
  const { text, reference } = splitReference(message);
  return (
    <>
      <div
        className={`notice error load-error ${className}`.trim()}
        role="alert"
      >
        <div className="load-error-text">
          <p>
            {text}
            {note ? ` ${note}` : ""}
          </p>
          {reference && (
            <p className="load-error-reference" aria-live="off">
              Reference: <code>{reference}</code>
              <button type="button" onClick={() => copy(reference)}>
                {copied === "done" ? "Copied" : "Copy"}
              </button>
              {copied === "failed" && (
                <span> Could not copy. Select the reference to copy it.</span>
              )}
            </p>
          )}
        </div>
        {onRetry && (
          <button
            type="button"
            disabled={busy || disabled}
            aria-busy={busy || undefined}
            onClick={onRetry}
          >
            {busy ? "Checking…" : retryLabel}
          </button>
        )}
      </div>
      <CopyStatus copied={copied} />
    </>
  );
}
