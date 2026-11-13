import { useRef, useState } from "react";
import useConfirmDialog from "./useConfirmDialog";
import {
  registerActionPanel,
  isTopActionPanel,
  panelHistoryState,
  installPanelBackHandler,
  backOutOfPanelEntry,
} from "./actionPanelHistory";

let managementConfirmationSerial = 0;
export default function useManagementConfirmation() {
  const [decision, setDecision] = useState(0);
  const pending = useRef(false);
  const { confirm, dialog } = useConfirmDialog(String(decision));
  async function ask(text: string, label = "Discard changes") {
    if (pending.current) return false;
    pending.current = true;
    const marker = `management-confirm-${++managementConfirmationSerial}`;
    const unregister = registerActionPanel(marker);
    const state = panelHistoryState(window.history.state, marker);
    let consumed = false;
    window.history.pushState(state, "", window.location.href);
    const uninstall = installPanelBackHandler({
      windowPort: window,
      historyPort: window.history,
      marker,
      panelState: state,
      isBusy: () => false,
      isTop: () => isTopActionPanel(marker),
      close: () => {
        consumed = true;
        setDecision((value) => value + 1);
      },
    });
    try {
      return await confirm(text, label);
    } finally {
      uninstall();
      unregister();
      if (!consumed)
        backOutOfPanelEntry({
          windowPort: window,
          historyPort: window.history,
          marker,
        });
      pending.current = false;
    }
  }
  return { ask, dialog };
}
