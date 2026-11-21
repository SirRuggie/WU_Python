import type { ReactNode, Ref } from "react";
import "./tokens.css";
import "./primitives.css";
import "./ListToolbar.css";

type Props = {
  search?: ReactNode;
  scope?: ReactNode;
  filters?: ReactNode;
  sort?: ReactNode;
  actions?: ReactNode;
  className?: string;
  rootRef?: Ref<HTMLDivElement>;
  sortBeforeFilters?: boolean;
};

/** List controls retain DOM order and wrap together; panels stay with their owner. */
export default function ListToolbar({
  search,
  scope,
  filters,
  sort,
  actions,
  className = "",
  rootRef,
  sortBeforeFilters = false,
}: Props) {
  return (
    <div
      ref={rootRef}
      className={`roster-ui list-toolbar${className ? ` ${className}` : ""}`}
    >
      {search}
      {scope}
      {sortBeforeFilters ? sort : filters}
      {sortBeforeFilters ? filters : sort}
      {actions}
    </div>
  );
}
