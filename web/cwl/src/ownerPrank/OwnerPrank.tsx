import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { api, ApiError } from "../api";
import "../memberTour/tour.css";
import {
  cardFor,
  milestone,
  rickrollUrl,
  type PrankEvent,
  type PrankState,
} from "./model";
import "./ownerPrank.css";

type Props = {
  view: string;
  blockedByTour: boolean;
  startBlocked: boolean;
  replaySignal: number;
  onSettled: () => void;
  onReplayAvailable: (available: boolean) => void;
  onError: (message: string) => void;
};

const hasOtherDialog = () =>
  Boolean(
    document.querySelector(
      'dialog[open]:not(.owner-prank-dialog), [role="dialog"][aria-modal="true"]:not(.owner-prank-dialog), [role="alertdialog"][aria-modal="true"]:not(.owner-prank-dialog)',
    ),
  );

export default function OwnerPrank({
  view,
  blockedByTour,
  startBlocked,
  replaySignal,
  onSettled,
  onReplayAvailable,
  onError,
}: Props) {
  const [state, setState] = useState<PrankState | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [otherDialogOpen, setOtherDialogOpen] = useState(hasOtherDialog);
  const dialog = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const started = useRef(false);
  const visitClosed = useRef(false);
  const generation = useRef(0);
  const latestConfirmed = useRef<PrankState | null>(null);
  const inFlight = useRef<Promise<PrankState> | null>(null);
  const stateRef = useRef<PrankState | null>(null);
  stateRef.current = state;
  const openRef = useRef(open);
  openRef.current = open;
  const callbacks = useRef({ onSettled, onReplayAvailable, onError });
  callbacks.current = { onSettled, onReplayAvailable, onError };

  useEffect(() => {
    const sync = () => setOtherDialogOpen(hasOtherDialog());
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open", "aria-modal"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(
    () => () => {
      generation.current += 1;
      // StrictMode remounts effects in development without remounting state.
      // Let the second setup issue the read that the cleanup invalidated.
      started.current = false;
    },
    [],
  );

  const post = (
    event: PrankEvent,
    current: PrankState,
    card = current.card,
    branch?: "yes" | "no",
  ) => {
    const request = api<PrankState>("/prank/event", "POST", {
      event,
      card,
      run: current.run,
      ...(branch ? { branch } : {}),
    });
    inFlight.current = request;
    return request
      .then((received) => {
        latestConfirmed.current = received;
        return received;
      })
      .finally(() => {
        if (inFlight.current === request) inFlight.current = null;
      });
  };

  const reconcileStale = async (
    error: unknown,
    token: number,
    previous: PrankState,
  ) => {
    if (!(
      error instanceof ApiError &&
      (error.status === 400 || error.status === 409)
    ))
      return false;
    try {
      const fresh = await api<PrankState>("/prank/state");
      if (token !== generation.current) return true;
      if (
        fresh.card === previous.card &&
        fresh.branch === previous.branch &&
        fresh.run === previous.run &&
        !fresh.completed_at
      ) {
        callbacks.current.onError(
          "Prank progress could not be reconciled. Refresh this page to continue.",
        );
        finishVisible();
        return true;
      }
      latestConfirmed.current = fresh;
      setState(fresh);
      callbacks.current.onReplayAvailable(
        Boolean(fresh.can_replay && fresh.completed_at),
      );
      if (fresh.completed_at) finishVisible();
      else {
        if (!openRef.current) {
          previousFocus.current = document.activeElement as HTMLElement;
          setOpen(true);
        }
        setError(
          "Prank progress changed in another session. Continue from this card.",
        );
      }
    } catch {
      if (token === generation.current) {
        callbacks.current.onError(
          "Prank progress could not be read. Refresh this page to continue.",
        );
        finishVisible();
      }
    }
    return true;
  };

  const enter = async (received: PrankState, token: number) => {
    let next = received;
    try {
      if (next.card === 1 && next.branch)
        next = await post("prank_card_seen", next, 2);
      else if (next.card === 2) next = await post("prank_card_seen", next, 3);
      if (token !== generation.current) return;
      if (next.card === 1) next = await post("prank_opened", next);
      const event = milestone(next.card);
      if (event) next = await post(event, next);
      if (token !== generation.current) return;
      setState(next);
      callbacks.current.onReplayAvailable(
        Boolean(next.can_replay && next.completed_at),
      );
      previousFocus.current = document.activeElement as HTMLElement;
      setOpen(true);
    } catch (error) {
      if (token !== generation.current) return;
      if (await reconcileStale(error, token, next)) return;
      // A failed milestone cannot imply a completed run. Keep the last confirmed card.
      setState(next);
      previousFocus.current = document.activeElement as HTMLElement;
      setOpen(true);
      setError("A prank update failed. Continue or close this card.");
    }
  };

  useEffect(() => {
    if (blockedByTour || startBlocked || otherDialogOpen) {
      if (started.current && !openRef.current && !visitClosed.current) {
        generation.current += 1;
        started.current = false;
      }
      return;
    }
    if (started.current || visitClosed.current) return;
    started.current = true;
    const token = ++generation.current;
    void api<PrankState>("/prank/state")
      .then((received) => {
        if (token !== generation.current) return;
        latestConfirmed.current = received;
        setState(received);
        callbacks.current.onReplayAvailable(
          Boolean(received.can_replay && received.completed_at),
        );
        if (received.completed_at) callbacks.current.onSettled();
        else if (!blockedByTour && !startBlocked && !hasOtherDialog())
          void enter(received, token);
        else started.current = false;
      })
      .catch(() => {
        if (token === generation.current) callbacks.current.onSettled();
      });
  }, [view, blockedByTour, startBlocked, otherDialogOpen]);

  useEffect(() => {
    if (
      !replaySignal ||
      !stateRef.current?.can_replay ||
      !stateRef.current.completed_at
    )
      return;
    const token = ++generation.current;
    setBusy(true);
    setError("");
    void post("prank_replay", stateRef.current, 15)
      .then((received) => {
        if (token !== generation.current) return;
        visitClosed.current = false;
        callbacks.current.onReplayAvailable(false);
        void enter(received, token);
      })
      .catch(() => {
        if (token === generation.current)
          callbacks.current.onError(
            "Replay could not start. Try again from the account menu.",
          );
      })
      .finally(() => {
        if (token === generation.current) setBusy(false);
      });
  }, [replaySignal]);

  useLayoutEffect(() => {
    if (!open) return;
    const node = dialog.current;
    if (!node) return;
    node.showModal();
    node.querySelector<HTMLElement>(".owner-prank-close")?.focus();
    return () => node.close();
  }, [open]);

  useEffect(() => {
    if (!open || state?.card !== 2 || busy || error) return;
    const timer = window.setTimeout(() => void advance(), 2000);
    return () => window.clearTimeout(timer);
    // Card 2's timer starts when its confirmed server state appears.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, state?.card, busy, error]);

  const finishVisible = () => {
    generation.current += 1;
    visitClosed.current = true;
    setOpen(false);
    setBusy(false);
    setError("");
    callbacks.current.onSettled();
    window.requestAnimationFrame(() => previousFocus.current?.focus());
  };

  const closeEarly = () => {
    const current = stateRef.current;
    if (!openRef.current) return;
    const pending = inFlight.current;
    finishVisible();
    if (current && !current.completed_at) {
      void (async () => {
        if (pending) await pending.catch(() => {});
        const confirmed = latestConfirmed.current || current;
        if (!confirmed.completed_at)
          await post("prank_closed_early", confirmed).catch(() => {});
      })();
    }
  };

  const advance = async (choice?: "yes" | "no") => {
    const current = stateRef.current;
    if (!current || busy || !openRef.current) return;
    if (current.card === 1 && current.branch && choice !== current.branch)
      return;
    const token = generation.current;
    setBusy(true);
    setError("");
    let next = current;
    try {
      if (current.card === 15) {
        next = await post("prank_completed", next);
        if (token !== generation.current) return;
        setState(next);
        callbacks.current.onReplayAvailable(
          Boolean(next.can_replay && next.completed_at),
        );
        finishVisible();
        return;
      }
      if (current.card === 1 && choice && !current.branch) {
        next = await post(
          choice === "yes" ? "prank_bait_yes" : "prank_bait_no",
          next,
          1,
          choice,
        );
        if (token !== generation.current) return;
        setState(next);
      }
      if (token !== generation.current) return;
      next = await post("prank_card_seen", next, current.card + 1);
      if (token !== generation.current) return;
      setState(next);
      const event = milestone(next.card);
      if (event) next = await post(event, next);
      if (token !== generation.current) return;
      setState(next);
    } catch (error) {
      if (token === generation.current) {
        if (await reconcileStale(error, token, next)) return;
        setState(next);
        setError("A prank update failed. Continue or close this card.");
      }
    } finally {
      if (token === generation.current) setBusy(false);
    }
  };

  if (!open || !state || state.card < 1 || state.card > 15) return null;
  const card = cardFor(state.card, state.branch, state.signup_count);
  return createPortal(
    <dialog
      ref={dialog}
      className="owner-prank-dialog"
      aria-labelledby="owner-prank-title"
      onCancel={(event) => {
        event.preventDefault();
        closeEarly();
      }}
    >
      <article
        className={`tour-card owner-prank-card${card.art ? " has-art" : ""}${state.card === 10 || state.card === 13 ? " wide-character" : ""}${state.card <= 2 ? " plain" : ""}${state.card === 3 ? " jump" : ""}${state.card === 15 ? " farewell" : ""}`}
      >
        <button
          type="button"
          className="owner-prank-close"
          aria-label="Close prank"
          onClick={closeEarly}
        >
          <X size={20} aria-hidden="true" />
        </button>
        {card.art && (
          <img className="owner-prank-character" src={card.art} alt="" />
        )}
        <div className="owner-prank-copy">
          <h2 id="owner-prank-title">{card.title}</h2>
          <p>{card.body}</p>
          {state.card === 3 && (
            <p className="owner-prank-reassurance">
              No real signups were deleted.
            </p>
          )}
          {state.card === 10 && (
            <img
              className="owner-prank-rickroll"
              src={rickrollUrl}
              alt="Rick Astley dancing"
            />
          )}
          {error && (
            <p className="owner-prank-error" role="alert">
              {error}
            </p>
          )}
          <footer>
            {card.buttons.map((label, index) => (
              <button
                key={label}
                type="button"
                disabled={busy}
                className={index === 0 ? "primary" : ""}
                onClick={() =>
                  void advance(
                    state.card === 1 ? (index === 0 ? "yes" : "no") : undefined,
                  )
                }
              >
                {label}
              </button>
            ))}
            {state.card === 2 && error && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void advance()}
              >
                Continue
              </button>
            )}
            {state.card === 2 && <span role="status">Working…</span>}
          </footer>
        </div>
      </article>
    </dialog>,
    document.body,
  );
}
