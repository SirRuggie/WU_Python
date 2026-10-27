export function cycleDialogTab(
  dialog: Pick<HTMLElement, 'querySelectorAll' | 'contains'>,
  event: Pick<KeyboardEvent, 'key' | 'shiftKey' | 'preventDefault'>,
  active: Element | null,
) {
  if (event.key !== 'Tab') return false
  const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
    'button, a[href], input, select, textarea, summary, [tabindex]',
  )).filter(element => {
    if (element.tabIndex < 0 || element.matches(':disabled') || !element.getClientRects().length) return false
    if (element.closest('[hidden], [inert], [aria-hidden="true"]')) return false
    const closedDetails = element.closest('details:not([open])')
    const summary = closedDetails?.querySelector('summary')
    return !closedDetails || !!summary?.contains(element)
  })
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (!first || !last) return false

  if (event.shiftKey && (active === first || !dialog.contains(active))) {
    event.preventDefault()
    last.focus()
    return true
  }
  if (!event.shiftKey && (active === last || !dialog.contains(active))) {
    event.preventDefault()
    first.focus()
    return true
  }
  return false
}
