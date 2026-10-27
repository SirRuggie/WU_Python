import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import "./ActionPanel.css";
import {
  backOutOfPanelEntry,
  installPanelBackHandler,
  isTopActionPanel,
  panelHistoryState,
  registerActionPanel,
} from "./actionPanelHistory";
import { cycleDialogTab } from "./actionPanelFocus";

type Props = {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  onClose: () => void | boolean;
  busy?: boolean;
  trigger: HTMLElement | null;
  expandOnSearchFocus?: boolean;
  variant?: "default" | "side";
};

function focusFallback() {
  const heading = document.querySelector<HTMLElement>(
    '[data-dashboard-focus-fallback], main h1, main [tabindex="-1"]',
  );
  if (!heading) return;
  if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
  heading.focus({ preventScroll: true });
}

function canRestoreFocus(element: HTMLElement | null) {
  if (!element?.isConnected || element.matches(":disabled")) return false;
  if (element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
  return (
    element.getClientRects().length > 0 &&
    getComputedStyle(element).display !== "none" &&
    getComputedStyle(element).visibility !== "hidden"
  );
}

export default function ActionPanel({
  title,
  children,
  footer,
  className = "",
  onClose,
  busy = false,
  trigger,
  expandOnSearchFocus = false,
  variant = "default",
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const busyRef = useRef(busy);
  const onCloseRef = useRef(onClose);
  const panelId = useId();
  const marker = `action-panel:${panelId}`;
  const [searchFocused, setSearchFocused] = useState(false);
  busyRef.current = busy;
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    const modal = dialog.current;
    if (!modal) return;
    const unregisterPanel = registerActionPanel(marker);
    const panelState = panelHistoryState(history.state, marker);
    history.pushState(panelState, "", location.href);
    modal.showModal();
    // Focus the explicit close control. Search inputs remain unfocused on open.
    closeButton.current?.focus({ preventScroll: true });

    const removeBackHandler = installPanelBackHandler({
      windowPort: window,
      historyPort: history,
      marker,
      panelState,
      isBusy: () => busyRef.current,
      isTop: () => isTopActionPanel(marker),
      close: () => onCloseRef.current(),
    });

    return () => {
      removeBackHandler();
      if (modal.open) modal.close();
      const current =
        history.state && typeof history.state === "object"
          ? (history.state as Record<string, unknown>)
          : {};
      if (current.wuActionPanel === marker) {
        backOutOfPanelEntry({
          windowPort: window,
          historyPort: history,
          marker,
        });
      }
      unregisterPanel();
      window.requestAnimationFrame(() => {
        // A menu may hand off to another modal in the same render. Its initial
        // focus belongs to that modal, not to the now-inert menu trigger.
        if (
          document.querySelector("dialog[open]") &&
          !trigger?.closest("dialog[open]")
        )
          return;
        if (canRestoreFocus(trigger)) trigger?.focus({ preventScroll: true });
        else focusFallback();
      });
    };
    // Deliberately bind this entry to mount/unmount; prop changes must not add history entries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    if (!busy) onClose();
  };

  return createPortal(
    <dialog
      ref={dialog}
      className={`action-panel action-panel-${variant}${searchFocused ? " is-search-focused" : ""}${className ? ` ${className}` : ""}`}
      aria-labelledby={`${panelId}-title`}
      onKeyDown={(event) => {
        if (
          isTopActionPanel(marker) &&
          dialog.current?.contains(event.target as Node)
        )
          cycleDialogTab(dialog.current, event, document.activeElement);
      }}
      onCancel={(event) => {
        // React portal events from a nested native dialog are not this panel's cancel.
        if (event.target !== dialog.current) return;
        if (!isTopActionPanel(marker)) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (isTopActionPanel(marker) && event.target === dialog.current)
          close();
      }}
      onFocusCapture={(event) => {
        if (!isTopActionPanel(marker)) return;
        if (
          expandOnSearchFocus &&
          (event.target as HTMLElement).matches(
            'input[type="search"], [data-action-panel-search]',
          )
        ) {
          setSearchFocused(true);
        }
      }}
      onBlurCapture={(event) => {
        if (!isTopActionPanel(marker)) return;
        if (
          expandOnSearchFocus &&
          (event.target as HTMLElement).matches(
            'input[type="search"], [data-action-panel-search]',
          )
        ) {
          setSearchFocused(false);
        }
      }}
    >
      <header className="action-panel-heading">
        <h2 id={`${panelId}-title`}>{title}</h2>
        <button
          ref={closeButton}
          type="button"
          className="action-panel-close"
          onClick={close}
          disabled={busy}
          aria-label="Close panel"
        >
          Close
        </button>
      </header>
      <div className="action-panel-content">{children}</div>
      {footer != null && (
        <footer className="action-panel-footer">{footer}</footer>
      )}
    </dialog>,
    document.body,
  );
}
