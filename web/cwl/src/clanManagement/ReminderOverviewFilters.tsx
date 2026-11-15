import { useState } from "react";
import ActionPanel from "../ActionPanel";
import FilterChips from "../FilterChips";
import { clanCategory } from "./ClanCategories";
import {
  visibleRows,
  type OverviewFilter,
  type OverviewRow,
} from "./reminderOverview";

export type OverviewFilters = { filter: OverviewFilter; category: string };
export const noOverviewFilters: OverviewFilters = {
  filter: "all",
  category: "",
};
export const statusLabels: Record<OverviewFilter, string> = {
  all: "All",
  attention: "Needs attention",
  enabled: "On",
  off: "Off",
  not_set_up: "Not set up",
};

export function overviewCategories(rows: OverviewRow[]) {
  return [
    ...new Set(rows.map((row) => clanCategory(row.clan.type)).filter(Boolean)),
  ].sort((a, b) => a.localeCompare(b));
}

/** Draft Type and Status; the counts show what each option would match with the other choice applied. */
export default function ReminderOverviewFilters({
  rows,
  query,
  names,
  channelsReady,
  filters,
  trigger,
  onClose,
  onApply,
}: {
  rows: OverviewRow[];
  query: string;
  names: Map<string, string>;
  channelsReady: boolean;
  filters: OverviewFilters;
  trigger: HTMLElement;
  onClose: () => void;
  onApply: (next: OverviewFilters) => void;
}) {
  const [draft, setDraft] = useState(filters);
  const count = (filter: OverviewFilter, category: string) =>
    visibleRows(rows, query, filter, names, channelsReady, category).length;
  return (
    <ActionPanel
      title="Filter clans"
      trigger={trigger}
      onClose={onClose}
      footer={
        <>
          <span role="status">{count(draft.filter, draft.category)} clans</span>
          <button onClick={() => onApply(draft)}>Apply</button>
          <button onClick={() => setDraft(noOverviewFilters)}>Reset</button>
        </>
      }
    >
      <div className="overview-filter-sections">
        <div>
          <h3>Type</h3>
          <FilterChips
            className="filter-chips--flow"
            label="Clan type"
            options={["", ...overviewCategories(rows)].map((category) => ({
              value: category,
              label: category || "All",
              count: count(draft.filter, category),
            }))}
            value={draft.category}
            onChange={(category) => setDraft({ ...draft, category })}
            variant="pill"
            role="group"
          />
        </div>
        <div>
          <h3>Status</h3>
          <FilterChips
            className="filter-chips--flow"
            label="Reminder status"
            options={(Object.keys(statusLabels) as OverviewFilter[]).map(
              (filter) => ({
                value: filter,
                label: statusLabels[filter],
                count: count(filter, draft.category),
              }),
            )}
            value={draft.filter}
            onChange={(filter) => setDraft({ ...draft, filter })}
            variant="pill"
            role="group"
          />
        </div>
      </div>
    </ActionPanel>
  );
}
