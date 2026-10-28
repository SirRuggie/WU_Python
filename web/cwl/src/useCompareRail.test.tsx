// @vitest-environment happy-dom
import { act, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import useCompareRail from "./useCompareRail";

it.each([false, true])(
  "settles once, syncs arrows without feedback, reduced motion=%s",
  async (reduced) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.useFakeTimers();
    window.matchMedia = vi.fn().mockReturnValue({ matches: reduced });
    const change = vi.fn();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    function Harness() {
      const rail = useRef<HTMLDivElement>(null),
        [selected, select] = useState("A");
      useCompareRail(rail, ["A", "B", "C"], selected, (tag) => {
        change(tag);
        select(tag);
      });
      return (
        <>
          <button onClick={() => select("C")}>Arrow</button>
          <div ref={rail} className="rail">
            {["A", "B", "C"].map((tag) => (
              <div key={tag}>{tag}</div>
            ))}
          </div>
          <p>{selected} players</p>
        </>
      );
    }
    try {
      await act(async () => root.render(<Harness />));
      const rail = host.querySelector<HTMLDivElement>(".rail")!;
      rail.getBoundingClientRect = () => ({ left: 0, width: 300 }) as DOMRect;
      [...rail.children].forEach((card, index) => {
        card.getBoundingClientRect = () =>
          ({ left: index * 300 - rail.scrollLeft, width: 300 }) as DOMRect;
      });
      let priorScrollCanSettle = true;
      rail.scrollTo = vi.fn((options) => {
        // A prior scroll may settle while the requested destination is still in flight.
        if (priorScrollCanSettle) {
          priorScrollCanSettle = false;
          rail.dispatchEvent(new Event("scroll"));
          rail.dispatchEvent(new Event("scrollend"));
        }
        rail.scrollLeft = (options as ScrollToOptions).left!;
        rail.dispatchEvent(new Event("scroll"));
        rail.dispatchEvent(new Event("scrollend"));
      });
      await act(async () => {
        rail.scrollLeft = 300;
        rail.dispatchEvent(new Event("scroll"));
        vi.advanceTimersByTime(100);
      });
      expect(host.textContent).toContain("A players");
      await act(async () => vi.advanceTimersByTime(21));
      expect(host.textContent).toContain("B players");
      expect(change).toHaveBeenCalledExactlyOnceWith("B");
      await act(async () => host.querySelector("button")!.click());
      expect(change).toHaveBeenCalledTimes(1);
      expect(rail.scrollTo).toHaveBeenCalledWith({
        left: 600,
        behavior: reduced ? "auto" : "smooth",
      });
      await act(async () => {
        rail.dispatchEvent(new Event("scrollend"));
        vi.advanceTimersByTime(121);
      });
      expect(host.textContent).toContain("C players");
      expect(change).toHaveBeenCalledTimes(1);
      // Multiple intermediate events are never committed mid-swipe.
      await act(async () => {
        rail.dispatchEvent(new Event("pointerdown"));
        rail.scrollLeft = 300;
        rail.dispatchEvent(new Event("scroll"));
        vi.advanceTimersByTime(80);
        rail.scrollLeft = 0;
        rail.dispatchEvent(new Event("scroll"));
        vi.advanceTimersByTime(80);
      });
      expect(host.textContent).toContain("C players");
      await act(async () => vi.advanceTimersByTime(41));
      expect(host.textContent).toContain("A players");
      expect(change).toHaveBeenCalledTimes(2);
    } finally {
      act(() => root.unmount());
      host.remove();
      vi.useRealTimers();
      vi.restoreAllMocks();
    }
  },
);
