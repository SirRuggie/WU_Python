import { useEffect, useRef, useState, type ReactNode } from "react";
import DetailsFrame from "./DetailsFrame";
import ClanWeightSource from "./ClanWeightSource";
import ConfirmDialog from "./ConfirmDialog";
import CompactWeightField from "./CompactWeightField";
import PlayerClanStatus, { playerClanStatus } from "./PlayerClanStatus";
import useLocationNow from "./useLocationNow";
import {
  mergeComparisonLocations,
  type LocationRecords,
} from "./comparisonLocation";
import "./WeightQueue.css";
import { parseManualWeight, type ManualWeightDraft } from "./manualWeight";
import { useDashboardPermission } from "./DashboardPermissions";
import useUnsavedWork from "./useUnsavedWork";
import { Button } from "./rosterUi/primitives";
import { ArrowRightLeft, Trash2, UserMinus } from "lucide-react";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";
import type { Pool } from "./api";
import RosterDiscordIdentity from "./RosterDiscordIdentity";
import RosterAssignPanel from "./RosterAssignPanel";
import PlayerCardMeta from "./PlayerCardMeta";
import TownHallIcon from "./TownHallIcon";
import "./RosterPlayerDialog.css";

type Props = {
  previous?: () => void;
  next?: () => void;
  onClanWeights?: () => void;
  onDirty?: (dirty: boolean) => void;
  account: RosterAccount;
  clans: RosterClan[];
  roster?: RosterSnapshot;
  undo?: ReactNode;
  locations?: LocationRecords;
  busy: boolean;
  error?: string;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<boolean>;
  onRemove: () => Promise<boolean>;
  onPoolChange?: (pool: Pool) => Promise<boolean>;
  archived?: boolean;
  rosterUi?: boolean;
};
export function dialogOwnsEvent(
  dialog: Pick<HTMLDialogElement, "contains"> | null,
  target: EventTarget | null,
): boolean {
  return !!dialog && !!target && dialog.contains(target as Node);
}
const detailsWeightDraft = (weight: number | null): ManualWeightDraft => ({
  unit: "loot",
  text: weight === null ? "" : String(weight / 5),
});
const fullWeight = (value: number | null) =>
  value === null ? "Missing weight" : value.toLocaleString();
export const detailsDate = (value?: string | null) =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "Not recorded";

