import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import ConfirmDialog from "../ConfirmDialog";
import { timeLabel, type ReminderData, type ReminderSettings } from "./types";

type Target = {
  tag: string;
  name: string;
  type: string;
  revision: string;
  settings: ReminderSettings;
};
type Field = "minutes" | "audience" | "war_started" | "enabled";
const labels: Record<Field, string> = {
  minutes: "Times",
  audience: "Who to remind",
  war_started: "War-start message",
  enabled: "On/off",
};
type Result = { tag: string; ok: boolean; message: string };
export default function CopyReminders({
  base,
  source,
  disabled,
  onBusy,
}: {
  base: string;
  source: ReminderData;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const [open, setOpen] = useState(false),
    [targets, setTargets] = useState<Target[]>([]);
  const [selected, setSelected] = useState<string[]>([]),
    [fields, setFields] = useState<Field[]>(["minutes"]);
  const [type, setType] = useState(""),
    [error, setError] = useState("");
  const [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [review, setReview] = useState<{
    revision: string;
    fields: Field[];
    targets: Target[];
  } | null>(null);
  const running = useRef(false);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setLoading(true);
    setError("");
    setTargets([]);
    setSelected([]);
    setReview(null);
    api<{ clans: Target[] }>(base + "/copy")
      .then((data) => {
        if (current) setTargets(data.clans);
      })
      .catch((e) => {
        if (current) setError(e.message);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [base, open]);
  useEffect(() => {
    setReview(null);
  }, [source.revision, disabled]);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  const chosen = targets.filter((t) => selected.includes(t.tag));
  async function copy() {
    if (!review || disabled || running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await api<{ results: Result[] }>(
        base + "/copy",
        "POST",
        {
          revision: review.revision,
          fields: review.fields,
          targets: review.targets.map(({ tag, revision }) => ({
            tag,
            revision,
          })),
        },
      );
      setResults(response.results);
      setSelected([]);
      setReview(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not confirm the copy. Check the clans before retrying.",
      );
      setReview(null);
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  return (
    <details
      className="war-disclosure"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary
        onClick={(e) => {
          if (busy) e.preventDefault();
        }}
      >
        Copy reminder settings to other clans
      </summary>
      {open && (
        <div>
          <p>
            Channels stay unchanged. Clans without a channel stay off. Save
            changes to this clan before copying.
          </p>
          {error && <p role="alert">{error}</p>}
          {loading ? (
            <p role="status">Loading clans…</p>
          ) : (
            <fieldset disabled={disabled || busy}>
              <legend>Choose what to copy</legend>
              {(Object.keys(labels) as Field[]).map((field) => (
                <label key={field}>
                  <input
                    type="checkbox"
                    checked={fields.includes(field)}
                    onChange={(e) =>
                      setFields((current) =>
                        e.target.checked
                          ? [...current, field]
                          : current.filter((f) => f !== field),
                      )
                    }
                  />{" "}
                  {labels[field]}
                </label>
              ))}
              <label>
                Clan type{" "}
                <select value={type} onChange={(e) => setType(e.target.value)}>
                  <option value="">All types</option>
                  {[...new Set(targets.map((t) => t.type))]
                    .sort()
                    .map((value) => (
                      <option key={value} value={value || "__unset"}>
                        {value || "Not set"}
                      </option>
                    ))}
                </select>
              </label>
              {targets
                .filter(
                  (t) =>
                    !type || (type === "__unset" ? !t.type : t.type === type),
                )
                .map((target) => (
                  <label key={target.tag}>
                    <input
                      type="checkbox"
                      checked={selected.includes(target.tag)}
                      onChange={(e) =>
                        setSelected((current) =>
                          e.target.checked
                            ? [...current, target.tag]
                            : current.filter((tag) => tag !== target.tag),
                        )
                      }
                    />{" "}
                    {target.name}
                    {!target.settings.channel_id && " · Needs a channel · Off"}
                  </label>
                ))}
              <p>{chosen.length} clans selected</p>
              <button
                type="button"
                disabled={!chosen.length || !fields.length}
                onClick={() =>
                  setReview({
                    revision: source.revision,
                    fields: [...fields],
                    targets: chosen,
                  })
                }
              >
                Review copy
              </button>
            </fieldset>
          )}
          {results.length > 0 && (
            <ul aria-label="Copy results">
              {results.map((result) => (
                <li key={result.tag}>
                  {targets.find((t) => t.tag === result.tag)?.name ||
                    "Clan unavailable"}
                  : {result.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {review && (
        <ConfirmDialog
          text={`Copy to ${review.targets.length} clans?`}
          confirmLabel="Copy settings"
          disabled={busy}
          onCancel={() => setReview(null)}
          onConfirm={() => void copy()}
        >
          <ul>
            {review.fields.map((field) => (
              <li key={field}>
                {labels[field]}:{" "}
                {field === "minutes"
                  ? source.settings.minutes.map(timeLabel).join(", ") || "None"
                  : field === "audience"
                    ? source.settings.audience === "zero"
                      ? "Players with no attacks used"
                      : "Players with attacks left"
                    : source.settings[field]
                      ? "On"
                      : "Off"}
              </li>
            ))}
          </ul>
          <ul>
            {review.targets.map((t) => (
              <li key={t.tag}>
                {t.name}
                {!t.settings.channel_id && " · Needs a channel · Off"}
              </li>
            ))}
          </ul>
          <p>Each clan keeps its own channel.</p>
        </ConfirmDialog>
      )}
    </details>
  );
}
