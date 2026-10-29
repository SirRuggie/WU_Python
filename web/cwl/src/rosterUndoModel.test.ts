import { describe, expect, it } from 'vitest'
import { undoPresentation, type RosterUndoState } from './rosterUndoModel'

describe('undoPresentation', () => {
  it('offers an explicit undo only while the operation is available', () => {
    const state: RosterUndoState = { status: 'available', label: 'Moved 2 accounts' }
    expect(undoPresentation(state)).toEqual({
      message: 'Undo available: Moved 2 accounts', actionLabel: 'Undo', canUndo: true, live: 'polite',
    })
  })

  it('prevents duplicate undo while the request is pending', () => {
    expect(undoPresentation({ status: 'pending', label: 'Moved 2 accounts' })).toMatchObject({
      message: 'Undoing: Moved 2 accounts', canUndo: false,
    })
  })

  it('announces unavailable state and surfaces failures assertively', () => {
    expect(undoPresentation({ status: 'unavailable', message: 'Undo has expired.' })).toMatchObject({
      message: 'Undo has expired.', canUndo: false, live: 'polite',
    })
    expect(undoPresentation({ status: 'error', message: 'Could not undo this change.' })).toMatchObject({
      message: 'Could not undo this change.', canUndo: false, live: 'assertive',
    })
  })
})
