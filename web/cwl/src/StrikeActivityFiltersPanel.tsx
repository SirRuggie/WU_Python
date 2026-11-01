import { useMemo, useState } from "react";
import ActionPanel from "./ActionPanel";
import RosterFilterOptions from "./RosterFilterOptions";
import type { ActivityAccount } from "./strikeActivityView";
import {
  visibleActivityAccounts,
  clearActivityFilters,
  type ActivityFilters,
} from "./strikeActivityFilters";

/** Draft filters share the roster panel's focus, Escape and Back behavior. */
export default function StrikeActivityFiltersPanel({
  filters,
  accounts,
  clans,
  trigger,
  onClose,
  onApply,
}: {
  filters: ActivityFilters;
  accounts: ActivityAccount[];
  clans: { tag: string; name: string }[];
  trigger: HTMLElement;
  onClose: () => void;
  onApply: (next: ActivityFilters) => void;
}) {
  const [draft, setDraft] = useState(filters);
  const [clanSearch, setClanSearch] = useState("");
  const patch = (next: Partial<ActivityFilters>) =>
    setDraft((current) => ({ ...current, ...next, page: 0, view: "all" }));
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
  const halls = [
    ...new Set(
      accounts
        .map((row) => row.town_hall)
        .filter((hall): hall is number => !!hall),
    ),
  ].sort((a, b) => b - a);
  const numberChoice = (
    label: string,
    key: "noAttackMin" | "quietMin" | "raidMin",
    values: number[],
  ) => (
    <label>
      {label}
      <select
        value={draft[key]}
        onChange={(event) => patch({ [key]: Number(event.target.value) })}
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
          <button onClick={() => setDraft(clearActivityFilters(draft))}>
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
        <label>
          Find clan
          <input
            type="search"
            value={clanSearch}
            onChange={(event) => setClanSearch(event.target.value)}
          />
        </label>
        <RosterFilterOptions
          title="Clans"
          selected={draft.clans}
          onChange={(clans) => patch({ clans })}
          options={clans
            .filter((clan) =>
              `${clan.name} ${clan.tag}`
                .toLocaleLowerCase()
                .includes(clanSearch.toLocaleLowerCase()),
            )
            .map((clan) => ({
              value: clan.tag,
              label: clan.name,
              count: accounts.filter((row) => row.current_clan_tag === clan.tag)
                .length,
            }))}
        />
        {numberChoice(
          "Wars without attacking",
          "noAttackMin",
          [0, 3, 5, 10, 14],
        )}
        {numberChoice("Quiet days", "quietMin", [0, 7, 14, 30])}
        {numberChoice("Raid weekends without attacking", "raidMin", [0, 1, 2])}
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
        <RosterFilterOptions
          title="Priority"
          selected={draft.priorities}
          onChange={(priorities) =>
            patch({ priorities: priorities as ActivityFilters["priorities"] })
          }
          options={["replace_first", "high", "normal", "none"].map((value) => ({
            value,
            label:
              value === "replace_first"
                ? "Chopping block"
                : value === "none"
                  ? "No priority"
                  : value === "high"
                    ? "High"
                    : "Normal",
            count: accounts.filter((row) => (row.priority || "none") === value)
              .length,
          }))}
        />
        <RosterFilterOptions
          title="Town halls"
          selected={draft.townHalls.map(String)}
          onChange={(values) => patch({ townHalls: values.map(Number) })}
          options={halls.map((hall) => ({
            value: String(hall),
            label: `TH${hall}`,
            count: accounts.filter((row) => row.town_hall === hall).length,
          }))}
        />
        <label>
          Minimum weight
          <input
            type="number"
            min="0"
            value={draft.minWeight ?? ""}
            onChange={(event) =>
              patch({
                minWeight:
                  event.target.value === "" ? null : Number(event.target.value),
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
                  event.target.value === "" ? null : Number(event.target.value),
              })
            }
          />
        </label>
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
            checked={draft.marked}
            onChange={(event) => patch({ marked: event.target.checked })}
          />
          Marked for replacement
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
          No activity since tracking began
        </label>
      </div>
    </ActionPanel>
  );
}
