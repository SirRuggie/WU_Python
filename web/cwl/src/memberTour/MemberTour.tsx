import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import { CircleHelp, Sparkles, X } from "lucide-react";
import {
  artAspect,
  invitedThisSession,
  rememberSession,
  readPreference,
  savePreference,
  shouldInvite,
  skipPreference,
  steps,
} from "./model";
import type { SignupTourState, TourPage } from "./session";
import Glove from "./Glove";
import { placeCard, type Box } from "./placement";
import "./tour.css";

type Props = {
  view: string;
  menuOpen: boolean;
  onMenu: (open: boolean) => void;
  onActive: (active: boolean) => boolean | void;
  onNavigate?: (page: TourPage, step: number) => void;
  signupState?: SignupTourState;
  startBlocked?: boolean;
  inviteBlocked?: boolean;
};

export default function MemberTour({
  view,
  menuOpen,
  onMenu,
  onActive,
  onNavigate,
  signupState = "open",
  startBlocked,
  inviteBlocked,
}: Props) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [dontShow, setDontShow] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
  const [gloveScale, setGloveScale] = useState(1);
  const dialog = useRef<HTMLDialogElement>(null);
  const card = useRef<HTMLElement>(null);
  const dismissedSession = useRef(false);
  const replay = useRef(false);
  const [position, setPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const initial = useRef({
    menu: false,
    scroll: 0,
    focus: null as HTMLElement | null,
  });
  const onMenuRef = useRef(onMenu);
  onMenuRef.current = onMenu;
  const callbacks = useRef({ onActive, onNavigate });
  callbacks.current = { onActive, onNavigate };
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(
    () => () => {
      if (openRef.current) callbacks.current.onActive(false);
    },
    [],
  );
  const [startError, setStartError] = useState("");
  const [shake, setShake] = useState(0);
  const current = steps[step];
  useEffect(() => {
    if (startBlocked === false) setStartError("");
  }, [startBlocked]);
  const closed = step >= 3 && step <= 7 && signupState === "closed";
  const empty = step >= 5 && step <= 7 && signupState === "empty";
  const allSigned = step >= 5 && step <= 7 && signupState === "all-signed";
  const failed = step >= 3 && step <= 7 && signupState === "error";
  const targetId = failed
    ? ""
    : closed
      ? "signup-closed"
      : empty
        ? "signup-missing"
        : allSigned
          ? ""
          : current.target;
  const text = failed
    ? "We couldn't load your accounts — you can still finish the tour."
    : closed
      ? "Signups are closed right now — next month, this is where you'll sign up."
      : empty
        ? "Link your Clash account here first."
        : allSigned
          ? "All your accounts are already signed up — nice!"
          : current.text;
  const copy = text.split("\n").map((line) =>
    line
      .split(/\*\*(.*?)\*\*/g)
      .map((part, index) =>
        index % 2 === 1 ? <strong key={index}>{part}</strong> : part,
      ),
  );
  const sidebarStep = [
    "home",
    "todo",
    "register",
    "saved",
    "assignments",
  ].includes(targetId);

  const start = (manual = false) => {
    if (callbacks.current.onActive(true) === false) {
      setStartError("Save or discard your changes first.");
      return;
    }
    setStartError("");
    replay.current = manual;
    dismissedSession.current = true;
    rememberSession();
    initial.current = {
      menu: menuOpen,
      scroll: window.scrollY,
      focus: document.activeElement as HTMLElement,
    };
    setStep(0);
    setDontShow(readPreference().dismissed);
    setOpen(true);
  };
  const close = (reason: "exit" | "skip" | "finish") => {
    if (reason === "skip") {
      if (!replay.current) savePreference(skipPreference(readPreference()));
    } else dismissedSession.current = true;
    if (reason === "finish" || dontShow)
      savePreference({ ...readPreference(), dismissed: true });
    try {
      callbacks.current.onActive(false);
    } finally {
      openRef.current = false;
      setOpen(false);
      onMenuRef.current(initial.current.menu);
      window.requestAnimationFrame(() => {
        window.scrollTo(0, initial.current.scroll);
        initial.current.focus?.focus();
      });
    }
  };
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const back = () => {
      if (openRef.current) closeRef.current("exit");
    };
    window.addEventListener("wu-tour-back", back);
    return () => window.removeEventListener("wu-tour-back", back);
  }, []);
  const advance = (targetTap = false) => {
    if (step === 7 && targetTap && !closed && !empty && !allSigned) {
      setShake((value) => value + 1);
      return;
    }
    if (step >= 3 && step <= 7 && signupState === "loading") return;
    if (closed || empty || failed) {
      setStep(9);
      return;
    }
    if (allSigned) {
      setStep(8);
      return;
    }
    if (step === 4 || step === 5) {
      const target = document.querySelector<HTMLElement>(
        `[data-tour-target="${targetId}"]`,
      );
      if (!target || target.matches(":disabled")) return;
      if (step === 4) target.click();
      else {
        const checkbox =
          target instanceof HTMLInputElement
            ? target
            : target.querySelector<HTMLInputElement>('input[type="checkbox"]');
        if (!checkbox || checkbox.disabled) return;
        if (!checkbox.checked) checkbox.click();
      }
    }
    if (step === steps.length - 1) close("finish");
    else setStep(step + 1);
  };
  useEffect(() => {
    if (!open || step === 0) return;
    const page: TourPage =
      step === 1 || step === 12
        ? "home"
        : step === 2
          ? "todo"
          : step === 10
            ? "saved"
            : step === 11
              ? "assignments"
              : "register";
    callbacks.current.onNavigate?.(page, step);
  }, [open, step]);

  useEffect(() => {
    if (view !== "home" || inviteBlocked) return;
    if (
      !open &&
      !dismissedSession.current &&
      !invitedThisSession() &&
      shouldInvite(readPreference())
    )
      start();
    // Only visiting Home invites; other renders do not repeat an invitation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, inviteBlocked]);
  useEffect(() => {
    if (!open) return;
    const sync = () =>
      onMenuRef.current(
        sidebarStep && window.matchMedia("(max-width: 900px)").matches,
      );
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, [open, sidebarStep, step, view]);
  useLayoutEffect(() => {
    if (!open) return;
    const node = dialog.current!;
    node.showModal();
    return () => node.close();
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    setBox(null);
    setPosition(null);
    const nav = document.querySelector<HTMLElement>(".sidebar nav");
    const originalNavHeight = nav?.style.maxHeight ?? "";
    const update = () => {
      const target = targetId
        ? document.querySelector<HTMLElement>(
            `[data-tour-target="${targetId}"]`,
          )
        : null;
      if (!target || !target.getClientRects().length) {
        setBox(null);
        return;
      }
      let rect = target.getBoundingClientRect();
      if (!sidebarStep && window.innerWidth <= 900 && card.current) {
        const panelTop = card.current.getBoundingClientRect().top;
        const gap = Math.max(18, Math.min(68, panelTop - rect.height - 64));
        const availableBottom = panelTop - gap;
        if (rect.bottom > availableBottom) {
          window.scrollBy(0, rect.bottom - availableBottom);
          rect = target.getBoundingClientRect();
        }
      }
      if (
        rect.width <= 0 ||
        rect.height <= 0 ||
        rect.left < 0 ||
        rect.top < 0 ||
        rect.right > window.innerWidth + 1 ||
        rect.bottom > window.innerHeight + 1
      ) {
        setBox(null);
        return;
      }
      if (window.innerWidth > 900 && card.current)
        setPosition(
          placeCard(rect, card.current.getBoundingClientRect(), {
            width: window.innerWidth,
            height: window.innerHeight,
          }),
        );
      const panelTop =
        card.current?.getBoundingClientRect().top ?? window.innerHeight;
      const spaceBelow =
        Math.min(
          window.innerHeight,
          panelTop > rect.bottom ? panelTop : window.innerHeight,
        ) -
        rect.bottom -
        8;
      setGloveScale(Math.max(0.15, Math.min(1, spaceBelow / 68)));
      setBox({
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      });
    };
    const frame = requestAnimationFrame(() => {
      // Reserve the measured card height before scrolling a phone navigation
      // target into view; longer translated/caption text must not cover it.
      if (sidebarStep && nav && window.innerWidth <= 900 && card.current) {
        nav.style.maxHeight = `${Math.max(100, card.current.getBoundingClientRect().top - nav.getBoundingClientRect().top - 16)}px`;
      }
      document
        .querySelector<HTMLElement>(`[data-tour-target="${targetId}"]`)
        ?.scrollIntoView({ block: "nearest" });
      update();
      card.current?.querySelector<HTMLElement>("h2")?.focus();
    });
    const observer = new ResizeObserver(update);
    observer.observe(document.body);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    let followFrame = 0;
    const until = performance.now() + 800;
    const follow = () => {
      update();
      if (performance.now() < until)
        followFrame = requestAnimationFrame(follow);
    };
    followFrame = requestAnimationFrame(follow);
    document.addEventListener("transitionend", update, true);
    const target = document.querySelector(`[data-tour-target="${targetId}"]`);
    if (target) observer.observe(target);
    if (card.current) observer.observe(card.current);
    return () => {
      if (nav) nav.style.maxHeight = originalNavHeight;
      cancelAnimationFrame(frame);
      cancelAnimationFrame(followFrame);
      document.removeEventListener("transitionend", update, true);
      observer.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, step, targetId, menuOpen, view, signupState]);

  return (
    <>
      <button
        type="button"
        className="tour-launcher"
        disabled={inviteBlocked}
        onClick={() => start(true)}
      >
        <CircleHelp size={20} aria-hidden="true" /> Help &amp; tour
      </button>
      {startError && <p role="status">{startError}</p>}
      {open &&
        createPortal(
          <dialog
            ref={dialog}
            className={`member-tour ${box ? "has-target" : "centered"}`}
            aria-labelledby="tour-title"
            onCancel={(e) => {
              e.preventDefault();
              close("exit");
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                close("exit");
              }
              if (e.key !== "Tab") return;
              const controls = [
                ...dialog.current!.querySelectorAll<HTMLElement>(
                  "button:not(:disabled), a[href], input:not(:disabled)",
                ),
              ].filter((el) => el.getClientRects().length);
              const index = controls.indexOf(
                document.activeElement as HTMLElement,
              );
              if (e.shiftKey && index <= 0) {
                e.preventDefault();
                controls.at(-1)?.focus();
              } else if (
                !e.shiftKey &&
                (index < 0 || index === controls.length - 1)
              ) {
                e.preventDefault();
                controls[0]?.focus();
              }
            }}
          >
            {!box && <div className="tour-dim" />}
            {box && (
              <button
                type="button"
                className="tour-spotlight"
                style={
                  { ...box, "--tour-glove-scale": gloveScale } as CSSProperties
                }
                onClick={() => advance(true)}
                aria-label={`Continue: ${current.title}`}
              >
                <Glove />
              </button>
            )}
            <section
              ref={card}
              className={`tour-card${artAspect[current.art] > 1.3 ? " wide-art" : ""}`}
              style={
                {
                  "--art-aspect": artAspect[current.art],
                  ...(box && window.innerWidth > 900 ? position : {}),
                } as CSSProperties
              }
            >
              <img
                key={current.art}
                className="tour-character"
                src={`/assets/tour/${current.art}.webp`}
                alt=""
                loading="lazy"
              />
              <button
                type="button"
                className="tour-close"
                onClick={() => close("exit")}
                aria-label="Close tour"
              >
                <X size={20} />
              </button>
              <div className="tour-copy">
                <p className="tour-step">
                  <Sparkles size={14} aria-hidden="true" /> Step{" "}
                  {current.number} of 8
                </p>
                <h2 id="tour-title" tabIndex={-1}>
                  {current.title}
                </h2>
                {copy.map((line, index) => (
                  <p
                    key={`${shake}-${index}`}
                    className={shake ? "tour-shake" : undefined}
                  >
                    {line}
                  </p>
                ))}
                {step === 0 && (
                  <label className="tour-remember">
                    <input
                      type="checkbox"
                      checked={dontShow}
                      onChange={(e) => {
                        setDontShow(e.target.checked);
                        savePreference({
                          ...readPreference(),
                          dismissed: e.target.checked,
                        });
                      }}
                    />{" "}
                    Don't show this again
                  </label>
                )}
              </div>
              <footer>
                <span
                  className="tour-progress"
                  aria-label={`Step ${current.number} of 8`}
                >
                  {Array.from({ length: 8 }, (_, i) => (
                    <i
                      key={i}
                      className={
                        i + 1 === current.number
                          ? "current"
                          : i < current.number
                            ? "done"
                            : ""
                      }
                    />
                  ))}
                </span>
                {step > 0 && (
                  <button
                    type="button"
                    className="tour-back"
                    disabled={step === 0}
                    onClick={() => setStep(step - 1)}
                  >
                    Back
                  </button>
                )}
                <button
                  type="button"
                  className="tour-next"
                  disabled={step >= 3 && step <= 7 && signupState === "loading"}
                  onClick={() => advance()}
                >
                  {step === 0
                    ? "Start tour"
                    : step === 12
                      ? "Finish"
                      : "Next →"}
                </button>
              </footer>
              {step === 0 && (
                <button
                  type="button"
                  className="tour-skip"
                  onClick={() => close("skip")}
                >
                  Skip for now
                </button>
              )}
            </section>
            {step === 8 && (
              <div className="tour-confetti" aria-hidden="true">
                {Array.from({ length: 24 }, (_, i) => (
                  <i
                    key={i}
                    style={{
                      left: `${(i * 17) % 100}%`,
                      animationDelay: `${(i % 5) * 0.12}s`,
                      background: i % 2 ? "#FAC775" : "#68d7b0",
                    }}
                  />
                ))}
              </div>
            )}
          </dialog>,
          document.body,
        )}
    </>
  );
}
