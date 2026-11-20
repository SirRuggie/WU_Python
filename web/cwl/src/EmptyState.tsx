import type { ReactNode } from "react";
import "./EmptyState.css";

/** A settled empty result, never a loading or failed-read placeholder. */
export default function EmptyState({
  title,
  line,
  action,
}: {
  title: string;
  line: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{line}</p>
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
