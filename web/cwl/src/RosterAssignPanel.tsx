import { useMemo, useRef, useState } from "react";
import { Input, ProgressBar } from "./rosterUi/primitives";
import { ChevronRight, Search, Unlink } from "lucide-react";
import ActionPanel from "./ActionPanel";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";
import { compactRosterWeight } from "./rosterCompactWeight";
import "./RosterAssignPanel.css";

type Props = {
  roster: RosterSnapshot;
  selectedAccounts: RosterAccount[];
  hiddenTags: string[];
  busy: boolean;
  trigger: HTMLElement | null;
  onClose: () => void;
  onAssign: (destination: string | null) => Promise<boolean>;
};

type Destination = {
  clan: RosterClan;
  currentCount: number;
  projectedCount: number;
  incomingCount: number;
  currentAverageWeight: number | null;
  currentKnownWeights: number;
};

function destinationProjection(
  clan: RosterClan,
  roster: RosterSnapshot,
  selected: RosterAccount[],
): Destination {
  const currentAccounts = roster.accounts.filter(
    (account) => account.assigned_clan_tag === clan.tag,
  );
  const currentCount = clan.assigned_count;
  const incomingCount = selected.filter(
    (account) => account.assigned_clan_tag !== clan.tag,
  ).length;
  const weights = currentAccounts
    .map((account) => account.effective_weight)
    .filter((weight): weight is number => weight !== null);
  return {
    clan,
    currentCount,
    projectedCount: currentCount + incomingCount,
    incomingCount,
    currentAverageWeight: weights.length
      ? weights.reduce((total, weight) => total + weight, 0) / weights.length
      : null,
    currentKnownWeights: weights.length,
  };
}

