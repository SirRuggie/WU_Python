import type { ComponentProps } from "react";
import { ArrowDownWideNarrow } from "lucide-react";
import "./SortTrigger.css";
export function sortTriggerLabel(
  label: string,
  grouped: boolean | string = false,
) {
  return `Sort: ${label}${grouped ? `, grouped by ${grouped === true ? "Discord user" : grouped}` : ""}`;
}
export default function SortTrigger({
  label,
  grouped = false,
  ...props
}: Omit<ComponentProps<"button">, "children"> & {
  label: string;
  /** True groups by Discord user; a string names another grouping. */
  grouped?: boolean | string;
}) {
  return (
    <button
      {...props}
      type="button"
      className="roster-ui-button roster-sort-trigger"
      aria-label={sortTriggerLabel(label, grouped)}
      title={`${label}${grouped ? " · Grouped" : ""}`}
    >
      <ArrowDownWideNarrow size={18} aria-hidden="true" />
      <span>
        {label}
        {grouped ? " · Grouped" : ""}
      </span>
    </button>
  );
}
