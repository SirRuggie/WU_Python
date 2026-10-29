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
  policyNotice,
  policyUrl,
  readPreference,
  savePreference,
  shouldInvite,
  skipPreference,
  steps,
} from "./model";
import Practice from "./Practice";
import Glove from "./Glove";
import { placeCard, type Box } from "./placement";
import "./tour.css";

type Props = {
  view: string;
  menuOpen: boolean;
  onMenu: (open: boolean) => void;
  onActive: (active: boolean) => void;
};

export default function MemberTour({
  view,
  menuOpen,
  onMenu,
  onActive,
}: Props) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [dontShow, setDontShow] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
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
  const current = steps[step];
  const sidebarStep = !!current.target && !current.target.startsWith("demo-");

  const start = (manual = false) => {
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
    setOpen(false);
    onMenuRef.current(initial.current.menu);
    window.requestAnimationFrame(() => {
      window.scrollTo(0, initial.current.scroll);
      initial.current.focus?.focus();
    });
  };
  const advance = () =>
    step === steps.length - 1 ? close("finish") : setStep(step + 1);

  useEffect(() => {
    if (view !== "home") return;
    if (
      !open &&
      !dismissedSession.current &&
      !invitedThisSession() &&
      shouldInvite(readPreference())
    )
      start();
    // Only visiting Home invites; other renders do not repeat an invitation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);
  useEffect(() => {
    onActive(open);
    return () => onActive(false);
  }, [open, onActive]);
  useEffect(() => {
    if (!open) return;
    const sync = () =>
      onMenuRef.current(
        sidebarStep && window.matchMedia("(max-width: 900px)").matches,
      );
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, [open, sidebarStep, step]);
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
      const target = current.target
        ? document.querySelector<HTMLElement>(
            `[data-tour-target="${current.target}"]`,
          )
        : null;
      if (!target || !target.getClientRects().length) {
        setBox(null);
        return;
      }
      const rect = target.getBoundingClientRect();
      if (window.innerWidth > 900 && card.current)
        setPosition(
          placeCard(rect, card.current.getBoundingClientRect(), {
            width: window.innerWidth,
            height: window.innerHeight,
          }),
        );
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
        .querySelector<HTMLElement>(`[data-tour-target="${current.target}"]`)
        ?.scrollIntoView({ block: "nearest" });
      update();
      card.current?.querySelector<HTMLElement>("h2")?.focus();
    });
    const observer = new ResizeObserver(update);
    observer.observe(document.body);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const timer = window.setTimeout(update, 350); // after the existing drawer transition
    return () => {
      if (nav) nav.style.maxHeight = originalNavHeight;
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      observer.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, step, current.target, menuOpen]);

  return (
    <>
      <button
        type="button"
        className="tour-launcher"
        onClick={() => start(true)}
      >
        <CircleHelp size={20} aria-hidden="true" /> Help &amp; tour
      </button>
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
            <Practice step={step} advance={advance} />
            {box && (
              <button
                type="button"
                className="tour-spotlight"
                style={box}
                onClick={advance}
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
                <p>{current.text}</p>
                {step === 10 && (
                  <div className="tour-mini">
                    <small>PRACTICE · nothing is saved</small>
                    <strong>Demo Barbarian · TH15 · Lazy CWL</strong>
                  </div>
                )}
                {step === 11 && (
                  <div className="tour-mini">
                    <small>PRACTICE · nothing is saved</small>
                    <strong>Demo Barbarian → Demo Warriors</strong>
                    <button type="button" onClick={advance}>
                      Open clan
                    </button>
                  </div>
                )}
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
                <button type="button" className="tour-next" onClick={advance}>
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
              {(step === 0 || step === 12) && (
                <p className="tour-policy">
                  {policyNotice}{" "}
                  <a href={policyUrl} target="_blank" rel="noopener noreferrer">
                    www.supercell.com/fan-content-policy.
                  </a>
                </p>
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