export default function RosterAssignPanel({
  roster,
  selectedAccounts,
  hiddenTags,
  busy,
  trigger,
  onClose,
  onAssign,
}: Props) {
  const pending = useRef(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState("");
  const hidden = new Set(hiddenTags);
  const reviewAccounts = [...selectedAccounts].sort(
    (left, right) =>
      Number(hidden.has(right.tag)) - Number(hidden.has(left.tag)),
  );
  const pools = new Set(selectedAccounts.map((account) => account.pool));
  const pool = pools.size === 1 ? selectedAccounts[0]?.pool : null;
  const destinations = useMemo(
    () =>
      roster.clans
        .filter((clan) => !clan.archived && pool !== null && clan.pool === pool)
        .map((clan) => destinationProjection(clan, roster, selectedAccounts))
        .sort((left, right) => left.clan.name.localeCompare(right.clan.name)),
    [pool, roster, selectedAccounts],
  );
  const term = search.trim().toLocaleLowerCase();
  const shownDestinations = term
    ? destinations.filter(({ clan }) =>
        [clan.name, clan.tag].some((value) =>
          value.toLocaleLowerCase().includes(term),
        ),
      )
    : destinations;
  const locked = selectedAccounts.filter((account) => account.kept);
  const canUnassign = selectedAccounts.some(
    (account) => account.assigned_clan_tag !== null,
  );
  const unavailable =
    busy ||
    submitting ||
    selectedAccounts.length === 0 ||
    selectedAccounts.length > 50;

  const assign = async (destination: string | null) => {
    if (
      unavailable ||
      pending.current ||
      (destination === null && !canUnassign)
    )
      return;
    pending.current = true;
    setSubmitting(true);
    setError("");
    try {
      if (await onAssign(destination)) onClose();
      else
        setError(
          "Could not confirm the assignment. Review the roster status before trying again.",
        );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not confirm the assignment. Refresh the roster before trying again.",
      );
    } finally {
      pending.current = false;
      setSubmitting(false);
    }
  };

  return (
    <ActionPanel
      className="roster-ui"
      title="Assign selected accounts"
      trigger={trigger}
      busy={busy || submitting}
      expandOnSearchFocus
      onClose={() => {
        if (!pending.current) onClose();
      }}
    >
      <div className="roster-assign-panel">
        <p className="roster-assign-intro">
          Assign {selectedAccounts.length} account
          {selectedAccounts.length === 1 ? "" : "s"}
          {" · "}manual assignment locks placement
        </p>
        {pool !== null && (
          <label className="roster-assign-search">
            Search hosting clans
            <Input
              icon={Search}
              type="search"
              value={search}
              disabled={busy || submitting}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name or clan tag"
            />
          </label>
        )}
        {hiddenTags.length > 0 && (
          <p className="roster-assign-warning">
            {hiddenTags.length} selected account
            {hiddenTags.length === 1 ? " is" : "s are"} not visible in the list
            and will be included below.
          </p>
        )}
        {pool === null && selectedAccounts.length > 0 && (
          <p className="roster-assign-warning">
            Main and Lazy accounts are selected together. Unassign is available;
            choose one pool to assign a clan.
          </p>
        )}
        {(pool !== null || canUnassign) && (
          <section
            className="roster-assign-destinations"
            aria-label="Hosting clan destinations"
          >
            <div className="roster-assign-destinations-heading">
              <h3>
                {pool === null
                  ? "Placement"
                  : `${pool === "main" ? "Main" : "Lazy"} CWL hosting clans`}
              </h3>
              {pool !== null && (
                <small>
                  {shownDestinations.length} of {destinations.length}
                </small>
              )}
            </div>
            {pool !== null && destinations.length === 0 && (
              <p>No active hosting clans are available for this pool.</p>
            )}
            {pool !== null &&
              destinations.length > 0 &&
              shownDestinations.length === 0 && (
                <p>No hosting clans match “{search.trim()}”.</p>
              )}
            <ul>
              {shownDestinations.map(
                ({
                  clan,
                  currentCount,
                  projectedCount,
                  incomingCount,
                  currentAverageWeight,
                  currentKnownWeights,
                }) => {
                  const currentlyFull = currentCount >= clan.effective_capacity;
                  const projectedOverCapacity =
                    projectedCount > clan.effective_capacity;
                  const unavailableDestination =
                    currentlyFull || projectedOverCapacity;
                  const unchanged = incomingCount === 0;
                  const disabled =
                    unavailable || unavailableDestination || unchanged;
                  const reason = currentlyFull
                    ? "Full"
                    : projectedOverCapacity
                      ? "Over capacity"
                      : unchanged
                        ? "Already assigned"
                        : null;
                  return (
                    <li key={clan.tag}>
                      <button
                        type="button"
                        className="roster-assign-clan"
                        disabled={disabled}
                        onClick={() => void assign(clan.tag)}
                      >
                        <span className="roster-assign-clan-head">
                          <span className="roster-assign-clan-name">
                            <span className="roster-assign-visually-hidden">
                              Assign selected accounts to{" "}
                            </span>
                            <strong>{clan.name}</strong>{" "}
                            <small>{clan.tag}</small>
                          </span>
                          <span className="roster-assign-clan-count">
                            {currentCount} → {projectedCount} /{" "}
                            {clan.effective_capacity}
                          </span>
                        </span>
                        <span className="roster-assign-clan-meta">
                          <span>
                            Current avg{" "}
                            {compactRosterWeight(currentAverageWeight)}
                          </span>
                          {currentKnownWeights < currentCount && (
                            <span>
                              {currentKnownWeights}/{currentCount} weighed
                            </span>
                          )}
                          {clan.capacity === null && (
                            <span>Default capacity</span>
                          )}
                          {reason && (
                            <span className="roster-assign-warning">
                              {reason}
                            </span>
                          )}
                        </span>
                        <ProgressBar
                          value={projectedCount}
                          max={clan.effective_capacity}
                          label={`${clan.name} projected capacity`}
                          valueText={`${projectedCount} of ${clan.effective_capacity}`}
                        />
                        <ChevronRight
                          className="roster-assign-chevron"
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  );
                },
              )}
              {canUnassign && (
                <li>
                  <button
                    type="button"
                    className="roster-assign-clan roster-assign-unassign"
                    disabled={unavailable}
                    onClick={() => void assign(null)}
                  >
                    <span className="roster-assign-clan-head">
                      <span className="roster-assign-clan-name">
                        <Unlink aria-hidden="true" />
                        <strong>Unassign selected accounts</strong>
                      </span>
                      <ChevronRight
                        className="roster-assign-chevron"
                        aria-hidden="true"
                      />
                    </span>
                    <span className="roster-assign-clan-meta">
                      Keeps signups and clears placement locks.
                    </span>
                  </button>
                </li>
              )}
            </ul>
          </section>
        )}
        <div className="roster-assign-review">
          <details
            className="roster-assign-accounts"
            open={hiddenTags.length > 0 ? true : undefined}
          >
            <summary>
              Review all {selectedAccounts.length} selected accounts
            </summary>
            <ul>
              {reviewAccounts.map((account) => (
                <li key={account.tag}>
                  <span>
                    {account.player_name} <small>{account.tag}</small>
                  </span>
                  {hidden.has(account.tag) && (
                    <small className="roster-assign-hidden">
                      Not visible in list
                    </small>
                  )}
                </li>
              ))}
            </ul>
          </details>
          {locked.length > 0 && (
            <details className="roster-assign-accounts">
              <summary>
                {locked.length} locked placement{locked.length === 1 ? "" : "s"}{" "}
                affected
              </summary>
              <ul>
                {locked.map((account) => (
                  <li key={account.tag}>
                    {account.player_name} <small>{account.tag}</small>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        {error && (
          <p role="alert" className="roster-assign-error">
            {error}
          </p>
        )}
      </div>
    </ActionPanel>
  );
}
