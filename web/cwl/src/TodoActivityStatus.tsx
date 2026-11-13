import { LockKeyhole } from "lucide-react";
import type { TodoRow, TodoView } from "./todo";

/** One notice per activity; diagnostic wording stays available on demand. */
export default function TodoActivityStatus({
  view,
  hasRows,
  unreadable,
  onAffected,
}: {
  view: TodoView;
  hasRows: boolean;
  unreadable: number;
  onAffected: () => void;
}) {
  if (view.loading) return null;
  const failed = !view.ok || !!view.incomplete;
  const details = [
    ...new Set(
      [view.incomplete, view.unavailable, view.note, ...view.notes]
        .flatMap((value) => (value || "").split(";"))
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
  if (!failed) {
    // Private war logs are a clan setting, not a failure: TodoPrivateNote
    // shows them below the task list.
    return details.length ? (
      <div className="todo-notes">
        {details.map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    ) : null;
  }
  return (
    <div className="todo-warning" role="status">
      <strong>
        {hasRows ? "Some tasks are missing" : "Could not load this activity"}
      </strong>
      <p>
        {hasRows
          ? "Showing the results we could check. Check in-game for the rest."
          : "Clash data is unavailable. Check in-game for now, or try Refresh again later."}
      </p>
      <details>
        <summary className="target-summary-44">Check details</summary>
        {details.map((note) => (
          <p key={note}>{note}</p>
        ))}
        {unreadable > 0 && (
          <button onClick={onAffected}>View affected accounts →</button>
        )}
      </details>
    </div>
  );
}

function accounts(count: number) {
  return `${count} account${count === 1 ? "" : "s"}`;
}

/** Neutral note under the War list for accounts whose clan war is unreadable. */
export function TodoPrivateNote({
  rows,
  onView,
}: {
  rows: TodoRow[];
  onView: () => void;
}) {
  const privateCount = rows.filter((row) => row.detail === "private").length;
  const otherCount = rows.length - privateCount;
  return (
    <div className="todo-private-note">
      <LockKeyhole aria-hidden="true" size={16} />
      <p>
        {privateCount > 0 &&
          `${accounts(privateCount)} ${privateCount === 1 ? "is" : "are"} in a clan with a private war log. `}
        {otherCount > 0 &&
          `${accounts(otherCount)} could not be checked right now. `}
        Check {rows.length === 1 ? "its" : "their"} attacks in-game.{" "}
        <button type="button" className="todo-note-link" onClick={onView}>
          View accounts
        </button>
      </p>
    </div>
  );
}
