import { useEffect, useId, useRef, useState } from "react";
import { Ban } from "lucide-react";
import { api, ApiError } from "../api";
import ConfirmDialog from "../ConfirmDialog";
import { Button } from "../rosterUi/primitives";
import SearchPicker from "../SearchPicker";
import ClockFields from "./ClockFields";
import {
  API_BASE,
  discordName,
  draftFrom,
  hasProblem,
  localTime,
  nameParts,
  problemText,
  sameDraft,
  voiceOption,
  zoneCity,
  type ClockDraft,
  type VoiceChannel,
  type WorldClock,
  type ZoneChip,
} from "./worldClocksModel";

type Props = {
  clock: WorldClock;
  open: boolean;
  focusChannel: boolean;
  chips: ZoneChip[];
  usedZones: Set<string>;
  voiceChannels: VoiceChannel[];
  channelsAvailable: boolean;
  onOpen: (open: boolean) => void;
  onDirty: (dirty: boolean) => void;
  onSaved: (clock: WorldClock, nextUpdate: string) => void;
  onReload: (notice: string) => void;
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Saving failed. Try again.";
}

export default function WorldClockRow({
  clock,
  open,
  focusChannel,
  chips,
  usedZones,
  voiceChannels,
  channelsAvailable,
  onOpen,
  onDirty,
  onSaved,
  onReload,
}: Props) {
  const [enabled, setEnabled] = useState(clock.enabled);
  const [switchBusy, setSwitchBusy] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const [draft, setDraft] = useState<ClockDraft>(() => draftFrom(clock));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const panelId = useId();
  const rowRef = useRef<HTMLElement>(null);
  const channelRef = useRef<HTMLButtonElement>(null);
  const problem = hasProblem({ ...clock, enabled });
  const dirty = open && !sameDraft(draft, draftFrom(clock));

  useEffect(() => setEnabled(clock.enabled), [clock.enabled, clock.revision]);
  useEffect(() => {
    if (!open) {
      setDraft(draftFrom(clock));
      setError("");
    }
  }, [open, clock]);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => {
    if (!open) return;
    rowRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    if (focusChannel) channelRef.current?.focus();
  }, [open, focusChannel]);

  async function toggle(next: boolean) {
    setEnabled(next);
    setSwitchBusy(true);
    setSwitchError("");
    try {
      const result = await api<{ clock: WorldClock; next_update: string }>(
        `${API_BASE}/${clock.id}`,
        "PATCH",
        { revision: clock.revision, enabled: next },
      );
      onSaved(
        {
          ...clock,
          ...result.clock,
          channel_name: clock.channel_name,
          channel_missing: clock.channel_missing,
        },
        result.next_update,
      );
    } catch (reason) {
      setEnabled(!next);
      if (reason instanceof ApiError && reason.status === 409)
        onReload(errorText(reason));
      else setSwitchError(errorText(reason));
    } finally {
      setSwitchBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ clock: WorldClock; next_update: string }>(
        `${API_BASE}/${clock.id}`,
        "PUT",
        {
          revision: clock.revision,
          zone: draft.zone,
          flag: draft.flag,
          code: draft.code.trim() || null,
          channel_id: draft.channel_id || null,
        },
      );
      onSaved(result.clock, result.next_update);
      onOpen(false);
      onReload(`Saved. Shows in Discord at ${localTime(result.next_update)}.`);
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        reason.status === 409 &&
        /changed/i.test(reason.message)
      ) {
        onOpen(false);
        onReload(errorText(reason));
      } else setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ channel?: string }>(
        `${API_BASE}/${clock.id}`,
        "DELETE",
        { revision: clock.revision },
      );
      setConfirmRemove(false);
      onOpen(false);
      onReload(
        result?.channel === "kept"
          ? "Clock removed. Its channel was not a voice channel, so it stays in Discord."
          : result?.channel === "deleted"
            ? "Clock and channel removed."
            : "Clock removed.",
      );
    } catch (reason) {
      setConfirmRemove(false);
      if (reason instanceof ApiError && reason.status === 409) {
        // Someone changed the clock. Show the new version instead of retrying a stale revision.
        onOpen(false);
        onReload(errorText(reason));
      } else setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  const statusLine = !enabled
    ? `Off · frozen${clock.last_name ? ` as ${clock.last_name}` : ""}`
    : problem
      ? problemText(clock)
      : clock.status === "waiting"
        ? clock.status_detail || "Waiting for the next update."
        : `${zoneCity(clock.zone)}${clock.last_renamed_at ? ` · renamed ${localTime(clock.last_renamed_at)}` : ""}`;

  return (
    <article
      ref={rowRef}
      className={`world-clock-row${problem ? " is-problem" : ""}${enabled ? "" : " is-off"}${open ? " is-open" : ""}`}
    >
      <div className="world-clock-row-main">
        <div className="world-clock-row-text">
          <ClockName
            name={
              enabled
                ? clock.name_now || discordName(clock)
                : discordName(clock)
            }
          />
          <p
            className={problem ? "world-clock-sub is-error" : "world-clock-sub"}
            role={problem ? "alert" : undefined}
          >
            {problem && (
              <Ban
                className="world-clock-sub-icon"
                size="1em"
                aria-hidden="true"
              />
            )}
            {statusLine}
          </p>
          {switchError && (
            <p className="world-clock-sub is-error" role="alert">
              {switchError}
            </p>
          )}
        </div>
        <label className={`world-clock-switch${problem ? " is-problem" : ""}`}>
          <input
            type="checkbox"
            role="switch"
            checked={enabled}
            disabled={switchBusy}
            aria-label={`Update ${clock.name_now || clock.zone}`}
            onChange={(event) => void toggle(event.target.checked)}
          />
          <span className="world-clock-switch-track" aria-hidden="true" />
          <span className="world-clock-switch-text">
            {enabled ? "On" : "Off"}
          </span>
        </label>
        <Button
          className="world-clock-edit"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => onOpen(!open)}
        >
          {open ? "Close" : problem ? "Fix" : "Edit"}
        </Button>
      </div>
      {open && (
        <div id={panelId} className="world-clock-panel">
          <ClockFields
            draft={draft}
            onChange={setDraft}
            chips={chips}
            usedZones={usedZones}
            disabled={busy}
          />
          <div>
            <SearchPicker
              label="Channel"
              triggerRef={channelRef}
              options={voiceChannels.map((channel) =>
                voiceOption(
                  channel,
                  channel.used && channel.id !== clock.channel_id
                    ? "has a clock"
                    : "",
                ),
              )}
              value={draft.channel_id}
              fallback={
                draft.channel_id
                  ? { value: draft.channel_id, label: "Missing channel" }
                  : undefined
              }
              placeholder="Select a voice channel"
              searchPlaceholder="Search voice channels"
              emptyText="No voice channels match."
              disabled={busy || !channelsAvailable}
              onChange={(channel_id) => setDraft({ ...draft, channel_id })}
            />
            <p className="world-clock-help">
              {channelsAvailable
                ? "Voice channels only. Use a channel no other app renames."
                : "Discord is unavailable, so the channel cannot change now."}
            </p>
          </div>
          {error && (
            <p className="world-clock-error" role="alert">
              {error}
            </p>
          )}
          <div className="world-clock-panel-actions">
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => setConfirmRemove(true)}
            >
              Remove clock
            </Button>
            <div className="world-clock-panel-save">
              <Button disabled={busy} onClick={() => onOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={busy || !dirty}
                onClick={() => void save()}
              >
                {busy ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      )}
      {confirmRemove && (
        <ConfirmDialog
          heading="Remove this clock?"
          text={
            clock.channel_id && !clock.channel_missing
              ? `This deletes the voice channel ${clock.channel_name || discordName(clock)} in Discord and removes the clock. This cannot be undone. To keep the channel, turn the clock off instead.`
              : "This removes the clock. It has no channel in Discord to delete."
          }
          confirmLabel={busy ? "Removing…" : "Remove clock"}
          danger
          disabled={busy}
          returnFocus={() =>
            rowRef.current?.querySelector<HTMLElement>(".world-clock-edit") ??
            null
          }
          onCancel={() => setConfirmRemove(false)}
          onConfirm={() => void remove()}
        />
      )}
    </article>
  );
}

function ClockName({ name }: { name: string }) {
  const { label, time } = nameParts(name);
  return (
    <p className="world-clock-name">
      {label}
      {time && (
        <>
          {" "}
          <span className="world-clock-time">· {time}</span>
        </>
      )}
    </p>
  );
}
