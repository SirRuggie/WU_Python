import { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";
import "./RosterBackToTop.css";

type Props = {
  blocked: boolean;
  selectionBarHeight: number;
};

/** Mounted only for Accounts & signups; all state is transient and read-only. */
export default function RosterBackToTop({
  blocked,
  selectionBarHeight,
}: Props) {
  const [phone, setPhone] = useState(false);
  const [visible, setVisible] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 800px)");
    const update = () => setPhone(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!phone) return;
    const update = () =>
      setDialogOpen(
        !!document.querySelector('dialog[open], [aria-modal="true"]'),
      );
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["open", "aria-modal"],
    });
    return () => observer.disconnect();
  }, [phone]);

  useEffect(() => {
    setVisible(false);
    if (!phone || blocked || dialogOpen) return;
    let anchor = window.scrollY;
    let previous = anchor;
    let direction = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const scroll = () => {
      const y = Math.max(0, window.scrollY);
      const nextDirection = Math.sign(y - previous);
      if (nextDirection && nextDirection !== direction) {
        anchor = previous;
        direction = nextDirection;
      }
      previous = y;
      clearTimeout(timer);
      if (y <= window.innerHeight) {
        setVisible(false);
        return;
      }
      if (Math.abs(y - anchor) < 40) return;
      timer = setTimeout(() => {
        if (direction > 0) setVisible(false);
        else if (y > 2 * window.innerHeight) setVisible(true);
      }, 80);
    };
    const resize = () => {
      clearTimeout(timer);
      setVisible(false);
      anchor = previous = window.scrollY;
      direction = 0;
    };
    window.addEventListener("scroll", scroll, { passive: true });
    window.addEventListener("resize", resize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("scroll", scroll);
      window.removeEventListener("resize", resize);
    };
  }, [phone, blocked, dialogOpen]);

  if (!phone) return null;
  return (
    <>
      <div className="roster-back-to-top-spacer" aria-hidden="true" />
      {visible && !blocked && !dialogOpen && (
        <button
          type="button"
          className="roster-back-to-top"
          aria-label="Back to top"
          style={{
            bottom: `calc(${selectionBarHeight > 0 ? selectionBarHeight + 28 : 16}px + env(safe-area-inset-bottom))`,
          }}
          onClick={() => {
            document
              .querySelector<HTMLElement>("[data-roster-heading]")
              ?.focus({ preventScroll: true });
            window.scrollTo({
              top: 0,
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "instant"
                : "smooth",
            });
            setVisible(false);
          }}
        >
          <ArrowUp size={18} aria-hidden="true" />
          Back to top
        </button>
      )}
    </>
  );
}
