import { useMemo, useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";
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

function displayWeight(value: number | null) {
  return value === null ? "Unavailable" : Math.round(value).toLocaleString();
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
          "The assignment was not saved. Review the roster status and try again.",
        );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The assignment was not saved. Try again.",
      );
    } finally {
      pending.current = false;
      setSubmitting(false);
    }
  };

  return (
    <ActionPanel
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
          {selectedAccounts.length} account
          {selectedAccounts.length === 1 ? "" : "s"} selected. Choose a clan to
          update the working roster; publish separately for members.
        </p>
        <p className="roster-assign-lock-note">
          Manual assignment locks placement. Unassign clears the lock.
        </p>
        {pool !== null && (
          <label className="roster-assign-search">
            Search hosting clans
            <input
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
            {hiddenTags.length === 1 ? " is" : "s are"} hidden by current
            filters and will be included.
          </p>
        )}
        <details className="roster-assign-accounts">
          <summary>
            Review all {selectedAccounts.length} selected accounts
          </summary>
          <ul>
            {selectedAccounts.map((account) => (
              <li key={account.tag}>
                <span>
                  {account.player_name} <small>{account.tag}</small>
                </span>
                {hidden.has(account.tag) && <small>Hidden by filters</small>}
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
        {pool === null && selectedAccounts.length > 0 && (
          <p className="roster-assign-warning">
            Main and Lazy accounts are selected together. Unassign is available;
            choose one pool to assign a clan.
          </p>
        )}
        {pool !== null && (
          <section
            className="roster-assign-destinations"
            aria-label="Hosting clan destinations"
          >
            <h3>{pool === "main" ? "Main" : "Lazy"} CWL hosting clans</h3>
            <p className="roster-assign-result-count">
              {shownDestinations.length} of {destinations.length} clans
            </p>
            {destinations.length === 0 && (
              <p>No active hosting clans are available for this pool.</p>
            )}
            {destinations.length > 0 && shownDestinations.length === 0 && (
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
                  const capacityLabel = `${clan.effective_capacity}${clan.capacity === null ? " default" : ""}`;
                  return (
                    <li key={clan.tag}>
                      <div className="roster-assign-clan-details">
                        <strong>{clan.name}</strong> <small>{clan.tag}</small>
                        <span>
                          Current: {currentCount} / {capacityLabel} · Avg known
                          weight: {displayWeight(currentAverageWeight)}
                          {currentKnownWeights < currentCount &&
                            ` (${currentKnownWeights} of ${currentCount} weighed)`}
                        </span>
                        <span>
                          After selection: {currentCount} → {projectedCount} /{" "}
                          {clan.effective_capacity}
                          {incomingCount > 0 && ` (+${incomingCount})`}
                        </span>
                        {unavailableDestination && (
                          <small className="roster-assign-warning">
                            {currentlyFull
                              ? "Clan is full"
                              : "Selection exceeds capacity"}
                          </small>
                        )}
                      </div>
                      <button
                        type="button"
                        disabled={
                          unavailable || unavailableDestination || unchanged
                        }
                        onClick={() => void assign(clan.tag)}
                      >
                        {unchanged
                          ? "Already assigned"
                          : `Assign to ${clan.name}`}
                      </button>
                    </li>
                  );
                },
              )}
            </ul>
          </section>
        )}
        <div className="roster-assign-footer">
          <button
            type="button"
            disabled={unavailable || !canUnassign}
            onClick={() => void assign(null)}
          >
            Unassign selected
          </button>
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
