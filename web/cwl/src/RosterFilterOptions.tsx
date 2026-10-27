import type { ReactNode } from "react";
import "./RosterFilters.css";
export type FilterOption = { value: string; label: ReactNode; count: number };
export default function RosterFilterOptions({
  title,
  options,
  selected,
  onChange,
  disabled = false,
}: {
  title: string;
  options: FilterOption[];
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset>
      <legend>{title}</legend>
      <div className="roster-filters-options">
        {options.map((option) => (
          <label key={option.value}>
            <input
              type="checkbox"
              checked={selected.includes(option.value)}
              disabled={disabled}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...selected, option.value]
                    : selected.filter((value) => value !== option.value),
                )
              }
            />
            <span>{option.label}</span>
            <small>{option.count}</small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
