import { rosterCapacity } from "./rosterCapacity";
import { useState } from "react";
import { totalRosterWeight } from "./rosterTotalWeight";
import type { Pool } from "./api";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";
import { Button, ProgressBar } from "./rosterUi/primitives";
import "./RosterClanChips.css";

type Props = {
  roster: RosterSnapshot;
  pool: Pool | "all";
  selectedTags: string[];
  onSelect: (tag: string) => void;
  disabled: boolean;
};

export type RosterClanChipSummary = {
  clan: RosterClan;
  assignedCount: number;
  fillerCount: number;
  knownWeightCount: number;
  missingWeightCount: number;
  totalWeight: number | null;
  capacity: number | null;
};

const GROUPS: { pool: Pool | null; label: string }[] = [
  { pool: "main", label: "Main" },
  { pool: "lazy", label: "Lazy" },
  { pool: null, label: "All" },
];

/** Recount roster accounts rather than trusting a possibly stale clan summary. */
export function buildRosterClanChipSummaries(
  accounts: RosterAccount[],
  clans: RosterClan[],
  pool: Pool | "all",
): RosterClanChipSummary[] {
  const byClan = new Map<
    string,
    { count: number; known: number; weight: number; fillers: number }
  >();
  for (const account of accounts) {
    if (!account.assigned_clan_tag) continue;
    const summary = byClan.get(account.assigned_clan_tag) || {
      count: 0,
      fillers: 0,
      known: 0,
      weight: 0,
    };
    summary.count += 1;
    summary.fillers += Number(!!account.roster_filler);
    if (
      account.effective_weight != null &&
      Number.isFinite(account.effective_weight)
    ) {
      summary.known += 1;
      summary.weight += account.effective_weight;
    }
    byClan.set(account.assigned_clan_tag, summary);
  }
  return clans
    .filter(
      (clan) =>
        !clan.archived &&
        (pool === "all" ||
          clan.pool === pool ||
          (pool === "main" && clan.pool === null)),
    )
    .map((clan) => {
      const accountSummary = byClan.get(clan.tag) || {
        count: 0,
        fillers: 0,
        known: 0,
        weight: 0,
      };
      return {
        clan,
        assignedCount: accountSummary.count,
        fillerCount: accountSummary.fillers,
        knownWeightCount: accountSummary.known,
        missingWeightCount: accountSummary.count - accountSummary.known,
        totalWeight: accountSummary.known ? accountSummary.weight : null,
        capacity:
          clan.capacity === 15 || clan.capacity === 30 ? clan.capacity : null,
      };
    })
    .sort((left, right) => {
      const leftGroup = GROUPS.findIndex(
        (group) => group.pool === left.clan.pool,
      );
      const rightGroup = GROUPS.findIndex(
        (group) => group.pool === right.clan.pool,
      );
      return (
        leftGroup - rightGroup || left.clan.name.localeCompare(right.clan.name)
      );
    });
}

export default function RosterClanChips({
  roster,
  pool,
  selectedTags,
  onSelect,
  disabled,
}: Props) {
  const [revealed, setRevealed] = useState<string[]>([]);
  const summaries = buildRosterClanChipSummaries(
    roster.accounts,
    roster.clans,
    pool,
  );
  const selected = new Set(selectedTags);
  if (!summaries.length) return null;

  return (
    <div
      className="roster-clan-chips roster-ui"
      aria-label="Hosting clan filters"
    >
      {GROUPS.map((group) => {
        const members = summaries.filter(
          (summary) => summary.clan.pool === group.pool,
        );
        if (!members.length) return null;
        const emptyCount = members.filter(
          (member) => member.assignedCount === 0,
        ).length;
        const visible = revealed.includes(group.label)
          ? members
          : members.filter((member) => member.assignedCount > 0);
        return (
          <section
            className="roster-clan-chips-group"
            key={group.label}
            aria-label={`${group.label} hosting clans`}
          >
            <h3>{group.label}</h3>
            <div className="roster-clan-chips-list">
              {!members.some((member) => member.assignedCount > 0) && (
                <p className="roster-clan-empty-note">
                  No clans have players yet
                </p>
              )}
              {visible.map((summary) => {
                const active = selected.has(summary.clan.tag);
                const capacity = rosterCapacity(
                  summary.assignedCount,
                  summary.fillerCount,
                  summary.capacity,
                );
                const { full, over } = capacity;
                const countLabel =
                  summary.capacity === null
                    ? `${summary.assignedCount} assigned`
                    : `${summary.assignedCount} of ${summary.capacity} assigned`;
                const totalLabel =
                  summary.totalWeight === null
                    ? "Total: no weights yet"
                    : totalRosterWeight(summary.totalWeight);
                const weighedLabel = summary.missingWeightCount
                  ? `, ${summary.knownWeightCount} of ${summary.assignedCount} weighed`
                  : "";
                const statusLabel = over
                  ? ", over capacity"
                  : full
                    ? ", full"
                    : "";
                return (
                  <Button
                    key={summary.clan.tag}
                    className={`roster-clan-chip${active ? " is-selected" : ""}${over ? " is-over" : full ? " is-full" : " is-room"}`}
                    aria-pressed={active}
                    aria-label={`${summary.clan.name}, ${countLabel}, ${totalLabel}${weighedLabel}${statusLabel}`}
                    disabled={disabled}
                    onClick={() => onSelect(summary.clan.tag)}
                  >
                    <span className="roster-clan-chip-content">
                      <span className="roster-clan-chip-top">
                        <strong title={summary.clan.name}>
                          {summary.clan.name}
                        </strong>
                        <span className="roster-clan-chip-count">
                          {summary.assignedCount}
                          {summary.capacity === null
                            ? ""
                            : ` / ${summary.capacity}`}
                          {capacity.fillerLabel && (
                            <small> · {capacity.fillerLabel}</small>
                          )}
                        </span>
                      </span>
                      <span className="roster-clan-chip-meta">
                        <span>{totalLabel}</span>
                        {summary.missingWeightCount > 0 && (
                          <small>
                            {summary.knownWeightCount} of{" "}
                            {summary.assignedCount} weighed
                          </small>
                        )}
                      </span>
                      {summary.capacity !== null && (
                        <ProgressBar
                          value={summary.assignedCount}
                          max={summary.capacity}
                          label={`${summary.clan.name} capacity`}
                          valueText={`${summary.assignedCount} of ${summary.capacity} assigned`}
                        />
                      )}
                    </span>
                  </Button>
                );
              })}
              {emptyCount > 0 && !revealed.includes(group.label) && (
                <Button
                  className="roster-clan-empty-reveal"
                  disabled={disabled}
                  onClick={() =>
                    setRevealed((current) => [...current, group.label])
                  }
                >
                  +{emptyCount} {emptyCount === 1 ? "clan" : "clans"} with no
                  players
                </Button>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
