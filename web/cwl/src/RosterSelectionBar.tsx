import { useEffect, useRef } from "react";
import { ClipboardCheck, Scale, UserRoundPlus, X } from "lucide-react";
import { Button, StatusPill } from "./rosterUi/primitives";
import "./RosterSelectionBar.css";

type Props = {
  selectedCount: number;
  hiddenCount: number;
  unloadedCount?: number;
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
  unloadedCount = 0,
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
      className="roster-ui roster-selection-dock"
      ref={bar}
      aria-hidden={hidden || undefined}
      inert={hidden}
      aria-label="Selected roster actions"
    >
      <div className="roster-selection-dock-summary">
        <div>
          <StatusPill>{selectedCount} selected</StatusPill>
          {hiddenCount > 0 && (
            <StatusPill tone="info">{hiddenCount} hidden by filters</StatusPill>
          )}
          {unloadedCount > 0 && (
            <StatusPill tone="info">{unloadedCount} not shown yet</StatusPill>
          )}
          {overLimit && (
            <span role="alert" className="roster-selection-limit">
              <StatusPill tone="danger">Max 50 per action</StatusPill>
              <span>Narrow your selection to 50 or fewer</span>
            </span>
          )}
        </div>
        <Button
          variant="icon"
          icon={X}
          className="roster-selection-dock-clear"
          onClick={onClear}
          disabled={busy}
          label="Clear selected accounts"
        />
      </div>
      <div className="roster-selection-dock-actions">
        {canRoster && (
          <Button
            variant="primary"
            icon={UserRoundPlus}
            onClick={(event) => onAssign(event.currentTarget)}
            disabled={unavailable}
          >
            Assign
          </Button>
        )}
        {canRoster && (
          <Button
            icon={Scale}
            onClick={(event) => onBalance(event.currentTarget)}
            disabled={unavailable}
          >
            Balance
          </Button>
        )}
        {canSignups && (
          <Button
            icon={ClipboardCheck}
            onClick={(event) => onSignup(event.currentTarget)}
            disabled={unavailable}
          >
            Signup
          </Button>
        )}
      </div>
    </section>
  );
}
