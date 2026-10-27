import { describe, expect, it, vi } from 'vitest'
import { cycleDialogTab } from './actionPanelFocus'

function control(tabIndex = 0, visible = true, disabled = false) {
  return {
    tabIndex,
    matches: (selector: string) => selector === ':disabled' && disabled,
    getClientRects: () => visible ? [{}] : [],
    closest: () => null,
    focus: vi.fn(),
  } as unknown as HTMLElement
}

function fixture(active: Element | null, controls: HTMLElement[]) {
  const dialog = {
    querySelectorAll: () => controls,
    contains: (element: Node | null) => !!element && controls.includes(element as HTMLElement),
  } as unknown as HTMLElement
  const event = { key: 'Tab', shiftKey: false, preventDefault: vi.fn() } as unknown as KeyboardEvent
  return { dialog, event, active }
}

describe('cycleDialogTab', () => {
  it('wraps Shift+Tab from the first control to the last', () => {
    const first = control()
    const last = control()
    const test = fixture(first, [first, last])
    Object.assign(test.event, { shiftKey: true })
    expect(cycleDialogTab(test.dialog, test.event, test.active)).toBe(true)
    expect(test.event.preventDefault).toHaveBeenCalledOnce()
    expect(last.focus).toHaveBeenCalledOnce()
  })

  it('wraps Tab from the last control to the first', () => {
    const first = control()
    const last = control()
    const test = fixture(last, [first, last])
    expect(cycleDialogTab(test.dialog, test.event, test.active)).toBe(true)
    expect(first.focus).toHaveBeenCalledOnce()
  })

  it('does not include hidden, disabled, or negative-tabindex controls', () => {
    const first = control()
    const hidden = control(0, false)
    const disabled = control(0, true, true)
    const negative = control(-1)
    const test = fixture(first, [first, hidden, disabled, negative])
    Object.assign(test.event, { shiftKey: true })
    cycleDialogTab(test.dialog, test.event, test.active)
    expect(first.focus).toHaveBeenCalledOnce()
    expect(hidden.focus).not.toHaveBeenCalled()
    expect(disabled.focus).not.toHaveBeenCalled()
    expect(negative.focus).not.toHaveBeenCalled()
  })
})
