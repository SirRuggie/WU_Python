import type { ActivityAccount } from "./strikeActivityView";
import { compactWeight } from "./replacementView";
import {
  hasNoActivity,
  quietDays,
  knownWars,
  warsWithoutAttacking,
  count,
  knownRaidMisses,
  type ActivitySort,
  type ActivityFilters,
} from "./strikeActivityFilters";
const warRatio = (row: ActivityAccount) => {
  const chain = warsWithoutAttacking(row);
  if (chain !== null && chain >= 1)
    return chain === 1 ? "Missed last war" : `Missed last ${chain} wars`;
  if (row.war_chain_unavailable) return null;
  const total = knownWars(row),
    attacked = count(row.attacked_wars);
  return total !== null && attacked !== null && attacked <= total
    ? `${attacked} of ${total} wars`
    : null;
};
const raidRatio = (row: ActivityAccount) =>
  knownRaidMisses(row) !== null
    ? `${row.attacked_raid_weekends} of ${row.observed_raid_weekends}`
    : null;
const seeded = (row: ActivityAccount) =>
  /clashking/i.test(row.last_seen_source || "");
const priority = (row: ActivityAccount) =>
  row.priority === "replace_first" ? (
    <strong className="strike-priority-chopping">Chopping Block</strong>
  ) : row.priority === "high" ? (
    <span className="strike-priority-high">High</span>
  ) : null;
export function compactActivitySummary(row: ActivityAccount) {
  const quiet = quietDays(row),
    wars = warRatio(row),
    raids = raidRatio(row);
  return [
    quiet !== null
      ? `Quiet ${seeded(row) ? "~" : ""}${quiet}d`
      : hasNoActivity(row)
        ? "No activity yet"
        : null,
    wars,
    raids ? `${raids} raids` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
const columns: { label: string; sort: ActivitySort }[] = [
  { label: "Player", sort: "name" },
  { label: "TH", sort: "th" },
  { label: "Clan", sort: "clan" },
  { label: "Weight", sort: "weight" },
  { label: "Strikes", sort: "strikes" },
  { label: "Quiet", sort: "quiet" },
  { label: "Wars", sort: "wars" },
  { label: "Raids", sort: "raids" },
  { label: "Priority", sort: "priority" },
];
export default function StrikeActivityRows({
  rows,
  selecting,
  selected,
  busy,
  filters,
  onSort,
  onSelected,
  onChoose,
}: {
  rows: ActivityAccount[];
  selecting: boolean;
  selected: string[];
  busy: boolean;
  filters: ActivityFilters;
  onSort: (sort: ActivitySort) => void;
  onSelected: (tags: string[]) => void;
  onChoose: (row: ActivityAccount) => void;
}) {
  return (
    <table className="strike-activity-table">
      <caption className="sr-only">Matching family accounts</caption>
      <thead>
        <tr>
          {selecting && <th scope="col">Select</th>}
          {columns.map((column) => (
            <th
              key={column.sort}
              scope="col"
              aria-sort={
                filters.sort === column.sort
                  ? filters.direction === "asc"
                    ? "ascending"
                    : "descending"
                  : "none"
              }
            >
              <button
                disabled={busy}
                onClick={() => onSort(column.sort)}
                aria-label={`Sort by ${column.label}`}
              >
                {column.label}
                {filters.sort === column.sort
                  ? filters.direction === "asc"
                    ? " ↑"
                    : " ↓"
                  : ""}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.player_tag}
            className="strike-activity-entry"
            onClick={() => {
              if (!busy) onChoose(row);
            }}
          >
            {selecting && (
              <td
                className="strike-activity-selection"
                onClick={(event) => event.stopPropagation()}
              >
                <label>
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.player_name}`}
                    checked={selected.includes(row.player_tag)}
                    disabled={
                      busy ||
                      row.left_clan ||
                      !row.current_clan_tag ||
                      (!selected.includes(row.player_tag) &&
                        selected.length >= 50)
                    }
                    onChange={(event) =>
                      onSelected(
                        event.target.checked
                          ? [...selected, row.player_tag]
                          : selected.filter((tag) => tag !== row.player_tag),
                      )
                    }
                  />
                </label>
              </td>
            )}
            <td className="strike-activity-account">
              <button
                className="strike-activity-row"
                disabled={busy}
                data-strike-player={row.player_tag}
                title={`${row.player_name} ${row.player_tag}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onChoose(row);
                }}
              >
                <strong>{row.player_name}</strong>
                <span className="strike-mobile-priority">{priority(row)}</span>
              </button>
            </td>
            <td className="strike-activity-th">TH{row.town_hall || "—"}</td>
            <td
              className="strike-activity-clan"
              title={row.current_clan_name || row.last_clan_name || "No clan"}
            >
              {row.current_clan_name || row.last_clan_name || "No clan"}
              {row.left_clan ? " · Left" : ""}
            </td>
            <td className="strike-activity-weight">
              {row.weight ? compactWeight(row.weight) : "—"}
            </td>
            <td className="strike-activity-count">
              {row.active_strikes}{" "}
              <span className="strike-activity-mobile-label">
                {row.active_strikes === 1 ? "strike" : "strikes"}
              </span>
            </td>
            <td
              className="strike-activity-quiet"
              title={
                seeded(row)
                  ? "Last seen seeded from ClashKing"
                  : "Last observed activity"
              }
            >
              {quietDays(row) !== null
                ? `${seeded(row) ? "~" : ""}${quietDays(row)}d`
                : hasNoActivity(row)
                  ? "No activity yet"
                  : "—"}
            </td>
            <td className="strike-activity-wars">{warRatio(row) || "—"}</td>
            <td className="strike-activity-raids">{raidRatio(row) || "—"}</td>
            <td className="strike-activity-priority">{priority(row)}</td>
            <td
              aria-label="Activity summary"
              className="strike-activity-one-summary"
              title={
                seeded(row) ? "~ Last seen seeded from ClashKing" : undefined
              }
            >
              {compactActivitySummary(row)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
