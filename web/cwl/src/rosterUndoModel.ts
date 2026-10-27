export type RosterUndoState =
  | { status: 'available'; label: string }
  | { status: 'pending'; label: string }
  | { status: 'unavailable'; message: string }
  | { status: 'error'; message: string }

export type UndoPresentation = { message: string; actionLabel: string; canUndo: boolean; live: 'polite' | 'assertive' }

export function undoPresentation(state: RosterUndoState): UndoPresentation {
  switch (state.status) {
    case 'available':
      return { message: `Undo available: ${state.label}`, actionLabel: 'Undo', canUndo: true, live: 'polite' }
    case 'pending':
      return { message: `Undoing: ${state.label}`, actionLabel: 'Undoing…', canUndo: false, live: 'polite' }
    case 'unavailable':
      return { message: state.message, actionLabel: '', canUndo: false, live: 'polite' }
    case 'error':
      return { message: state.message, actionLabel: '', canUndo: false, live: 'assertive' }
  }
}
