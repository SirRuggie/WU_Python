// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikeSortPanel from "./StrikeSortPanel";
import { parseActivityFilters } from "./strikeActivityFilters";

let host: HTMLDivElement,
  root: ReturnType<typeof createRoot>,
  trigger: HTMLButtonElement;
let reduced = false;
const closed = vi.fn();
function Harness() {
  const [open, setOpen] = useState(true);
  return open ? (
    <StrikeSortPanel
      filters={parseActivityFilters()}
      trigger={trigger}
      onChange={() => {}}
      onClose={() => {
        closed();
        setOpen(false);
      }}
    />
  ) : null;
}
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  reduced = false;
  closed.mockReset();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    window.setTimeout(() => callback(0), 0),
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: reduced })),
  );
  vi.spyOn(history, "back").mockImplementation(() => {});
  history.replaceState({}, "");
  host = document.createElement("div");
  trigger = document.createElement("button");
  trigger.textContent = "Sort";
  trigger.getClientRects = () =>
    [{ width: 44, height: 44 } as DOMRect] as unknown as DOMRectList;
  document.body.append(trigger, host);
  root = createRoot(host);
  await act(async () => root.render(<Harness />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  vi.runOnlyPendingTimers();
  host.remove();
  trigger.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const dismiss = () =>
  act(async () =>
    document.querySelector<HTMLButtonElement>(".action-panel-close")!.click(),
  );

it("finishes one100ms explicit exit, rejects duplicate close and returns focus", async () => {
  await dismiss();
  await dismiss();
  expect(
    document.querySelector(".strike-sort-panel.is-closing"),
  ).not.toBeNull();
  expect(closed).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTime(99));
  expect(closed).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTime(1));
  expect(closed).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTime(0));
  expect(document.activeElement).toBe(trigger);
});

it("Back closes immediately and a rapid second Back reaches normal navigation", async () => {
  const appPop = vi.fn();
  window.addEventListener("popstate", appPop);
  try {
    await act(async () => {
      history.replaceState({}, "");
      window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
      window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
    });
    expect(closed).toHaveBeenCalledTimes(1);
    expect(appPop).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".strike-sort-panel")).toBeNull();
    await act(async () => vi.advanceTimersByTime(200));
    expect(closed).toHaveBeenCalledTimes(1);
  } finally {
    window.removeEventListener("popstate", appPop);
  }
});

it("Back during an explicit exit cancels its timer rather than closing twice", async () => {
  await dismiss();
  await act(async () => {
    vi.advanceTimersByTime(50);
    history.replaceState({}, "");
    window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
  });
  expect(closed).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTime(200));
  expect(closed).toHaveBeenCalledTimes(1);
});

it("parent/route unmount cancels a pending exit callback", async () => {
  await dismiss();
  await act(async () => root.render(null));
  await act(async () => vi.advanceTimersByTime(200));
  expect(closed).not.toHaveBeenCalled();
});

it("reduced motion closes immediately without a timer", async () => {
  reduced = true;
  await dismiss();
  expect(closed).toHaveBeenCalledTimes(1);
  expect(document.querySelector(".strike-sort-panel")).toBeNull();
});
