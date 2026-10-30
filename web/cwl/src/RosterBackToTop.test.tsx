// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import RosterBackToTop from "./RosterBackToTop";

let root: Root;
let host: HTMLDivElement;
let phone: boolean;
let reduced: boolean;
let mediaChange: (() => void) | undefined;
const button = () =>
  document.querySelector<HTMLButtonElement>('[aria-label="Back to top"]');
async function render(blocked = false, selectionBarHeight = 0) {
  await act(async () =>
    root.render(
      <RosterBackToTop
        blocked={blocked}
        selectionBarHeight={selectionBarHeight}
      />,
    ),
  );
}
async function scroll(y: number, settle = true) {
  await act(async () => {
    Object.defineProperty(window, "scrollY", { configurable: true, value: y });
    window.dispatchEvent(new Event("scroll"));
    if (settle) vi.advanceTimersByTime(80);
  });
}
async function show() {
  await scroll(2600);
  await scroll(2500);
  expect(button()).not.toBeNull();
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  phone = true;
  reduced = false;
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: 800,
  });
  Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        get matches() {
          return query.includes("reduced-motion") ? reduced : phone;
        },
        addEventListener: (_: string, callback: () => void) => {
          mediaChange = callback;
        },
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("stays hidden at top and on descent; needs two screens and 40px upward travel", async () => {
  await render();
  expect(button()).toBeNull();
  await scroll(1500);
  await scroll(1400);
  expect(button()).toBeNull();
  await scroll(2600);
  expect(button()).toBeNull();
  await scroll(2570);
  expect(button()).toBeNull();
  await scroll(2550, false);
  expect(button()).toBeNull();
  await act(async () => vi.advanceTimersByTime(80));
  expect(button()).not.toBeNull();
  await scroll(2560);
  expect(button()).not.toBeNull();
  await scroll(2600);
  expect(button()).toBeNull();
});

it("retains visibility below the reveal threshold until within one screen of top", async () => {
  await render();
  await show();
  await scroll(1200);
  expect(button()).not.toBeNull();
  await scroll(800, false);
  expect(button()).toBeNull();
});

it("clears pending reveals when direction changes or the component unmounts", async () => {
  await render();
  await scroll(2600);
  await scroll(2500, false);
  await scroll(2510);
  expect(button()).toBeNull();
  await act(async () => root.render(null));
  await act(async () => vi.runAllTimers());
  expect(button()).toBeNull();
});

it("uses the measured selection bar height plus a gap and reserves last-row space", async () => {
  await render(false, 136);
  await show();
  expect(button()?.style.bottom).toBe(
    "calc(164px + env(safe-area-inset-bottom))",
  );
  expect(document.querySelector(".roster-back-to-top-spacer")).not.toBeNull();
  await render(false, 184);
  expect(button()?.style.bottom).toBe(
    "calc(212px + env(safe-area-inset-bottom))",
  );
  await render(false, 0);
  expect(button()?.style.bottom).toBe(
    "calc(16px + env(safe-area-inset-bottom))",
  );
});

it("hides immediately for Details/panels and cancels any pending reveal", async () => {
  await render();
  await show();
  await render(true);
  expect(button()).toBeNull();
  await scroll(2300);
  expect(button()).toBeNull();
  await render();
  expect(button()).toBeNull();
});

it("hides for a dialog opened outside the workspace", async () => {
  await render();
  await show();
  await act(async () => {
    const dialog = document.createElement("dialog");
    dialog.open = true;
    document.body.append(dialog);
    await new Promise<void>((resolve) => queueMicrotask(resolve));
  });
  expect(button()).toBeNull();
});

it.each([false, true])(
  "scrolls to zero and focuses Build roster with reduced motion %s",
  async (reduce) => {
    reduced = reduce;
    const heading = document.createElement("h1");
    heading.setAttribute("data-roster-heading", "");
    heading.tabIndex = -1;
    document.body.append(heading);
    await render();
    await show();
    const url = location.href;
    await act(async () => button()!.click());
    expect(window.scrollTo).toHaveBeenCalledWith({
      top: 0,
      behavior: reduce ? "instant" : "smooth",
    });
    expect(document.activeElement).toBe(heading);
    expect(location.href).toBe(url);
    expect(button()).toBeNull();
  },
);

it("does not render on desktop and removes itself on resizing to desktop", async () => {
  phone = false;
  await render();
  await scroll(2600);
  await scroll(2500);
  expect(host.childElementCount).toBe(0);
  phone = true;
  await act(async () => mediaChange?.());
  await show();
  phone = false;
  await act(async () => mediaChange?.());
  expect(host.childElementCount).toBe(0);
});
