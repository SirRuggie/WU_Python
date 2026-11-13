import { Fragment, useState } from "react";
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
  const [copiedRef, setCopiedRef] = useState("");
  async function copy(reference: string) {
    setCopiedRef(reference);
    try {
      await navigator.clipboard.writeText(reference);
      setCopied("done");
    } catch {
      setCopied("failed");
    }
  }
  return { copied, copiedRef, copy };
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
  /** Several messages from one failure share one block; each keeps its own Reference. */
  message: string | string[];
  /** Extra context, e.g. "Showing the last update." */
  note?: string;
  onRetry?: () => void;
  busy?: boolean;
  disabled?: boolean;
  retryLabel?: string;
  className?: string;
}) {
  const { copied, copiedRef, copy } = useReferenceCopy();
  const parts = (Array.isArray(message) ? message : [message])
    .filter(Boolean)
    .map(splitReference);
  if (!parts.length) return null;
  return (
    <>
      <div
        className={`notice error load-error ${className}`.trim()}
        role="alert"
      >
        <div className="load-error-text">
          {parts.map(({ text, reference }, index) => (
            <Fragment key={index}>
              <p>
                {text}
                {note && index === parts.length - 1 ? ` ${note}` : ""}
              </p>
              {reference && (
                <p className="load-error-reference" aria-live="off">
                  Reference: <code>{reference}</code>
                  <button type="button" onClick={() => copy(reference)}>
                    {copiedRef === reference && copied === "done"
                      ? "Copied"
                      : "Copy"}
                  </button>
                  {copiedRef === reference && copied === "failed" && (
                    <span>
                      {" "}
                      Could not copy. Select the reference to copy it.
                    </span>
                  )}
                </p>
              )}
            </Fragment>
          ))}
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