export default function RosterPlayerDialog({
  account,
  previous,
  next,
  onClanWeights,
  clans,
  roster,
  undo,
  locations,
  busy,
  error,
  onClose,
  onSave,
  onRemove,
  onPoolChange,
  onDirty,
  archived = false,
}: Props) {
  const [now] = useLocationNow();
  const locationCache = useRef<LocationRecords>({});
  locationCache.current = mergeComparisonLocations(locationCache.current, [
    {
      ...account,
      current_clan_tag: account.current_clan_tag ?? null,
      current_clan_name: account.current_clan_name ?? null,
    },
    ...Object.entries(locations || {}).map(([tag, value]) => ({
      ...value,
      tag,
    })),
  ]);
  const weightInput = useRef<HTMLInputElement>(null);
  const canRoster = useDashboardPermission("cwl_roster");
  const canSignups = useDashboardPermission("cwl_signups");
  const pending = useRef(false);
  const assignTrigger = useRef<HTMLButtonElement>(null);
  const [weight, setWeight] = useState(
    detailsWeightDraft(account.manual_weight),
  );
  const [localError, setLocalError] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [review, setReview] = useState<"unassign" | "remove" | "pool" | null>(
    null,
  );
  const currentHost = clans.find((c) => c.tag === account.assigned_clan_tag);
  const dirty =
    JSON.stringify(weight) !==
    JSON.stringify(detailsWeightDraft(account.manual_weight));
  useUnsavedWork(dirty || busy, onDirty);
  useEffect(() => {
    setWeight(detailsWeightDraft(account.manual_weight));
  }, [account.tag, account.manual_weight]);
  useEffect(() => {
    setLocalError("");
    setAssignOpen(false);
    setReview(null);
  }, [account.tag]);
  async function run(action: () => Promise<boolean>) {
    if (pending.current || busy || archived) return false;
    pending.current = true;
    setLocalError("");
    try {
      return await action();
    } catch (cause) {
      setLocalError(
        cause instanceof Error ? cause.message : "Could not save changes.",
      );
      return false;
    } finally {
      pending.current = false;
    }
  }
  async function saveWeight() {
    if (!canRoster || account.clan_weight_managed) return;
    try {
      const value = parseManualWeight(weight);
      if (value !== account.manual_weight)
        await run(() => onSave({ manual_weight: value }));
    } catch (cause) {
      setLocalError((cause as Error).message);
    }
  }
  const targetPool: Pool = account.pool === "main" ? "lazy" : "main";
  async function confirm() {
    if (!review || dirty) return;
    const action = review;
    if (action === "unassign" ? !canRoster : !canSignups) return;
    const success = await run(() =>
      action === "remove"
        ? onRemove()
        : action === "pool"
          ? (onPoolChange?.(targetPool) ?? Promise.resolve(false))
          : onSave({ assigned_clan_tag: null, kept: false }),
    );
    if (success) {
      setReview(null);
      if (action === "remove") onClose();
    }
  }
  const source = account.clan_weight_managed
    ? "Clan weights"
    : account.manual_weight !== null
      ? "Manual"
      : "Imported";
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
      <section className="roster-player-dialog roster-ui" aria-busy={busy}>
        <header className="details-player-heading">
          <h2>
            <TownHallIcon level={account.town_hall} />
            {account.player_name}
          </h2>
          <PlayerCardMeta account={account} />
          <RosterDiscordIdentity userId={account.user_id} />
        </header>
        <section aria-label="At a glance">
          <h3>At a glance</h3>
          <p>
            {currentHost
              ? `Assigned: ${currentHost.name}`
              : account.assigned_clan_tag
                ? `Assigned: ${account.assigned_clan_tag}`
                : "Not assigned"}
            {account.kept ? " · Locked" : ""}
          </p>
          <PlayerClanStatus
            status={playerClanStatus(
              account.assigned_clan_tag,
              currentHost?.name || account.assigned_clan_tag || "Not assigned",
              locationCache.current[account.tag] || {},
              now,
            )}
          />
          <p>
            Weight {fullWeight(account.effective_weight)} · {source}
          </p>
        </section>
        {canRoster && !archived && (
          <section aria-label="Placement">
            <h3>Placement</h3>
            <Button
              disabled={busy || dirty || !roster}
              onClick={(event) => {
                assignTrigger.current = event.currentTarget;
                setAssignOpen(true);
              }}
            >
              Change clan
            </Button>
            <label className="details-lock">
              <input
                type="checkbox"
                checked={account.kept}
                disabled={busy || dirty}
                onChange={(event) =>
                  void run(() => onSave({ kept: event.target.checked }))
                }
              />
              Lock placement
            </label>
            <Button
              icon={UserMinus}
              disabled={busy || dirty || !account.assigned_clan_tag}
              onClick={() => setReview("unassign")}
            >
              Unassign from clan
            </Button>
            <small>
              Changes apply to the working roster. Publish again to update the
              published roster.
            </small>
          </section>
        )}
        {canRoster && !archived && (
          <section aria-label="Weight">
            <h3>Weight</h3>
            {account.clan_weight_managed ? (
              <ClanWeightSource onNavigate={onClanWeights} />
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveWeight();
                }}
              >
                <CompactWeightField
                  value={weight}
                  onChange={setWeight}
                  disabled={busy}
                  inputRef={weightInput}
                  name={account.player_name}
                  allowClear
                />
                <small>Leave blank to use source weight.</small>
              </form>
            )}
          </section>
        )}
        <details className="roster-player-source">
          <summary>Source &amp; history</summary>
          <dl>
            <dt>Source weight</dt>
            <dd>
              {fullWeight(account.source_weight)} · {account.source_status}
              {account.source_name ? ` · ${account.source_name}` : ""}
            </dd>
            <dt>First saved weight</dt>
            <dd>{fullWeight(account.initial_manual_weight ?? null)}</dd>
            <dt>Source updated</dt>
            <dd>{detailsDate(account.source_modified_at)}</dd>
            <dt>Fetched</dt>
            <dd>{detailsDate(account.source_checked_at)}</dd>
          </dl>
        </details>
        {canSignups && !archived && (
          <section aria-label="Signup">
            <h3>Signup</h3>
            <p>{account.pool === "main" ? "Main CWL" : "Lazy CWL"}</p>
            {onPoolChange && (
              <Button
                icon={ArrowRightLeft}
                disabled={busy || dirty}
                onClick={() => setReview("pool")}
              >
                Switch to {targetPool === "main" ? "Main" : "Lazy"} CWL
              </Button>
            )}
          </section>
        )}
        {canSignups && !archived && (
          <section aria-label="Danger area">
            <h3>Danger area</h3>
            <Button
              icon={Trash2}
              variant="danger"
              disabled={busy || dirty}
              onClick={() => setReview("remove")}
            >
              Remove signup
            </Button>
            <small>
              Removes this season’s signup and placement. Saved weights stay.
            </small>
          </section>
        )}
        {(localError || error) && <p role="alert">{localError || error}</p>}
        {busy && <p role="status">Saving account changes…</p>}
        <footer>Signed up {detailsDate(account.signed_up_at)}</footer>
        {undo}
        {assignOpen && roster && (
          <RosterAssignPanel
            roster={roster}
            selectedAccounts={[account]}
            hiddenTags={[]}
            busy={busy}
            trigger={assignTrigger.current}
            onClose={() => setAssignOpen(false)}
            onAssign={async (destination) => {
              if (destination === null) {
                setAssignOpen(false);
                setReview("unassign");
                return true;
              }
              return run(() =>
                onSave({ assigned_clan_tag: destination, kept: true }),
              );
            }}
          />
        )}
        {review && (
          <ConfirmDialog
            heading={
              review === "unassign"
                ? "Unassign from clan?"
                : review === "remove"
                  ? "Remove signup?"
                  : `Switch to ${targetPool === "main" ? "Main" : "Lazy"} CWL?`
            }
            text={
              review === "unassign"
                ? `${account.player_name} will be unassigned from ${currentHost?.name || account.assigned_clan_tag}. Their signup and saved weight stay. The placement lock is cleared. Publish again to update the published roster.`
                : review === "remove"
                  ? `Remove ${account.player_name} from this season’s signup and working roster? Saved weights stay. Publish again to update the published roster.${account.kept ? " This account has a locked placement." : ""}`
                  : `${account.player_name}: switching signup type clears the working placement and lock and is visible to members. Published rosters stay unchanged until republished. Main CWL eligibility is checked before saving.${account.kept ? " This account has a locked placement." : ""}`
            }
            confirmLabel={
              review === "unassign"
                ? "Unassign from clan"
                : review === "remove"
                  ? "Remove signup"
                  : "Confirm signup change"
            }
            disabled={busy}
            onCancel={() => setReview(null)}
            onConfirm={() => void confirm()}
          />
        )}
      </section>
    </DetailsFrame>
  );
}
