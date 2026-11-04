import type { ReactNode } from "react";
import ActionMenu, { type ActionMenuItem } from "./rosterUi/ActionMenu";
import "./members/Members.css";
/** Shared Members-style selection shell. The caller owns applicability and scope. */
export default function SelectionActionBar({
  name,
  label,
  shortLabel,
  onShow,
  actions,
  selectionActions,
  desktopSelection,
  busy = false,
  overflowActions,
  className = "",
}: {
  name: string;
  label: string;
  shortLabel: string;
  onShow: () => void;
  actions: ActionMenuItem[];
  selectionActions: ActionMenuItem[];
  desktopSelection: ReactNode;
  busy?: boolean;
  overflowActions?: ActionMenuItem[];
  className?: string;
}) {
  return (
    <div className={`members-bulk-bar ${className}`} role="region" aria-label={name}>
      <button onClick={onShow} aria-label={label}>
        <span className="members-selection-full">{label}</span>
        <span className="members-selection-short" aria-hidden="true">
          {shortLabel}
        </span>
      </button>
      <div className="members-bulk-phone">
        <ActionMenu
          name={name}
          label="Actions"
          disabled={busy}
          items={overflowActions ? [...selectionActions, ...actions, ...overflowActions] : [...actions, ...selectionActions]}
        />
      </div>
      <div className="members-bulk-desktop">
        {desktopSelection}
        {actions.map((item) => (
          <button
            key={item.id}
            disabled={busy || item.disabled}
            title={item.title}
            onClick={(event) => item.onAction?.(event.currentTarget)}
          >
            {item.label}
          </button>
        ))}
        {overflowActions && overflowActions.length > 0 && (
          <ActionMenu name={name} label="More actions" disabled={busy} items={overflowActions} />
        )}
      </div>
    </div>
  );
}
