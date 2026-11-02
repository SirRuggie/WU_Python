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
}: {
  name: string;
  label: string;
  shortLabel: string;
  onShow: () => void;
  actions: ActionMenuItem[];
  selectionActions: ActionMenuItem[];
  desktopSelection: ReactNode;
  busy?: boolean;
}) {
  return (
    <div className="members-bulk-bar" role="region" aria-label={name}>
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
          items={[...actions, ...selectionActions]}
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
      </div>
    </div>
  );
}
