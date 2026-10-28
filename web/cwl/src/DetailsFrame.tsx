import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import ConfirmDialog from "./ConfirmDialog";
import { Button } from "./rosterUi/primitives";
import { cycleDialogTab } from "./actionPanelFocus";
import {
  backOutOfPanelEntry,
  isTopActionPanel,
  installPanelBackHandler,
  panelHistoryState,
  registerActionPanel,
} from "./actionPanelHistory";
import {
  detailsAccount,
  detailsUrl,
  registerDetailsGuard,
} from "./detailsNavigation";
import "./DetailsFrame.css";

export default function DetailsFrame({
  tag,
  name,
  dirty,
  busy,
  onClose,
  previous,
  next,
  children,
}: {
  tag: string;
  name: string;
  dirty: boolean;
  busy: boolean;
  onClose: () => void;
  previous?: () => void;
  next?: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [pending, setPending] = useState<null | (() => void)>(null);
  const current = useRef({ dirty, busy, onClose, tag });
  current.current = { dirty, busy, onClose, tag };
  const marker = useRef(
    `details:${Math.random().toString(36).slice(2)}`,
  ).current;
  const request = (action: () => void) => {
    if (current.current.busy) return;
    if (current.current.dirty) setPending(() => action);
    else action();
  };
  useLayoutEffect(() => registerDetailsGuard(request), []);
  useLayoutEffect(() => {
    const modal = dialog.current!;
    const trigger =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const unregister = registerActionPanel(marker);
    const state = panelHistoryState(history.state, marker);
    // A direct link gets a list entry beneath it, so Back still closes Details.
    if (detailsAccount())
      history.replaceState(history.state, "", detailsUrl(null));
    history.pushState(state, "", detailsUrl(current.current.tag));
    const media = matchMedia("(min-width: 768px)");
    const show = () => {
      if (modal.open) modal.close();
      if (media.matches) modal.show();
      else modal.showModal();
    };
    show();
    closeButton.current?.focus({ preventScroll: true });
    media.addEventListener("change", show);
    const removeBackHandler = installPanelBackHandler({
      windowPort: window,
      historyPort: {
        get state() {
          return history.state;
        },
        pushState: (data) =>
          history.pushState(data, "", detailsUrl(current.current.tag)),
        back: () => history.back(),
      },
      marker,
      panelState: state,
      isTop: () => isTopActionPanel(marker),
      isBusy: () => current.current.busy,
      close: () => {
        if (current.current.dirty) {
          request(() => current.current.onClose());
          return false;
        }
        current.current.onClose();
      },
    });
    return () => {
      removeBackHandler();
      media.removeEventListener("change", show);
      modal.close();
      unregister();
      backOutOfPanelEntry({ windowPort: window, historyPort: history, marker });
      requestAnimationFrame(() => {
        if (trigger?.isConnected) trigger.focus({ preventScroll: true });
      });
    };
  }, []);
  useLayoutEffect(() => {
    if (history.state?.wuActionPanel === marker)
      history.replaceState(history.state, "", detailsUrl(tag));
  }, [tag, marker]);
  return createPortal(
    <dialog
      ref={dialog}
      className="details-frame roster-ui"
      aria-label={`Details for ${name}`}
      onCancel={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        request(onClose);
      }}
      onKeyDown={(event) => {
        if (
          matchMedia("(max-width: 767px)").matches &&
          isTopActionPanel(marker) &&
          dialog.current?.contains(event.target as Node)
        )
          cycleDialogTab(dialog.current, event, document.activeElement);
      }}
    >
      <header className="details-frame-navigation">
        <button
          ref={closeButton}
          type="button"
          className="roster-ui-button is-secondary"
          disabled={busy}
          onClick={() => request(onClose)}
        >
          ‹ Build roster
        </button>
        {(previous !== undefined || next !== undefined) && (
          <nav
            aria-label="Browse accounts"
            className="details-player-navigation"
          >
            <Button
              disabled={busy || !previous}
              onClick={() => previous && request(previous)}
            >
              ‹ Previous
            </Button>
            <Button
              disabled={busy || !next}
              onClick={() => next && request(next)}
            >
              Next ›
            </Button>
          </nav>
        )}
      </header>
      {children}
      {pending && (
        <ConfirmDialog
          heading="Discard unsaved weight?"
          text={`Discard the unsaved weight for ${name}?`}
          confirmLabel="Discard"
          onCancel={() => setPending(null)}
          onConfirm={() => {
            const action = pending;
            setPending(null);
            action();
          }}
        />
      )}
    </dialog>,
    document.body,
  );
}
