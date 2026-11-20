import ActionPanel from "./ActionPanel";
import { useEffect, useRef, useState } from "react";
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
  const [closing, setClosing] = useState(false);
  const closingRef = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const closeImmediately = () => {
    window.clearTimeout(timer.current);
    closingRef.current = true;
    onClose();
  };
  const close = () => {
    if (closingRef.current) return;
    closingRef.current = true;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      onClose();
      return;
    }
    setClosing(true);
    timer.current = window.setTimeout(onClose, 100);
  };
  return (
    <ActionPanel
      title="Sort accounts"
      className={`strike-sort-panel${closing ? " is-closing" : ""}`}
      trigger={trigger}
      onClose={close}
      onHistoryClose={closeImmediately}
    >
      <fieldset className="strike-sort-options" disabled={closing}>
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
      <fieldset className="strike-sort-direction" disabled={closing}>
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
      <fieldset className="strike-sort-group" disabled={closing}>
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
