import { useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../api";
import { Button } from "../rosterUi/primitives";
import SearchPicker from "../SearchPicker";
import ClockFields from "./ClockFields";
import {
  API_BASE,
  newRequestId,
  voiceOption,
  type ClockDraft,
  type ClockSettings,
  type VoiceChannel,
  type ZoneChip,
} from "./worldClocksModel";

type Mode = "create" | "existing";

/** Add clock: a bottom sheet on the phone, a dialog on desktop. */
export default function AddClockDialog({
  chips,
  usedZones,
  voiceChannels,
  categories,
  settings,
  channelsAvailable,
  onClose,
  onAdded,
  onDirty,
}: {
  chips: ZoneChip[];
  usedZones: Set<string>;
  voiceChannels: VoiceChannel[];
  categories: { id: string; name: string }[];
  settings: ClockSettings;
  channelsAvailable: boolean;
  onClose: () => void;
  onAdded: (notice: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [draft, setDraft] = useState<ClockDraft>({
    zone: "",
    flag: "",
    code: "",
    channel_id: "",
  });
  const [mode, setMode] = useState<Mode>("create");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // One id per try. A double tap or a retry after an unclear error reuses it,
  // so the server answers from its receipt instead of creating a 2nd channel.
  const requestId = useRef(newRequestId());
  const category = categories.find((row) => row.id === settings.category_id);

  useLayoutEffect(() => {
    const opener = document.activeElement;
    dialog.current?.showModal?.();
    return () => {
      dialog.current?.close?.();
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);

  function change(next: ClockDraft) {
    setDraft(next);
    onDirty(!!next.zone);
  }

  const ready =
    !!draft.zone &&
    channelsAvailable &&
    (mode === "create"
      ? !!category
      : voiceChannels.some(
          (channel) => channel.id === draft.channel_id && !channel.used,
        ));

  async function submit() {
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`${API_BASE}`, "POST", {
        request_id: requestId.current,
        zone: draft.zone,
        flag: draft.flag,
        code: draft.code.trim() || null,
        mode,
        category_id: mode === "create" ? settings.category_id : null,
        channel_id: mode === "existing" ? draft.channel_id : null,
      });
      onDirty(false);
      onAdded(
        mode === "create"
          ? "Clock added. The new channel is in Discord."
          : "Clock added. It shows in Discord at the next update.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Adding the clock failed.",
      );
      // Renew the id only after a definite refusal, where no channel was made.
      // Network errors (status 0), 5xx and 409 keep the id: Discord may have
      // created the channel, and the same id lets the server find that out.
      if (reason instanceof ApiError && [400, 403, 404].includes(reason.status))
        requestId.current = newRequestId();
      setBusy(false);
    }
  }

  return createPortal(
    <dialog
      ref={dialog}
      className="world-clock-sheet"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="world-clock-sheet-body">
        <h2 id={titleId}>Add clock</h2>
        <ClockFields
          draft={draft}
          onChange={change}
          chips={chips}
          usedZones={usedZones}
          disabled={busy}
        />
        <fieldset className="world-clock-mode" disabled={busy}>
          <legend className="world-clock-label">Channel</legend>
          <label
            className={
              mode === "create"
                ? "world-clock-radio is-selected"
                : "world-clock-radio"
            }
          >
            <input
              type="radio"
              name="world-clock-mode"
              checked={mode === "create"}
              onChange={() => setMode("create")}
            />
            <span>
              Create a new voice channel
              <small>
                {category
                  ? `In ${category.name}, with its permissions.`
                  : "Select a category in Settings first."}
              </small>
            </span>
          </label>
          <label
            className={
              mode === "existing"
                ? "world-clock-radio is-selected"
                : "world-clock-radio"
            }
          >
            <input
              type="radio"
              name="world-clock-mode"
              checked={mode === "existing"}
              onChange={() => setMode("existing")}
            />
            <span>
              Use an existing voice channel
              <small>Only a channel no other app renames.</small>
            </span>
          </label>
          {mode === "existing" && (
            <SearchPicker
              label="Voice channel"
              options={voiceChannels.map((channel) =>
                voiceOption(channel, channel.used ? "has a clock" : ""),
              )}
              value={draft.channel_id}
              placeholder="Select a voice channel"
              searchPlaceholder="Search voice channels"
              emptyText="No voice channels match."
              disabled={busy}
              onChange={(channel_id) => setDraft({ ...draft, channel_id })}
            />
          )}
        </fieldset>
        {!channelsAvailable && (
          <p className="world-clock-error" role="alert">
            Discord is unavailable. You cannot add a clock now.
          </p>
        )}
        {error && (
          <p className="world-clock-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="world-clock-sheet-footer">
        <Button disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={!ready || busy}
          onClick={() => void submit()}
        >
          {busy
            ? "Adding…"
            : mode === "create"
              ? "Create channel and add"
              : "Add clock"}
        </Button>
      </div>
    </dialog>,
    document.body,
  );
}
