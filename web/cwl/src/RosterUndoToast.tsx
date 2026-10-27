import { undoPresentation, type RosterUndoState } from './rosterUndoModel'
import './RosterUndoToast.css'

export default function RosterUndoToast({
  state,
  onUndo,
  bottomOffset = 0,
  onDismiss,
}: {
  state: RosterUndoState
  onUndo: () => void
  bottomOffset?: number
  onDismiss?: () => void
}) {
  const presentation = undoPresentation(state)
  return (
    <div
      className={`roster-undo-toast is-${state.status}`}
      role={presentation.live === 'assertive' ? 'alert' : 'status'}
      aria-live={presentation.live}
      style={{ '--roster-undo-offset': `${Math.max(0, bottomOffset)}px` } as React.CSSProperties}
    >
      <span>{presentation.message}</span>
      {presentation.canUndo && (
        <button type="button" onClick={onUndo} disabled={state.status !== 'available'}>
          {presentation.actionLabel}
        </button>
      )}
      {onDismiss && <button type="button" className="roster-undo-dismiss" onClick={onDismiss} aria-label="Dismiss undo notification">×</button>}
    </div>
  )
}
