// @vitest-environment happy-dom
import { createElement } from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { horizontalFadeState, useHorizontalFades } from "./useHorizontalFades";

it("shows only edges with hidden content", () => {
  expect(
    horizontalFadeState({ scrollLeft: 0, clientWidth: 360, scrollWidth: 360 }),
  ).toEqual({ left: false, right: false });
  expect(
    horizontalFadeState({ scrollLeft: 0, clientWidth: 360, scrollWidth: 600 }),
  ).toEqual({ left: false, right: true });
  expect(
    horizontalFadeState({
      scrollLeft: 120,
      clientWidth: 360,
      scrollWidth: 600,
    }),
  ).toEqual({ left: true, right: true });
  expect(
    horizontalFadeState({
      scrollLeft: 240,
      clientWidth: 360,
      scrollWidth: 600,
    }),
  ).toEqual({ left: true, right: false });
});

it("subscribes once per mounted scroller, including a conditional remount", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const original = globalThis.ResizeObserver;
  const observe = vi.fn();
  const disconnect = vi.fn();
  globalThis.ResizeObserver = class {
    observe = observe;
    disconnect = disconnect;
    unobserve = vi.fn();
  } as unknown as typeof ResizeObserver;
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  function Harness({ show, tick }: { show: boolean; tick: number }) {
    const fades = useHorizontalFades<HTMLDivElement>();
    return show
      ? createElement(
          "div",
          { ref: fades.ref, "data-fade-right": fades.right },
          createElement("span", null, "chips"),
          tick >= 5 ? createElement("span", null, "Auto-place") : null,
        )
      : null;
  }
  try {
    await act(async () =>
      root.render(createElement(Harness, { show: false, tick: 0 })),
    );
    expect(observe).not.toHaveBeenCalled();
    await act(async () =>
      root.render(createElement(Harness, { show: true, tick: 1 })),
    );
    expect(observe).toHaveBeenCalledTimes(2);
    await act(async () =>
      root.render(createElement(Harness, { show: true, tick: 2 })),
    );
    expect(observe).toHaveBeenCalledTimes(2);
    await act(async () =>
      root.render(createElement(Harness, { show: false, tick: 3 })),
    );
    expect(disconnect).toHaveBeenCalledTimes(1);
    await act(async () =>
      root.render(createElement(Harness, { show: true, tick: 4 })),
    );
    expect(observe).toHaveBeenCalledTimes(4);
    const scroller = host.firstElementChild!;
    Object.defineProperty(scroller, "clientWidth", {
      configurable: true,
      value: 360,
    });
    Object.defineProperty(scroller, "scrollWidth", {
      configurable: true,
      value: 600,
    });
    await act(async () =>
      root.render(createElement(Harness, { show: true, tick: 5 })),
    );
    expect(scroller.getAttribute("data-fade-right")).toBe("true");
    expect(observe).toHaveBeenCalledTimes(5);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    globalThis.ResizeObserver = original;
  }
});
