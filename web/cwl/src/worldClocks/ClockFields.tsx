import { useEffect, useId, useState } from "react";
import { api } from "../api";
import ZonePicker from "./ZonePicker";
import {
  API_BASE,
  type ClockDraft,
  type ClockPreview,
  type ZoneChip,
} from "./worldClocksModel";

const PREVIEW_DELAY_MS = 300;

/** Server-built names for the draft. Runs only while the form is open. */
export function useClockPreview(draft: ClockDraft) {
  const [preview, setPreview] = useState<ClockPreview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!draft.zone) {
      setPreview(null);
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => {
      api<ClockPreview>(`${API_BASE}/preview`, "POST", {
        zone: draft.zone,
        flag: draft.flag,
        code: draft.code.trim() || null,
      })
        .then((result) => {
          if (!current) return;
          setPreview(result);
          setError("");
        })
        .catch((reason) => {
          if (!current) return;
          setPreview(null);
          setError(
            reason instanceof Error
              ? reason.message
              : "Preview is unavailable.",
          );
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [draft.zone, draft.flag, draft.code]);
  return { preview, error };
}

export default function ClockFields({
  draft,
  onChange,
  chips,
  usedZones,
  disabled,
}: {
  draft: ClockDraft;
  onChange: (next: ClockDraft) => void;
  chips: ZoneChip[];
  usedZones: Set<string>;
  disabled?: boolean;
}) {
  const flagId = useId();
  const codeId = useId();
  const codeHelpId = useId();
  const { preview, error } = useClockPreview(draft);
  const needsCode = !!preview?.needs_code;

  return (
    <>
      <ZonePicker
        value={draft.zone}
        flag={draft.flag}
        chips={chips}
        usedZones={usedZones}
        disabled={disabled}
        onChange={(zone, flag) => onChange({ ...draft, zone, flag, code: "" })}
      />
      <div className="world-clock-two">
        <div>
          <label className="world-clock-label" htmlFor={flagId}>
            Flag
          </label>
          <input
            id={flagId}
            className="world-clock-input world-clock-flag"
            value={draft.flag}
            maxLength={16}
            disabled={disabled}
            aria-describedby={`${flagId}-help`}
            onChange={(event) =>
              onChange({ ...draft, flag: event.target.value })
            }
          />
          <p id={`${flagId}-help`} className="world-clock-help">
            Emoji, or empty.
          </p>
        </div>
        <div>
          <label className="world-clock-label" htmlFor={codeId}>
            Code
          </label>
          <input
            id={codeId}
            className="world-clock-input"
            value={draft.code}
            maxLength={6}
            disabled={disabled}
            placeholder={preview?.code_auto || ""}
            aria-invalid={needsCode || undefined}
            aria-describedby={codeHelpId}
            onChange={(event) =>
              onChange({ ...draft, code: event.target.value.toUpperCase() })
            }
          />
          <p
            id={codeHelpId}
            className={
              needsCode ? "world-clock-help is-error" : "world-clock-help"
            }
          >
            {needsCode
              ? "Type a code, for example GST."
              : "Empty = automatic, changes with summer time."}
          </p>
        </div>
      </div>
      <div className="world-clock-preview" aria-live="polite">
        {error ? (
          <p className="world-clock-help is-error">{error}</p>
        ) : preview?.name_now ? (
          <>
            <p>
              <span className="world-clock-preview-label">
                Channel name now
              </span>
              <span className="world-clock-name">{preview.name_now}</span>
            </p>
            <p>
              <span className="world-clock-preview-label">
                Other half of year
              </span>
              <span>
                {preview.name_other || "No summer time in this zone."}
              </span>
            </p>
          </>
        ) : (
          <p className="world-clock-help">
            {draft.zone
              ? "Building the preview…"
              : "Select a time zone to see the channel name."}
          </p>
        )}
      </div>
    </>
  );
}
