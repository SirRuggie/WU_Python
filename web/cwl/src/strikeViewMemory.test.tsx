// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { useViewScroll } from "./strikeViewMemory";

it("does not replace the saved origin scroll with the destination scroll during unmount", async () => {
  const memory = new Map<string, unknown>([["scroll", 0]]);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  function View() {
    useViewScroll(memory, true);
    return null;
  }
  try {
    await act(async () => root.render(<View />));
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      value: 900,
    });
    window.dispatchEvent(new Event("scroll"));
    expect(memory.get("scroll")).toBe(900);
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
    await act(async () => root.unmount());
    expect(memory.get("scroll")).toBe(900);
  } finally {
    host.remove();
    vi.unstubAllGlobals();
  }
});
