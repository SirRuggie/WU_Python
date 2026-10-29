import { Undo2, X } from "lucide-react";
import { Button, StatusPill } from "./rosterUi/primitives";
import { undoPresentation, type RosterUndoState } from "./rosterUndoModel";
import "./RosterUndoToast.css";

export default function RosterUndoToast({
  state,
  onUndo,
  bottomOffset = 0,
  onDismiss,
}: {
  state: RosterUndoState;
  onUndo: () => void;
  bottomOffset?: number;
  onDismiss?: () => void;
}) {
  const presentation = undoPresentation(state);
  return (
    <div
      className={`roster-ui roster-undo-toast is-${state.status}`}
      role={presentation.live === "assertive" ? "alert" : "status"}
      aria-live={presentation.live}
      style={
        {
          "--roster-undo-offset": `${Math.max(0, bottomOffset)}px`,
        } as React.CSSProperties
      }
    >
      <StatusPill
        tone={
          state.status === "error"
            ? "danger"
            : state.status === "available"
              ? "warning"
              : "neutral"
        }
      >
        {presentation.message}
      </StatusPill>
      {presentation.canUndo && (
        <Button
          icon={Undo2}
          onClick={onUndo}
          disabled={state.status !== "available"}
        >
          {presentation.actionLabel}
        </Button>
      )}
      {onDismiss && (
        <Button
          variant="icon"
          icon={X}
          className="roster-undo-dismiss"
          onClick={onDismiss}
          label="Dismiss undo notification"
        />
      )}
    </div>
  );
}
