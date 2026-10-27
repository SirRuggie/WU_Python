import type { ComponentProps } from "react";
import { ArrowDownWideNarrow } from "lucide-react";
import "./SortTrigger.css";
export function sortTriggerLabel(label: string, grouped = false) {
  return `Sort: ${label}${grouped ? ", grouped by Discord user" : ""}`;
}
export default function SortTrigger({
  label,
  grouped = false,
  ...props
}: Omit<ComponentProps<"button">, "children"> & {
  label: string;
  grouped?: boolean;
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
