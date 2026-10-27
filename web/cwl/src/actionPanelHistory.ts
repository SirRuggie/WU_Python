export type PanelHistoryPort = Pick<History, "state" | "pushState" | "back">;

const activePanels: string[] = [];

export function registerActionPanel(marker: string) {
  activePanels.push(marker);
  let registered = true;
  return () => {
    if (!registered) return;
    registered = false;
    const index = activePanels.lastIndexOf(marker);
    if (index >= 0) activePanels.splice(index, 1);
  };
}

export function isTopActionPanel(marker: string) {
  return activePanels.at(-1) === marker;
}

export function panelHistoryState(state: unknown, marker: string) {
  const current =
    state && typeof state === "object"
      ? (state as Record<string, unknown>)
      : {};
  return { ...current, wuActionPanel: marker };
}

export function installPanelBackHandler({
  windowPort,
  historyPort,
  marker,
  panelState,
  isBusy,
  isTop = () => true,
  close,
}: {
  windowPort: Window;
  historyPort: PanelHistoryPort;
  marker: string;
  panelState: Record<string, unknown>;
  isBusy: () => boolean;
  isTop?: () => boolean;
  close: () => void | boolean;
}) {
  const onPopState = (event: PopStateEvent) => {
    if (!isTop()) return;
    const state =
      event.state && typeof event.state === "object"
        ? (event.state as Record<string, unknown>)
        : {};
    if (state.wuActionPanel === marker) return;
    // A panel entry is a same-route duplicate. Keep App's dirty-navigation guard
    // out of this panel-only Back action; its dashboard history index is unchanged.
    event.stopImmediatePropagation();
    if (isBusy()) {
      historyPort.pushState(panelState, "", windowPort.location.href);
      return;
    }
    if (close() === false) {
      // A discard confirmation was cancelled after Back consumed this marker.
      // Restore it so the next Back still targets the panel.
      historyPort.pushState(panelState, "", windowPort.location.href);
    }
  };
  windowPort.addEventListener("popstate", onPopState, true);
  return () => windowPort.removeEventListener("popstate", onPopState, true);
}

export function backOutOfPanelEntry({
  windowPort,
  historyPort,
  marker,
}: {
  windowPort: Window;
  historyPort: PanelHistoryPort;
  marker: string;
}) {
  const current =
    historyPort.state && typeof historyPort.state === "object"
      ? (historyPort.state as Record<string, unknown>)
      : {};
  if (current.wuActionPanel !== marker) return;

  let timeout = 0;
  const suppressAppPop = (event: PopStateEvent) => {
    windowPort.removeEventListener("popstate", suppressAppPop, true);
    windowPort.clearTimeout(timeout);
    event.stopImmediatePropagation();
  };
  windowPort.addEventListener("popstate", suppressAppPop, true);
  timeout = windowPort.setTimeout(
    () => windowPort.removeEventListener("popstate", suppressAppPop, true),
    1500,
  );
  historyPort.back();
}
