import { useCallback, useEffect, useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import BonusRepAccounts from "./BonusRepAccounts";
import useConfirmDialog from "./useConfirmDialog";
import { api, ApiError } from "./api";
import { exportMonthLabel } from "./exportPreview";
import { resultTimeText } from "./participationOutcome";
import {
  validCwlCycle,
  type ParticipationData,
  type ParticipationSync,
} from "./participation";
import type { RaffleData, RepAccount } from "./bonusRaffle";
import "./ResultsSettingsSheet.css";

type Draft = {
  cycle: string;
  enabled: boolean;
  expected_updated_at: string | null;
};
export type SettingsSaved = {
  kind: "capture" | "odds";
  /** The CWL month moved, so loaded results no longer match. */
  cycleChanged?: boolean;
  enabled?: boolean;
};
type Props = {
  seasonId: string;
  /** Results access: the CWL capture section. */
  canCapture: boolean;
  /** Bonus access: the FWA Rep accounts section. */
  canOdds: boolean;
  archived: boolean;
  /** Unsaved result edits in the page behind the sheet. */
  dirtyResults?: number;
  trigger: HTMLElement | null;
  onDirty: (dirty: boolean) => void;
  onClose: () => void;
  onSaved: (saved: SettingsSaved) => void | Promise<void>;
};

const errorText = (cause: unknown) =>
  cause instanceof Error
    ? cause.message
    : "Settings could not be saved. Refresh to check their saved status.";

/** CWL capture and FWA Rep accounts in one sheet, off the results and bonus flow. */
export default function ResultsSettingsSheet({
  seasonId,
  canCapture,
  canOdds,
  archived,
  dirtyResults = 0,
  trigger,
  onDirty,
  onClose,
  onSaved,
}: Props) {
  const { confirm, dialog: confirmation } = useConfirmDialog(seasonId);
  const sid = useRef(seasonId);
  sid.current = seasonId;
  const base = `/seasons/${encodeURIComponent(seasonId)}`;
  const [sync, setSync] = useState<ParticipationSync | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [captureDirty, setCaptureDirty] = useState(false);
  const [captureError, setCaptureError] = useState("");
  const [captureLoading, setCaptureLoading] = useState(canCapture);
  const [revision, setRevision] = useState<number | null>(null);
  const [repAccounts, setRepAccounts] = useState<RepAccount[]>([]);
  const [repDirty, setRepDirty] = useState(false);
  const [oddsError, setOddsError] = useState("");
  const [oddsLoading, setOddsLoading] = useState(canOdds);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const dirty = captureDirty || (canOdds && repDirty);
  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);

  const loadCapture = useCallback(async () => {
    if (!canCapture) return;
    setCaptureLoading(true);
    try {
      const result = await api<ParticipationData>(`${base}/participation`);
      if (!result.sync) throw new Error("Capture settings are unavailable.");
      setSync(result.sync);
      setDraft({
        cycle: result.sync.cycle || "",
        enabled: result.sync.enabled,
        expected_updated_at: result.sync.updated_at ?? null,
      });
      setCaptureDirty(false);
      setCaptureError("");
    } catch (cause) {
      setCaptureError(errorText(cause));
    } finally {
      setCaptureLoading(false);
    }
  }, [base, canCapture]);
  const takeOdds = (result: RaffleData) => {
    setRevision(result.revision);
    setRepAccounts(result.rep_accounts || []);
  };
  const loadOdds = useCallback(async () => {
    if (!canOdds) return;
    setOddsLoading(true);
    try {
      takeOdds(await api<RaffleData>(`${base}/bonus-raffle`));
      setOddsError("");
    } catch (cause) {
      setOddsError(errorText(cause));
    } finally {
      setOddsLoading(false);
    }
  }, [base, canOdds]);
  useEffect(() => {
    void loadCapture();
    if (canOdds) void loadOdds();
  }, [loadCapture, loadOdds, canOdds]);

  const saveCapture = async () => {
    if (
      !draft ||
      busy ||
      pending.current ||
      archived ||
      !validCwlCycle(draft.cycle)
    )
      return;
    const cycleChanged = draft.cycle !== sync?.cycle;
    if (
      cycleChanged &&
      dirtyResults &&
      !(await confirm(
        `Changing the CWL month will discard unsaved result edits for ${dirtyResults} account${dirtyResults === 1 ? "" : "s"}. Continue?`,
        "Change CWL month",
      ))
    )
      return;
    const season = seasonId;
    pending.current = true;
    setBusy(true);
    setCaptureError("");
    setNotice("");
    try {
      const result = await api<{ sync: ParticipationSync }>(
        `${base}/participation/sync-settings`,
        "POST",
        draft,
      );
      if (sid.current !== season) return;
      setSync(result.sync);
      setDraft({
        cycle: result.sync.cycle || "",
        enabled: result.sync.enabled,
        expected_updated_at: result.sync.updated_at ?? null,
      });
      setCaptureDirty(false);
      setNotice(
        result.sync.enabled
          ? "Automatic CWL capture enabled."
          : "Automatic CWL capture disabled. You can still check manually.",
      );
      await onSaved({
        kind: "capture",
        cycleChanged,
        enabled: result.sync.enabled,
      });
    } catch (cause) {
      if (sid.current === season) {
        // A conflict loads the latest settings and keeps its message.
        if (cause instanceof ApiError && cause.status === 409)
          await loadCapture();
        setCaptureError(errorText(cause));
      }
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const mutateRep = async (
    method: "POST" | "PATCH" | "DELETE",
    body: Record<string, unknown>,
    message: string,
  ) => {
    if (busy || pending.current || archived || revision === null) return false;
    const season = seasonId;
    pending.current = true;
    setBusy(true);
    setOddsError("");
    setNotice("");
    try {
      const result = await api<RaffleData>(
        `${base}/bonus-raffle/rep-accounts`,
        method,
        { ...body, revision },
      );
      if (sid.current !== season) return false;
      takeOdds(result);
      setNotice(message);
      await onSaved({ kind: "odds" });
      return true;
    } catch (cause) {
      if (sid.current === season) {
        // A conflict loads the latest list and keeps its message.
        if (cause instanceof ApiError && cause.status === 409) await loadOdds();
        setOddsError(errorText(cause));
      }
      return false;
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const requestClose = () => {
    if (!dirty) {
      onClose();
      return undefined;
    }
    void confirm("Discard unsaved settings?", "Discard settings").then(
      (discard) => {
        if (discard) onClose();
      },
    );
    // false keeps the Back entry while the discard question is open.
    return false;
  };

  const captureLocked = archived || busy || captureLoading || !draft;
  return (
    <>
      {confirmation}
      <ActionPanel
        title="Settings"
        className="results-settings"
        trigger={trigger}
        busy={busy}
        onClose={requestClose}
      >
        {archived && <p className="notice">Archived season · Read only</p>}
        {notice && <p role="status">{notice}</p>}
        {canCapture && (
          <section
            className="results-settings-section"
            aria-label="CWL capture"
          >
            <h3>CWL capture{captureDirty ? " · Unsaved" : ""}</h3>
            {captureLoading && <p role="status">Loading capture settings…</p>}
            {captureError && (
              <p role="alert">
                {captureError}{" "}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void loadCapture()}
                >
                  Retry
                </button>
              </p>
            )}
            {draft && (
              <>
                <div className="results-settings-fields">
                  <label>
                    CWL month
                    <input
                      type="month"
                      name="cwl-month"
                      autoComplete="off"
                      value={draft.cycle}
                      disabled={captureLocked}
                      onChange={(event) => {
                        setDraft({ ...draft, cycle: event.target.value });
                        setCaptureDirty(true);
                      }}
                    />
                  </label>
                  <label className="results-settings-toggle">
                    <input
                      type="checkbox"
                      name="capture-enabled"
                      checked={draft.enabled}
                      disabled={captureLocked}
                      onChange={(event) => {
                        setDraft({ ...draft, enabled: event.target.checked });
                        setCaptureDirty(true);
                      }}
                    />
                    Check automatically every 15 minutes
                  </label>
                </div>
                <div className="results-settings-meta">
                  <small>
                    {sync?.cycle
                      ? exportMonthLabel(sync.cycle)
                      : "CWL month not set"}{" "}
                    · Month source:{" "}
                    {sync?.cycle_source === "manage_binding"
                      ? "Manage CWL settings"
                      : sync?.cycle_source === "settings"
                        ? "Staff setting"
                        : "None"}
                  </small>
                  <small>
                    Last success:{" "}
                    {sync?.last_success_at ? (
                      <time dateTime={sync.last_success_at}>
                        {resultTimeText(sync.last_success_at)}
                      </time>
                    ) : (
                      "Never"
                    )}
                  </small>
                </div>
                {captureDirty && (
                  <div className="results-settings-actions">
                    <button
                      type="button"
                      disabled={captureLocked || !validCwlCycle(draft.cycle)}
                      onClick={() => void saveCapture()}
                    >
                      Save capture settings
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void loadCapture()}
                    >
                      Discard changes
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        )}
        {canOdds && (
          <>
            {oddsLoading && <p role="status">Loading FWA Rep accounts…</p>}
            {oddsError && (
              <p role="alert">
                {oddsError}{" "}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void loadOdds()}
                >
                  Refresh
                </button>
              </p>
            )}
            {revision !== null && (
              <BonusRepAccounts
                accounts={repAccounts}
                disabled={busy || archived}
                onDirty={setRepDirty}
                onConfirm={confirm}
                onMutate={mutateRep}
              />
            )}
          </>
        )}
      </ActionPanel>
    </>
  );
}
