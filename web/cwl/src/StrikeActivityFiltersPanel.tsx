import { useMemo, useState } from "react";
import ActionPanel from "./ActionPanel";
import StrikeMemberSelect, { strikeMemberOptions } from "./StrikeMemberSelect";
import type { ActivityAccount } from "./strikeActivityView";
import {
  visibleActivityAccounts,
  clearActivityFilters,
  normalizeActivityView,
  type ActivityFilters,
} from "./strikeActivityFilters";

/** Draft filters share the roster panel's focus, Escape and Back behavior. */
export default function StrikeActivityFiltersPanel({
  filters,
  accounts,
  trigger,
  onClose,
  onApply,
}: {
  filters: ActivityFilters;
  accounts: ActivityAccount[];
  trigger: HTMLElement;
  onClose: () => void;
  onApply: (next: ActivityFilters) => void;
}) {
  const [draft, setDraft] = useState(filters);
  const members = useMemo(() => strikeMemberOptions(accounts), [accounts]);
  const patch = (next: Partial<ActivityFilters>) =>
    setDraft((current) =>
      normalizeActivityView({ ...current, ...next, page: 0 }),
    );
  const matching = useMemo(
    () => visibleActivityAccounts(accounts, draft).length,
    [accounts, draft],
  );
  const invalidWeight =
    [draft.minWeight, draft.maxWeight].some(
      (value) => value !== null && (!Number.isFinite(value) || value < 0),
    ) ||
    (draft.minWeight !== null &&
      draft.maxWeight !== null &&
      draft.minWeight > draft.maxWeight);
  const priorities = [
    ["replace_first", "Chopping block"],
    ["high", "High"],
    ["normal", "Normal"],
    ["none", "None"],
  ] as const;
  const numberChoice = (label: string, key: "raidMin", values: number[]) => (
    <label>
      {label}
      <select
        value={draft[key]}
        onChange={(event) =>
          patch({
            [key]: Number(event.target.value) as ActivityFilters["raidMin"],
          })
        }
      >
        {values.map((value) => (
          <option key={value} value={value}>
            {value ? `${value}+` : "Any"}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <ActionPanel
      title="Filter accounts"
      trigger={trigger}
      onClose={onClose}
      expandOnSearchFocus
      footer={
        <>
          <span role="status">{matching} matching accounts</span>
          <button disabled={invalidWeight} onClick={() => onApply(draft)}>
            Apply filters
          </button>
          <button
            onClick={() =>
              // Clans and Town Halls belong to the toolbar selects, not this panel.
              setDraft({
                ...clearActivityFilters(draft),
                clans: draft.clans,
                townHalls: draft.townHalls,
              })
            }
          >
            Clear filters
          </button>
        </>
      }
    >
      {invalidWeight && (
        <p role="alert">
          Use nonnegative weights with minimum no greater than maximum.
        </p>
      )}
      <div className="strike-activity-more">
        <fieldset className="strike-filter-priority">
          <legend>Priority</legend>
          <div>
            {priorities.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={draft.priorities.includes(value)}
                onClick={() =>
                  patch({
                    priorities: draft.priorities.includes(value)
                      ? draft.priorities.filter((item) => item !== value)
                      : [...draft.priorities, value],
                  })
                }
              >
                {label}{" "}
                <small>
                  {
                    accounts.filter((row) => (row.priority || "none") === value)
                      .length
                  }
                </small>
              </button>
            ))}
          </div>
        </fieldset>
        <label>
          Strikes
          <select
            value={draft.strikeMode}
            onChange={(event) =>
              patch({
                strikeMode: event.target.value as ActivityFilters["strikeMode"],
              })
            }
          >
            <option value="any">Any</option>
            <option value="1">1+ strikes</option>
            <option value="3">3+ strikes</option>
            <option value="over_limit">Over limit</option>
            <option value="new_this_week">New this week</option>
          </select>
        </label>
        {numberChoice("Raid weekends without attacking", "raidMin", [0, 1, 2])}
        <StrikeMemberSelect
          options={members}
          value={draft.member}
          onChange={(member) => patch({ member })}
        />
        <div className="strike-filter-weights">
          <label>
            Minimum weight
            <input
              type="number"
              min="0"
              value={draft.minWeight ?? ""}
              onChange={(event) =>
                patch({
                  minWeight:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
            />
          </label>
          <label>
            Maximum weight
            <input
              type="number"
              min="0"
              value={draft.maxWeight ?? ""}
              onChange={(event) =>
                patch({
                  maxWeight:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
            />
          </label>
        </div>
        <label>
          Membership
          <select
            value={draft.left}
            onChange={(event) =>
              patch({ left: event.target.value as ActivityFilters["left"] })
            }
          >
            <option value="all">Current and left</option>
            <option value="current">Current members</option>
            <option value="left">Left clan</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.includeLow}
            onChange={(event) => patch({ includeLow: event.target.checked })}
          />
          Include eligible 1–2 strikes
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.noActivity}
            onChange={(event) => patch({ noActivity: event.target.checked })}
          />
          No activity yet
        </label>
      </div>
    </ActionPanel>
  );
}
