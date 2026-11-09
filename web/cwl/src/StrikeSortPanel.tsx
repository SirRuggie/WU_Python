import ActionPanel from "./ActionPanel";
import {
  activityGroupLabels,
  activityGroups,
  activitySortLabels,
  activitySorts,
  type ActivityFilters,
} from "./strikeActivityFilters";

/** Sort, direction and grouping in one panel; each choice applies at once. */
export default function StrikeSortPanel({
  filters,
  trigger,
  onClose,
  onChange,
}: {
  filters: ActivityFilters;
  trigger: HTMLElement;
  onClose: () => void;
  onChange: (patch: Partial<ActivityFilters>) => void;
}) {
  return (
    <ActionPanel
      title="Sort accounts"
      className="strike-sort-panel"
      trigger={trigger}
      onClose={onClose}
    >
      <fieldset className="strike-sort-options">
        <legend>Sort by</legend>
        {activitySorts.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={filters.sort === value}
            onClick={() => onChange({ sort: value })}
          >
            {activitySortLabels[value]}
          </button>
        ))}
      </fieldset>
      <fieldset className="strike-sort-direction">
        <legend>Direction</legend>
        {(["desc", "asc"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={filters.direction === value}
            onClick={() => onChange({ direction: value })}
          >
            {value === "desc" ? "High to low" : "Low to high"}
          </button>
        ))}
      </fieldset>
      <fieldset className="strike-sort-group">
        <legend>Group by</legend>
        {activityGroups.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={filters.group === value}
            onClick={() => onChange({ group: value })}
          >
            {activityGroupLabels[value]}
          </button>
        ))}
      </fieldset>
    </ActionPanel>
  );
}
