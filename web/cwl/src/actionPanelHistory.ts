export type PanelHistoryPort = Pick<History, 'state' | 'pushState' | 'back'>

export function panelHistoryState(state: unknown, marker: string) {
  const current = state && typeof state === 'object' ? state as Record<string, unknown> : {}
  return { ...current, wuActionPanel: marker }
}

export function installPanelBackHandler({
  windowPort,
  historyPort,
  marker,
  panelState,
  isBusy,
  close,
}: {
  windowPort: Window
  historyPort: PanelHistoryPort
  marker: string
  panelState: Record<string, unknown>
  isBusy: () => boolean
  close: () => void
}) {
  const onPopState = (event: PopStateEvent) => {
    const state = event.state && typeof event.state === 'object' ? event.state as Record<string, unknown> : {}
    if (state.wuActionPanel === marker) return
    // A panel entry is a same-route duplicate. Keep App's dirty-navigation guard
    // out of this panel-only Back action; its dashboard history index is unchanged.
    event.stopImmediatePropagation()
    if (isBusy()) {
      historyPort.pushState(panelState, '', windowPort.location.href)
      return
    }
    close()
  }
  windowPort.addEventListener('popstate', onPopState, true)
  return () => windowPort.removeEventListener('popstate', onPopState, true)
}

export function backOutOfPanelEntry({
  windowPort,
  historyPort,
  marker,
}: {
  windowPort: Window
  historyPort: PanelHistoryPort
  marker: string
}) {
  const current = historyPort.state && typeof historyPort.state === 'object'
    ? historyPort.state as Record<string, unknown>
    : {}
  if (current.wuActionPanel !== marker) return

  let timeout = 0
  const suppressAppPop = (event: PopStateEvent) => {
    windowPort.removeEventListener('popstate', suppressAppPop, true)
    windowPort.clearTimeout(timeout)
    event.stopImmediatePropagation()
  }
  windowPort.addEventListener('popstate', suppressAppPop, true)
  timeout = windowPort.setTimeout(() => windowPort.removeEventListener('popstate', suppressAppPop, true), 1500)
  historyPort.back()
}


export type TriggerRect = { top: number; right: number; bottom: number }
export type ViewportSize = { width: number; height: number }
export type PanelAnchorStyle = {
  '--action-panel-top': string
  '--action-panel-bottom': string
  '--action-panel-right': string
  '--action-panel-width': string
  '--action-panel-max-height': string
}

export function actionPanelAnchor(rect: TriggerRect, viewport: ViewportSize): PanelAnchorStyle {
  const margin = 12
  const gap = 8
  const spaceBelow = Math.max(0, viewport.height - rect.bottom - margin - gap)
  const spaceAbove = Math.max(0, rect.top - margin - gap)
  const placeAbove = spaceBelow < 280 && spaceAbove > spaceBelow
  const available = placeAbove ? spaceAbove : spaceBelow
  const right = Math.max(margin, viewport.width - rect.right)
  const width = Math.max(0, Math.min(544, viewport.width - right - margin))

  return {
    '--action-panel-top': placeAbove ? 'auto' : `${Math.min(viewport.height - margin, rect.bottom + gap)}px`,
    '--action-panel-bottom': placeAbove ? `${Math.min(viewport.height - margin, viewport.height - rect.top + gap)}px` : 'auto',
    '--action-panel-right': `${right}px`,
    '--action-panel-width': `${width}px`,
    '--action-panel-max-height': `${Math.max(120, Math.min(available || viewport.height - margin * 2, viewport.height - margin * 2))}px`,
  }
}
