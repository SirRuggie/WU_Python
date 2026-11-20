import { numericInputProps } from "./inputProps";
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
  const historyOnly = draft.left === "left";
  const clanOptions = (
    historyOnly
      ? []
      : [
          ...clans,
          ...(draft.clans.length === 1 &&
          !clans.some((clan) => clan.tag === draft.clans[0])
            ? [{ tag: draft.clans[0], name: draft.clans[0] }]
            : []),
        ]
  )
    .map((clan) => ({
      ...clan,
      count: accounts.filter(
        (row) =>
          (row.left_clan ? row.last_clan_tag : row.current_clan_tag) ===
          clan.tag,
      ).length,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const hallOptions = [
    ...new Set([
      ...accounts
        .map((row) => row.town_hall)
        .filter((hall): hall is number => !!hall),
      ...(draft.townHalls.length === 1 ? draft.townHalls : []),
    ]),
  ]
    .sort((a, b) => b - a)
    .map((hall) => ({
      hall,
      count: accounts.filter((row) => row.town_hall === hall).length,
    }));
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
        <fieldset className="strike-filter-scope">
          <legend>Accounts</legend>
          <label>
            Membership
            <select
              aria-label="Membership"
              value={draft.left}
              onChange={(event) =>
                patch({
                  left: event.target.value as ActivityFilters["left"],
                  clans: [],
                })
              }
            >
              <option value="all">Current and recent leavers</option>
              <option value="current">Current members</option>
              <option value="left">Left</option>
            </select>
          </label>
          <label>
            Clan
            <select
              aria-label="Clan"
              value={draft.clans.length > 1 ? "many" : (draft.clans[0] ?? "")}
              disabled={historyOnly}
              onChange={(event) =>
                patch({ clans: event.target.value ? [event.target.value] : [] })
              }
            >
              <option value="">All clans</option>
              {draft.clans.length > 1 && (
                <option value="many" disabled>
                  {draft.clans.length} clans
                </option>
              )}
              {clanOptions.map((clan) => (
                <option key={clan.tag} value={clan.tag}>
                  {clan.name} · {clan.count}
                </option>
              ))}
            </select>
          </label>
          <label>
            Town Hall
            <select
              aria-label="Town Hall"
              value={
                draft.townHalls.length > 1
                  ? "many"
                  : String(draft.townHalls[0] ?? "")
              }
              onChange={(event) =>
                patch({
                  townHalls: event.target.value
                    ? [Number(event.target.value)]
                    : [],
                })
              }
            >
              <option value="">Any TH</option>
              {draft.townHalls.length > 1 && (
                <option value="many" disabled>
                  {draft.townHalls.length} Town Halls
                </option>
              )}
              {hallOptions.map((option) => (
                <option key={option.hall} value={option.hall}>
                  TH{option.hall} · {option.count}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
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
              {...numericInputProps}
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
              {...numericInputProps}
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
