import RosterFillerCheckbox from "./RosterFillerCheckbox";
import { useEffect, useRef, useState, type ReactNode } from "react";
import DetailsFrame from "./DetailsFrame";
import ClanWeightSource from "./ClanWeightSource";
import ConfirmDialog from "./ConfirmDialog";
import LinkedWeightField from "./LinkedWeightField";
import PlayerClanStatus, { playerClanStatus } from "./PlayerClanStatus";
import useLocationNow from "./useLocationNow";
import {
  mergeComparisonLocations,
  type LocationRecords,
} from "./comparisonLocation";
import "./WeightQueue.css";
import { draftFor, validateDraft, type Draft } from "./weightTrial/model";
import { useDashboardPermission } from "./DashboardPermissions";
import useUnsavedWork from "./useUnsavedWork";
import { Button } from "./rosterUi/primitives";
import { ArrowRightLeft, Trash2, UserMinus } from "lucide-react";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";
import type { Pool } from "./api";
import DiscordIdentity from "./DiscordIdentity";
import RosterAssignPanel from "./RosterAssignPanel";
import PlayerCardMeta from "./PlayerCardMeta";
import TownHallIcon from "./TownHallIcon";
import "./PlayerCard.css";
import "./RosterPlayerDialog.css";

type Props = {
  seasonId?: string;
  previous?: () => void;
  next?: () => void;
  onClanWeights?: (player?: string, clan?: string) => void;
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
  onReload?: () => Promise<void>;
  onRemove: () => Promise<boolean>;
  onPoolChange?: (pool: Pool) => Promise<boolean>;
  archived?: boolean;
  viewOnly?: "declaration";
  publicationNote?: string;
  rosterUi?: boolean;
};
const detailsWeightDraft = (account: RosterAccount): Draft =>
  draftFor({
    tag: account.tag,
    name: account.player_name,
    town_hall: account.town_hall,
    weight:
      account.effective_weight !== null && account.effective_weight % 1000 !== 0
        ? null
        : account.effective_weight,
    revision: account.weight_revision ?? 0,
    storages: account.weight_storages ?? undefined,
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
  seasonId,
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
  onReload,
  onPoolChange,
  onDirty,
  archived = false,
  viewOnly,
  publicationNote,
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
  const rosterPermission = useDashboardPermission("cwl_roster");
  const canRoster = rosterPermission && !archived && !viewOnly;
  const weightPermission = useDashboardPermission("clan_weights");
  const canWeight = canRoster && weightPermission;
  const signupPermission = useDashboardPermission("cwl_signups");
  const canSignups = signupPermission && !archived && !viewOnly;
  const reason = archived
    ? "Archived season · view only"
    : viewOnly === "declaration"
      ? "View only here · change placements in Build roster ›"
      : !rosterPermission
        ? "View only · you don't have roster editing access"
        : "";
  const pending = useRef(false);
  const assignTrigger = useRef<HTMLButtonElement>(null);
  const [weight, setWeight] = useState(detailsWeightDraft(account));
  const [clearRequested, setClearRequested] = useState(false);
  const baseline = useRef({
    tag: account.tag,
    draft: detailsWeightDraft(account),
  });
  const [localError, setLocalError] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [review, setReview] = useState<"unassign" | "remove" | "pool" | null>(
    null,
  );
  const currentHost = clans.find((c) => c.tag === account.assigned_clan_tag);
  const unusualWeight =
    account.effective_weight !== null && account.effective_weight % 1000 !== 0;
  const dirty =
    canWeight &&
    ((clearRequested && unusualWeight && !weight.full && !weight.loot) ||
      JSON.stringify(weight) !== JSON.stringify(detailsWeightDraft(account)));
  useUnsavedWork(dirty || busy, onDirty);
  useEffect(() => {
    setClearRequested(false);
    const previous = baseline.current;
    const draft = detailsWeightDraft(account);
    setWeight((current) =>
      previous.tag !== account.tag ||
      JSON.stringify(current) === JSON.stringify(previous.draft)
        ? draft
        : current,
    );
    baseline.current = { tag: account.tag, draft };
  }, [account.tag, account.effective_weight, account.weight_storages]);
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
    if (!canWeight) return;
    try {
      const value = validateDraft(weight);
      if (
        !dirty ||
        (await run(() =>
          onSave({
            manual_weight: value.weight,
            weight_revision: account.weight_revision ?? 0,
            weight_storages: value.storages,
          }),
        ))
      ) {
        setClearRequested(false);
        setWeight(
          detailsWeightDraft({
            ...account,
            effective_weight: value.weight,
            weight_storages: value.storages,
          }),
        );
      }
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
          <DiscordIdentity userId={account.user_id} />
        </header>
        {seasonId && roster && rosterPermission && !archived && (
          <RosterFillerCheckbox
            seasonId={seasonId}
            tag={account.tag}
            name={account.player_name}
            value={!!account.roster_filler}
            markRevision={account.roster_filler_revision || 0}
            revision={roster.revision}
            disabled={busy || dirty}
            onChanged={async () => {
              await onReload?.();
            }}
          />
        )}
        {reason && (
          <p className="details-view-only">
            {viewOnly === "declaration" && !archived ? (
              <>
                View only here · change placements in{" "}
                <a
                  href={`/cwl/roster?season=${encodeURIComponent(new URLSearchParams(location.search).get("season") || "")}&account=${encodeURIComponent(account.tag)}`}
                >
                  Build roster ›
                </a>
              </>
            ) : (
              reason
            )}
          </p>
        )}
        {publicationNote && (
          <p className="details-view-only">{publicationNote}</p>
        )}
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
            showAssigned={false}
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
            {!canWeight && (
              <p>
                {fullWeight(account.effective_weight)} · View only · Clan
                weights access required
              </p>
            )}
            {unusualWeight && (
              <p>
                Saved weight: {fullWeight(account.effective_weight)}. Saved
                value isn't a whole thousand. Enter a new one to change it.
              </p>
            )}
            {canWeight && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveWeight();
                }}
              >
                <LinkedWeightField
                  value={weight}
                  onChange={setWeight}
                  disabled={busy}
                  name={account.player_name}
                  unchanged={!dirty}
                  allowEmptyClear={unusualWeight}
                  onClear={() => setClearRequested(true)}
                />
              </form>
            )}
            <ClanWeightSource
              account={account}
              onNavigate={onClanWeights}
              compact
            />
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
        {(localError || error)?.includes("Changed by someone else") &&
          onReload && (
            <Button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await onReload();
                  return true;
                })
              }
            >
              Reload
            </Button>
          )}
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
            danger={review === "remove"}
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
