import type { Pool } from "./api";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";
import { compactRosterWeight } from "./rosterCompactWeight";
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
  knownWeightCount: number;
  missingWeightCount: number;
  averageWeight: number | null;
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
    { count: number; known: number; weight: number }
  >();
  for (const account of accounts) {
    if (!account.assigned_clan_tag) continue;
    const summary = byClan.get(account.assigned_clan_tag) || {
      count: 0,
      known: 0,
      weight: 0,
    };
    summary.count += 1;
    if (account.effective_weight !== null) {
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
        known: 0,
        weight: 0,
      };
      return {
        clan,
        assignedCount: accountSummary.count,
        knownWeightCount: accountSummary.known,
        missingWeightCount: accountSummary.count - accountSummary.known,
        averageWeight: accountSummary.known
          ? accountSummary.weight / accountSummary.known
          : null,
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
        return (
          <section
            className="roster-clan-chips-group"
            key={group.label}
            aria-label={`${group.label} hosting clans`}
          >
            <h3>{group.label}</h3>
            <div className="roster-clan-chips-list">
              {members.map((summary) => {
                const active = selected.has(summary.clan.tag);
                const full =
                  summary.capacity !== null &&
                  summary.assignedCount >= summary.capacity;
                const over =
                  summary.capacity !== null &&
                  summary.assignedCount > summary.capacity;
                const countLabel =
                  summary.capacity === null
                    ? `${summary.assignedCount} assigned`
                    : `${summary.assignedCount} of ${summary.capacity} assigned`;
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
                    aria-label={`${summary.clan.name}, ${countLabel}${weighedLabel}${statusLabel}`}
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
                            : `/${summary.capacity}`}
                        </span>
                      </span>
                      {summary.capacity !== null && (
                        <span className="roster-clan-chip-meta">
                          <span>
                            Avg {compactRosterWeight(summary.averageWeight)}
                          </span>
                          {summary.missingWeightCount > 0 && (
                            <small>
                              {summary.knownWeightCount} of{" "}
                              {summary.assignedCount} weighed
                            </small>
                          )}
                        </span>
                      )}
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
            </div>
          </section>
        );
      })}
    </div>
  );
}
