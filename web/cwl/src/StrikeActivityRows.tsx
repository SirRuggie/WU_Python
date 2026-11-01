import type { ActivityAccount } from "./strikeActivityView";
import { compactWeight } from "./replacementView";
import {
  hasNoActivity,
  quietDays,
  warsWithoutAttacking,
} from "./strikeActivityFilters";

export function compactActivitySummary(row: ActivityAccount) {
  const quiet = quietDays(row),
    wars = warsWithoutAttacking(row);
  return (
    [
      quiet !== null
        ? `Quiet ${quiet}d`
        : hasNoActivity(row)
          ? "Not seen since tracking began"
          : null,
      wars !== null && wars > 0 ? `No attacks in last ${wars} wars` : null,
      row.over_limit ? "Over limit" : null,
      row.new_this_week ? "New this week" : null,
    ]
      .filter(Boolean)
      .join(" · ") || "Activity unavailable"
  );
}
export default function StrikeActivityRows({
  rows,
  selecting,
  selected,
  busy,
  onSelected,
  onChoose,
}: {
  rows: ActivityAccount[];
  selecting: boolean;
  selected: string[];
  busy: boolean;
  onSelected: (tags: string[]) => void;
  onChoose: (row: ActivityAccount) => void;
}) {
  return (
    <table className="strike-activity-table">
      <caption className="sr-only">Matching family accounts</caption>
      <thead>
        <tr>
          {selecting && <th scope="col">Select</th>}
          <th scope="col">Account</th>
          <th scope="col">TH</th>
          <th scope="col">Clan</th>
          <th scope="col">Weight</th>
          <th scope="col">Strikes</th>
          <th scope="col">Activity</th>
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
                onClick={(event) => {
                  event.stopPropagation();
                  onChoose(row);
                }}
              >
                <strong>{row.player_name}</strong>
                <small>{row.player_tag}</small>
              </button>
            </td>
            <td className="strike-activity-th">TH{row.town_hall || "—"}</td>
            <td className="strike-activity-clan">
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
            <td className="strike-activity-one-summary">
              <span className="strike-activity-summary-text">
                {compactActivitySummary(row)}
              </span>
              {row.priority === "replace_first" ? (
                <strong className="strike-priority-chopping">
                  Chopping Block
                </strong>
              ) : row.priority === "high" ? (
                <span className="strike-priority-high">High</span>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
