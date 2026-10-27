import type { ReactNode } from "react";
import type { RosterAccount, RosterClan } from "./roster";
import { clanSummary } from "./compare";
import { comparisonTally, type LocationRecords } from "./comparisonLocation";
import { comparisonWeightRange } from "./comparePresentation";
import { totalRosterWeight } from "./rosterTotalWeight";
import { ProgressBar } from "./rosterUi/primitives";

type Props = {
  clan: RosterClan;
  accounts: RosterAccount[];
  locations: LocationRecords;
  menu?: ReactNode;
  compact?: boolean;
};
export default function CompareClanHeader({
  clan,
  accounts,
  locations,
  menu,
  compact = false,
}: Props) {
  const summary = clanSummary(accounts, clan.tag);
  const tally = comparisonTally(
    accounts.filter((a) => a.assigned_clan_tag === clan.tag).map((a) => a.tag),
    locations,
    clan.tag,
  );
  const range = comparisonWeightRange(clan);
  return (
    <div className="compare-clan-summary">
      <div className="compare-clan-top">
        <strong className="compare-clan-name">{clan.name}</strong>
        <strong>
          {summary.count} / {clan.effective_capacity}
        </strong>
        {menu}
      </div>
      {!compact && (
        <small>
          {clan.cwl_league || "League unavailable"} · {clan.tag}
          {range && ` · ${range}`}
        </small>
      )}
      <strong className="compare-total">
        {totalRosterWeight(summary.totalWeight)}
      </strong>
      {summary.knownWeights < summary.count && (
        <small>
          {summary.knownWeights} of {summary.count} weighed
        </small>
      )}
      <small className="compare-tally">
        {tally.arrived} in clan · {tally.elsewhere} elsewhere
        {tally.checking > 0 && ` · ${tally.checking} checking`}
        {tally.outside > 0 && (
          <span className="compare-warning">
            {" "}
            · {tally.outside} outside family
          </span>
        )}
      </small>
      {!compact && (
        <small>
          Avg TH{" "}
          {summary.averageTownHall === null
            ? "—"
            : summary.averageTownHall.toLocaleString(undefined, {
                maximumFractionDigits: 1,
              })}
          {summary.knownTownHalls < summary.count &&
            ` · ${summary.knownTownHalls} of ${summary.count} known`}
        </small>
      )}
      <ProgressBar
        className={
          summary.count > clan.effective_capacity
            ? "is-over"
            : summary.count === clan.effective_capacity
              ? "is-full"
              : "has-room"
        }
        value={summary.count}
        max={clan.effective_capacity}
        label={`${clan.name} capacity`}
      />
    </div>
  );
}
