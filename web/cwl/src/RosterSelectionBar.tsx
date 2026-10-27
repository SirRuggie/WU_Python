import { useEffect, useRef } from "react";
import "./RosterSelectionBar.css";

type Props = {
  selectedCount: number;
  hiddenCount: number;
  busy: boolean;
  hidden?: boolean;
  canRoster: boolean;
  canSignups: boolean;
  onAssign: (trigger: HTMLElement) => void;
  onBalance: (trigger: HTMLElement) => void;
  onSignup: (trigger: HTMLElement) => void;
  onClear: () => void;
  onHeight: (height: number) => void;
};

export default function RosterSelectionBar({
  selectedCount,
  hiddenCount,
  busy,
  hidden = false,
  canRoster,
  canSignups,
  onAssign,
  onBalance,
  onSignup,
  onClear,
  onHeight,
}: Props) {
  const bar = useRef<HTMLElement>(null);
  const overLimit = selectedCount > 50;
  const unavailable = busy || selectedCount === 0 || overLimit;

  useEffect(() => {
    const node = bar.current;
    if (!node || hidden) {
      if (selectedCount === 0) onHeight(0);
      return;
    }
    const measure = () => onHeight(node.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [onHeight, selectedCount, hidden]);

  useEffect(() => () => onHeight(0), [onHeight]);

  if (selectedCount === 0) return null;
  return (
    <section
      className="roster-selection-dock"
      ref={bar}
      aria-hidden={hidden || undefined}
      inert={hidden}
      aria-label="Selected roster actions"
    >
      <div className="roster-selection-dock-summary">
        <div>
          <strong>{selectedCount} selected</strong>
          {hiddenCount > 0 && <span>{hiddenCount} hidden by filters</span>}
          {overLimit && (
            <span role="alert">
              Select at most 50 accounts to use an action.
            </span>
          )}
        </div>
        <button
          type="button"
          className="roster-selection-dock-clear"
          onClick={onClear}
          disabled={busy}
          aria-label="Clear selected accounts"
        >
          ×
        </button>
      </div>
      <div className="roster-selection-dock-actions">
        {canRoster && (
          <button
            type="button"
            onClick={(event) => onAssign(event.currentTarget)}
            disabled={unavailable}
          >
            Assign
          </button>
        )}
        {canRoster && (
          <button
            type="button"
            onClick={(event) => onBalance(event.currentTarget)}
            disabled={unavailable}
          >
            Balance
          </button>
        )}
        {canSignups && (
          <button
            type="button"
            onClick={(event) => onSignup(event.currentTarget)}
            disabled={unavailable}
          >
            Signup
          </button>
        )}
      </div>
    </section>
  );
}
