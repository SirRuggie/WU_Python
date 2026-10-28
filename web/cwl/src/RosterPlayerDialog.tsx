import DetailsFrame from "./DetailsFrame";
import ClanWeightSource from "./ClanWeightSource";
import ConfirmDialog from "./ConfirmDialog";
import ManualWeightFields from "./ManualWeightFields";
import { manualWeightDraft, parseManualWeight } from "./manualWeight";
import { useDashboardPermission } from "./DashboardPermissions";
import useUnsavedWork from "./useUnsavedWork";
import ClanDestinationOptions, {
  rosterDestinationMenuOptions,
} from "./ClanDestinationOptions";
import RosterMenu from "./rosterUi/Menu";
import { Button, StatusPill } from "./rosterUi/primitives";
import { ArrowRightLeft, Save, Trash2, UserMinus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { RosterAccount, RosterClan } from "./roster";
import type { Pool } from "./api";
import RosterDiscordIdentity from "./RosterDiscordIdentity";
import "./RosterPlayerDialog.css";

type Props = {
  previous?: () => void;
  next?: () => void;
  onClanWeights?: () => void;
  onDirty?: (dirty: boolean) => void;
  account: RosterAccount;
  clans: RosterClan[];
  busy: boolean;
  error?: string;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<boolean>;
  onRemove: () => Promise<boolean>;
  onPoolChange?: (pool: Pool) => Promise<boolean>;
  archived?: boolean;
  rosterUi?: boolean;
};

const fullWeight = (value: number | null) =>
  value === null ? "Missing weight" : value.toLocaleString();

/** React portal events can bubble through this component without belonging to its dialog. */
export function dialogOwnsEvent(
  dialog: Pick<HTMLDialogElement, "contains"> | null,
  target: EventTarget | null,
): boolean {
  return !!dialog && !!target && dialog.contains(target as Node);
}

const sourceStatus = (status: RosterAccount["source_status"]) =>
  status === "current"
    ? "Current"
    : status === "unavailable"
      ? "Source unavailable; prior value may be stale"
      : "Missing weight";

export default function RosterPlayerDialog({
  account,
  previous,
  next,
  onClanWeights,
  clans,
  busy,
  error,
  onClose,
  onSave,
  onRemove,
  onPoolChange,
  onDirty,
  archived = false,
  rosterUi = false,
}: Props) {
  const canRoster = useDashboardPermission("cwl_roster");
  const canSignups = useDashboardPermission("cwl_signups");
  const closeButton = useRef<HTMLButtonElement>(null);
  const unassignButton = useRef<HTMLButtonElement>(null);
  const removeButton = useRef<HTMLButtonElement>(null);
  const switchButton = useRef<HTMLButtonElement>(null);
  const pendingAction = useRef(false);
  const [weight, setWeight] = useState(
    manualWeightDraft(account.manual_weight),
  );
  const [clan, setClan] = useState(account.assigned_clan_tag || "");
  const [kept, setKept] = useState(account.kept);
  const [localError, setLocalError] = useState("");
  const [actionReview, setActionReview] = useState<
    "unassign" | "remove" | null
  >(null);
  const [poolReview, setPoolReview] = useState<Pool | null>(null);
  const currentHost = clans.find(
    (item) => item.tag === account.assigned_clan_tag,
  );
  const dirty =
    JSON.stringify(weight) !==
      JSON.stringify(manualWeightDraft(account.manual_weight)) ||
    clan !== (account.assigned_clan_tag || "") ||
    kept !== account.kept;
  useUnsavedWork(dirty || busy || !!poolReview || !!actionReview, onDirty);

  const close = () => {
    if (!busy && !pendingAction.current) onClose();
  };
  useEffect(() => {
    setWeight(manualWeightDraft(account.manual_weight));
    setClan(account.assigned_clan_tag || "");
    setKept(account.kept);
    setLocalError("");
    setActionReview(null);
    setPoolReview(null);
  }, [account.tag]);

  async function save() {
    if (!canRoster || archived || busy || pendingAction.current) return;
    try {
      const body: Record<string, unknown> = {};
      const value = account.clan_weight_managed
        ? account.manual_weight
        : parseManualWeight(weight);
      if (!account.clan_weight_managed && value !== account.manual_weight)
        body.manual_weight = value;
      if (clan !== (account.assigned_clan_tag || ""))
        body.assigned_clan_tag = clan || null;
      if (kept !== account.kept || clan !== (account.assigned_clan_tag || ""))
        body.kept = kept;
      if (!Object.keys(body).length) {
        onClose();
        return;
      }
      setLocalError("");
      pendingAction.current = true;
      try {
        if (await onSave(body)) onClose();
      } finally {
        pendingAction.current = false;
      }
    } catch (cause) {
      setLocalError(
        cause instanceof Error ? cause.message : "Could not save changes.",
      );
    }
  }

  async function confirmAction() {
    const action = actionReview;
    if (
      !action ||
      archived ||
      busy ||
      pendingAction.current ||
      dirty ||
      poolReview
    )
      return;
    if (
      action === "unassign"
        ? !canRoster || !account.assigned_clan_tag
        : !canSignups
    )
      return;
    pendingAction.current = true;
    let completed = false;
    setActionReview(null);
    setLocalError("");
    try {
      const success =
        action === "unassign"
          ? await onSave({ assigned_clan_tag: null, kept: false })
          : await onRemove();
      completed = success;
      if (success) onClose();
    } catch (cause) {
      setLocalError(
        cause instanceof Error
          ? cause.message
          : `Could not ${action === "unassign" ? "unassign account" : "remove signup"}.`,
      );
    } finally {
      pendingAction.current = false;
      if (!completed)
        requestAnimationFrame(() => {
          (action === "unassign"
            ? unassignButton
            : removeButton
          ).current?.focus({ preventScroll: true });
        });
    }
  }

  async function changePool() {
    if (
      !poolReview ||
      !onPoolChange ||
      !canSignups ||
      archived ||
      busy ||
      pendingAction.current
    )
      return;
    setLocalError("");
    pendingAction.current = true;
    try {
      if (await onPoolChange(poolReview)) onClose();
    } catch (cause) {
      setLocalError(
        cause instanceof Error
          ? cause.message
          : "Could not change signup type.",
      );
    } finally {
      pendingAction.current = false;
    }
  }

  return (
    <DetailsFrame
      tag={account.tag}
      name={account.player_name}
      dirty={dirty}
      busy={busy}
      onClose={onClose}
      previous={previous}
      next={next}
    >
      <section
        className="roster-player-dialog roster-ui is-roster-ui"
        aria-busy={busy}
      >
        <header>
          <h2 id="roster-player-title">{account.player_name}</h2>
          <button
            ref={closeButton}
            type="button"
            className={
              rosterUi ? "roster-ui roster-ui-button is-secondary" : undefined
            }
            disabled={busy}
            onClick={close}
          >
            {rosterUi ? (
              <>
                <X size={16} aria-hidden="true" /> Close
              </>
            ) : (
              "Close ×"
            )}
          </button>
        </header>
        <small>
          {account.tag} · TH {account.town_hall ?? "—"} ·{" "}
          {rosterUi ? (
            <StatusPill tone="info">
              {account.pool === "main" ? "Main" : "Lazy"} CWL
            </StatusPill>
          ) : (
            `${account.pool === "main" ? "Main" : "Lazy"} CWL`
          )}
        </small>
        <RosterDiscordIdentity userId={account.user_id} />
        <small className="roster-signup-time">
          Signed up:{" "}
          {account.signed_up_at &&
          Number.isFinite(Date.parse(account.signed_up_at)) ? (
            <time dateTime={account.signed_up_at}>
              {new Date(account.signed_up_at).toLocaleString(undefined, {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </time>
          ) : (
            "Not recorded"
          )}
        </small>
        <dl className="roster-player-context">
          <div>
            <dt>Current clan</dt>
            <dd>
              {account.current_clan_status === "unavailable" ||
              !account.current_clan_status
                ? "Unavailable"
                : account.current_clan_name ||
                  account.current_clan_tag ||
                  "No clan"}
              {account.current_clan_status === "stale" ? " · Last checked" : ""}
            </dd>
          </div>
          <div>
            <dt>Weight used</dt>
            <dd>{fullWeight(account.effective_weight)}</dd>
          </div>
        </dl>
        <details className="roster-player-source">
          <summary>Weight source &amp; saved details</summary>
          <dl className="roster-player-context">
            <div>
              <dt>Saved hosting clan</dt>
              <dd>
                {currentHost?.name || account.assigned_clan_tag || "Unassigned"}
                {currentHost?.archived ? " · Archived" : ""}
                <small>
                  {account.kept
                    ? "Kept placement"
                    : "Available for auto-placement"}
                </small>
              </dd>
            </div>
            <div>
              <dt>Weight used</dt>
              <dd>
                {fullWeight(account.effective_weight)}
                <small>
                  {account.clan_weight_managed
                    ? "Using Clan weights"
                    : account.manual_weight === null
                      ? "Using imported weight"
                      : `Manual override: ${fullWeight(account.manual_weight)}`}
                </small>
                {account.initial_manual_weight != null && (
                  <small>
                    First saved weight:{" "}
                    {fullWeight(account.initial_manual_weight)}
                  </small>
                )}
              </dd>
            </div>
            <div>
              <dt>Source weight</dt>
              <dd>
                {fullWeight(account.source_weight)}
                <small>
                  {sourceStatus(account.source_status)}
                  {account.source_name ? ` · ${account.source_name}` : ""}
                </small>
                {account.source_modified_at && (
                  <small>
                    Source updated{" "}
                    {new Date(account.source_modified_at).toLocaleString()}
                  </small>
                )}
                {account.source_checked_at && (
                  <small>
                    Fetched{" "}
                    {new Date(account.source_checked_at).toLocaleString()}
                  </small>
                )}
              </dd>
            </div>
          </dl>
        </details>
        {account.clan_weight_managed && (
          <ClanWeightSource onNavigate={onClanWeights} />
        )}
        {canRoster && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <fieldset
              disabled={busy || archived || !!poolReview || !!actionReview}
            >
              {!account.clan_weight_managed && (
                <>
                  <ManualWeightFields
                    value={weight}
                    onChange={setWeight}
                    disabled={busy || !canRoster}
                  />
                  <small>
                    Saved for future seasons. Leave blank to use source weight.
                  </small>
                </>
              )}
              {rosterUi ? (
                <RosterMenu
                  label="Hosting clan"
                  value={clan}
                  disabled={busy || archived || !!poolReview || !!actionReview}
                  onValueChange={(value) => {
                    setClan(value);
                    setKept(true);
                  }}
                  options={[
                    { value: "", label: "Not assigned" },
                    ...(account.assigned_clan_tag && currentHost?.archived
                      ? [
                          {
                            value: account.assigned_clan_tag,
                            label: `Archived clan · ${account.assigned_clan_tag}`,
                          },
                        ]
                      : []),
                    ...rosterDestinationMenuOptions(
                      clans,
                      account.pool,
                      account.assigned_clan_tag,
                    ),
                  ]}
                />
              ) : (
                <label>
                  Hosting clan
                  <select
                    value={clan}
                    onChange={(event) => {
                      setClan(event.target.value);
                      setKept(true);
                    }}
                  >
                    <option value="">Not assigned</option>
                    {account.assigned_clan_tag && currentHost?.archived && (
                      <option value={account.assigned_clan_tag}>
                        Archived clan · {account.assigned_clan_tag}
                      </option>
                    )}
                    <ClanDestinationOptions
                      clans={clans}
                      pool={account.pool}
                      current={account.assigned_clan_tag}
                    />
                  </select>
                </label>
              )}
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={kept}
                  onChange={(event) => setKept(event.target.checked)}
                />
                Lock placement
              </label>
              <small>Auto-place won’t move this account.</small>
              {rosterUi ? (
                <Button variant="primary" icon={Save} type="submit">
                  {busy ? "Saving…" : "Save changes"}
                </Button>
              ) : (
                <button className="primary" type="submit">
                  {busy ? "Saving…" : "Save changes"}
                </button>
              )}
            </fieldset>
          </form>
        )}
        {canRoster && (
          <small>
            Changes apply to the working roster. Publish again to update the
            published roster.
          </small>
        )}
        {busy && <p role="status">Saving account changes…</p>}
        {(localError || error) && <p role="alert">{localError || error}</p>}
        {archived && <p>Archived season · account changes are unavailable.</p>}
        {canSignups && !archived && (
          <section className="roster-player-signup" aria-label="Signup actions">
            <h3>Signup type</h3>
            <p>
              {account.pool === "main" ? "Main CWL" : "Lazy CWL"}
              {onPoolChange
                ? " · Switching type clears the working placement."
                : ""}
            </p>
            {onPoolChange &&
              (!poolReview ? (
                <button
                  ref={switchButton}
                  type="button"
                  className={
                    rosterUi
                      ? "roster-ui roster-ui-button is-secondary"
                      : undefined
                  }
                  disabled={busy || dirty}
                  onClick={() =>
                    setPoolReview(account.pool === "main" ? "lazy" : "main")
                  }
                >
                  {rosterUi && <ArrowRightLeft size={16} aria-hidden="true" />}
                  Switch to {account.pool === "main" ? "Lazy" : "Main"} CWL
                </button>
              ) : (
                <div
                  className="roster-player-pool-review"
                  role="group"
                  aria-label="Review signup type change"
                >
                  <strong>
                    Move {account.player_name} to{" "}
                    {poolReview === "main" ? "Main" : "Lazy"} CWL?
                  </strong>
                  <small>
                    Any working hosting-clan assignment will be cleared.
                    Published rosters stay unchanged until republished. Main CWL
                    eligibility is checked before saving.
                  </small>
                  <div>
                    {rosterUi ? (
                      <Button
                        icon={X}
                        disabled={busy}
                        onClick={() => {
                          setPoolReview(null);
                          requestAnimationFrame(() =>
                            switchButton.current?.focus({
                              preventScroll: true,
                            }),
                          );
                        }}
                      >
                        Cancel
                      </Button>
                    ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setPoolReview(null);
                          requestAnimationFrame(() =>
                            switchButton.current?.focus({
                              preventScroll: true,
                            }),
                          );
                        }}
                      >
                        Cancel
                      </button>
                    )}
                    {rosterUi ? (
                      <Button
                        variant="primary"
                        icon={ArrowRightLeft}
                        disabled={busy}
                        onClick={() => void changePool()}
                      >
                        {busy ? "Saving…" : "Confirm signup change"}
                      </Button>
                    ) : (
                      <button
                        type="button"
                        className="primary"
                        disabled={busy}
                        onClick={() => void changePool()}
                      >
                        {busy ? "Saving…" : "Confirm signup change"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
          </section>
        )}
        {(canRoster || canSignups) && !archived && (
          <section
            className="roster-player-remove"
            aria-label="Placement and signup actions"
          >
            {canRoster && (
              <div>
                <button
                  ref={unassignButton}
                  type="button"
                  className={
                    rosterUi
                      ? "roster-ui roster-ui-button is-secondary"
                      : undefined
                  }
                  disabled={
                    busy || !!poolReview || dirty || !account.assigned_clan_tag
                  }
                  onClick={() => setActionReview("unassign")}
                >
                  {rosterUi && <UserMinus size={16} aria-hidden="true" />}{" "}
                  Unassign from clan
                </button>
                <small>
                  {account.assigned_clan_tag
                    ? "Keeps the signup. Clears the clan and placement lock."
                    : "This account is already unassigned."}
                </small>
              </div>
            )}
            {canSignups && (
              <div>
                <button
                  ref={removeButton}
                  type="button"
                  className={
                    rosterUi ? "roster-ui roster-ui-button is-danger" : "danger"
                  }
                  disabled={busy || !!poolReview || dirty}
                  onClick={() => setActionReview("remove")}
                >
                  {rosterUi && <Trash2 size={16} aria-hidden="true" />} Remove
                  signup
                </button>
                <small>
                  Removes this season’s signup and placement. Saved weights
                  stay.
                </small>
              </div>
            )}
            {dirty && (
              <small>Save your changes before using these actions.</small>
            )}
          </section>
        )}
        {actionReview && (
          <ConfirmDialog
            heading={
              actionReview === "unassign"
                ? "Unassign from clan?"
                : "Remove signup?"
            }
            text={
              actionReview === "unassign"
                ? `${account.player_name} will be unassigned from ${currentHost?.name || account.assigned_clan_tag}. Their signup and saved weight stay. The placement lock is cleared. Publish again to update the published roster.`
                : `Remove ${account.player_name} from this season’s signup and working roster? Saved weights stay. Publish again to update the published roster.`
            }
            confirmLabel={
              actionReview === "unassign"
                ? "Unassign from clan"
                : "Remove signup"
            }
            disabled={busy}
            onCancel={() => setActionReview(null)}
            onConfirm={() => void confirmAction()}
          />
        )}
      </section>
    </DetailsFrame>
  );
}
