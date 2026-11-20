// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import useSwipeNavigation, {
  SWIPE_DISTANCE,
  SWIPE_EDGE_GUARD,
  SWIPE_AXIS_RATIO,
} from "./useSwipeNavigation";
import { swipeEvent, touchEvent } from "./swipeTestEvents";

let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const change = vi.fn(),
  click = vi.fn();
function Sample({ enabled = true }: { enabled?: boolean }) {
  const swipe = useSwipeNavigation({ onSwipe: change, enabled });
  return (
    <>
      {[1, 2].map((id) => (
        <div key={id} className="area" {...swipe}>
          <button onClick={click}>Open{id}</button>
        </div>
      ))}
    </>
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal("innerWidth", 360);
  vi.stubGlobal("visualViewport", { scale: 1 });
  change.mockReset();
  click.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function mount(enabled = true) {
  await act(async () => root.render(<Sample enabled={enabled} />));
  return host.querySelector<HTMLElement>(".area")!;
}
it("exports the specified distance, axis and edge thresholds", () => {
  expect([SWIPE_DISTANCE, SWIPE_AXIS_RATIO, SWIPE_EDGE_GUARD]).toEqual([
    70, 1.5, 24,
  ]);
});
it.each([
  [250, 100, "next"],
  [100, 250, "previous"],
] as const)(
  "moves only after finger lift (%s to %s)",
  async (from, to, direction) => {
    const area = await mount();
    expect(
      touchEvent(area, "touchstart", [{ clientX: from, clientY: 0 }])
        .defaultPrevented,
    ).toBe(false);
    expect(change).not.toHaveBeenCalled();
    expect(
      touchEvent(area, "touchend", [{ clientX: to, clientY: 0 }])
        .defaultPrevented,
    ).toBe(false);
    expect(change).toHaveBeenCalledExactlyOnceWith(direction);
  },
);
it.each([
  [250, 180, 0, false],
  [250, 179, 0, true],
  [250, 100, 100, false],
  [250, 100, 101, false],
  [23, 200, 0, false],
  [24, 200, 0, true],
  [337, 100, 0, false],
  [336, 100, 0, true],
])(
  "guards threshold/axis/edge from%s to%s dy%s",
  async (from, to, dy, counts) => {
    const area = await mount();
    swipeEvent(area, from, to, dy);
    expect(change).toHaveBeenCalledTimes(counts ? 1 : 0);
  },
);
it.each([false, true])(
  "rejects multiple fingers, including a later finger outside the area (%s)",
  async (outside) => {
    const area = await mount();
    touchEvent(area, "touchstart", [{ clientX: 250, clientY: 0 }]);
    touchEvent(outside ? document.body : area, "touchstart", [
      { clientX: 250, clientY: 0 },
      { clientX: 100, clientY: 0 },
    ]);
    touchEvent(area, "touchend", [{ clientX: 100, clientY: 0 }]);
    expect(change).not.toHaveBeenCalled();
  },
);
it("rejects a multi-finger initial touch and a partial touchend", async () => {
  const area = await mount();
  touchEvent(area, "touchstart", [
    { clientX: 250, clientY: 0 },
    { clientX: 150, clientY: 0 },
  ]);
  touchEvent(area, "touchend", [{ clientX: 100, clientY: 0 }]);
  touchEvent(area, "touchstart", [{ clientX: 250, clientY: 0 }]);
  touchEvent(
    area,
    "touchend",
    [{ clientX: 100, clientY: 0 }],
    [{ clientX: 150, clientY: 0 }],
  );
  expect(change).not.toHaveBeenCalled();
});
it.each(["start", "end"])("rejects zoom at %s", async (when) => {
  const area = await mount();
  if (when === "start") vi.stubGlobal("visualViewport", { scale: 1.5 });
  touchEvent(area, "touchstart", [{ clientX: 250, clientY: 0 }]);
  vi.stubGlobal("visualViewport", { scale: 1.5 });
  touchEvent(area, "touchend", [{ clientX: 100, clientY: 0 }]);
  expect(change).not.toHaveBeenCalled();
});
it("accepts a missing visualViewport but rejects selected text", async () => {
  const area = await mount();
  vi.stubGlobal("visualViewport", undefined);
  swipeEvent(area);
  expect(change).toHaveBeenCalledTimes(1);
  vi.spyOn(window, "getSelection").mockReturnValue({
    toString: () => "selected",
  } as Selection);
  swipeEvent(area);
  expect(change).toHaveBeenCalledTimes(1);
});
it("touchcancel and disabling mid-gesture cancel navigation", async () => {
  const area = await mount();
  touchEvent(area, "touchstart", [{ clientX: 250, clientY: 0 }]);
  touchEvent(area, "touchcancel", []);
  touchEvent(area, "touchend", [{ clientX: 100, clientY: 0 }]);
  touchEvent(area, "touchstart", [{ clientX: 250, clientY: 0 }]);
  await mount(false);
  await mount(true);
  touchEvent(area, "touchend", [{ clientX: 100, clientY: 0 }]);
  expect(change).not.toHaveBeenCalled();
});
it("blocks one click across bound areas after a swipe, resets on the next touch, and passes ordinary clicks", async () => {
  const area = await mount();
  swipeEvent(area);
  const other = host.querySelectorAll("button")[1];
  await act(async () => other.click());
  expect(click).not.toHaveBeenCalled();
  await act(async () => other.click());
  expect(click).toHaveBeenCalledTimes(1);
  swipeEvent(area);
  touchEvent(area, "touchstart", [{ clientX: 200, clientY: 0 }]);
  touchEvent(area, "touchend", [{ clientX: 199, clientY: 0 }]);
  await act(async () => other.click());
  expect(click).toHaveBeenCalledTimes(2);
});
it("installs passive touch listeners and removes each node's listeners on unmount", async () => {
  const listen = vi.spyOn(HTMLElement.prototype, "addEventListener");
  const area = await mount();
  for (const type of ["touchstart", "touchend", "touchcancel"])
    expect(
      listen.mock.calls.some(
        (args) =>
          args[0] === type && (args[2] as AddEventListenerOptions)?.passive,
      ),
    ).toBe(true);
  await act(async () => root.render(null));
  swipeEvent(area);
  expect(change).not.toHaveBeenCalled();
});
