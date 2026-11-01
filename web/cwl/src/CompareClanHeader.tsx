import { clanCapacity } from "./rosterCapacity";
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
  const capacity = clanCapacity(accounts, clan.tag, clan.effective_capacity);
  const summary = clanSummary(accounts, clan.tag);
  const tally = comparisonTally(
    accounts.filter((a) => a.assigned_clan_tag === clan.tag).map((a) => a.tag),
    locations,
    clan.tag,
    clan.name,
  );
  const range = comparisonWeightRange(clan);
  return (
    <div className="compare-clan-summary">
      <div className="compare-clan-top">
        <strong className="compare-clan-name">{clan.name}</strong>
        <strong>
          {summary.count} / {clan.effective_capacity}
          {capacity.fillerLabel && <small> · {capacity.fillerLabel}</small>}
        </strong>
        {menu}
      </div>
      {compact && (
        <small className="compare-rail-subtitle">
          {clan.cwl_league || "League unavailable"} · {clan.tag}
          {range && ` · ${range}`}
        </small>
      )}
      <div className="compare-clan-metrics">
        <strong className="compare-total">
          {totalRosterWeight(summary.totalWeight)}
        </strong>
        {summary.knownWeights < summary.count && (
          <small>
            {summary.knownWeights} of {summary.count} weighed
          </small>
        )}
        {summary.averageTownHall !== null && (
          <small>
            Avg TH{" "}
            {summary.averageTownHall.toLocaleString(undefined, {
              maximumFractionDigits: 1,
            })}
            {summary.knownTownHalls < summary.count &&
              ` · ${summary.knownTownHalls} of ${summary.count} known`}
          </small>
        )}
      </div>
      {!compact && (
        <small>
          {clan.cwl_league || "League unavailable"} · {clan.tag}
          {range && ` · ${range}`}
        </small>
      )}
      <small className="compare-tally">
        <span>
          <span className="compare-count-arrived">{tally.arrived}</span> in clan
        </span>
        <span>
          <span className="compare-tally-separator">, </span>
          <span className="compare-count-missing">{tally.elsewhere}</span>{" "}
          elsewhere
        </span>
        {tally.checking > 0 && (
          <span>
            <span className="compare-tally-separator">, </span>
            <span className="compare-count-checking">
              {tally.checking}
            </span>{" "}
            checking
          </span>
        )}
        {tally.outside > 0 && (
          <span>
            <span className="compare-tally-separator">, </span>
            <span className="compare-count-outside">{tally.outside}</span>{" "}
            outside family
          </span>
        )}
      </small>
      <ProgressBar
        className={capacity.barClass}
        value={summary.count}
        max={clan.effective_capacity}
        label={`${clan.name} capacity`}
      />
    </div>
  );
}
