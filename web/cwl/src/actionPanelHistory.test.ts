import { describe, expect, it, vi } from "vitest";
import {
  actionPanelAnchor,
  backOutOfPanelEntry,
  installPanelBackHandler,
  isTopActionPanel,
  panelHistoryState,
  registerActionPanel,
} from "./actionPanelHistory";

describe("action panel history", () => {
  it("places a panel above a low trigger and clamps its height to available space", () => {
    const anchor = actionPanelAnchor(
      { top: 720, right: 280, bottom: 760 },
      { width: 320, height: 800 },
    );
    expect(anchor["--action-panel-top"]).toBe("auto");
    expect(anchor["--action-panel-bottom"]).toBe("88px");
    expect(
      Number.parseFloat(anchor["--action-panel-max-height"]),
    ).toBeLessThanOrEqual(708);
    expect(anchor["--action-panel-right"]).toBe("40px");
  });

  it("clamps panel width and right offset when the trigger extends beyond the viewport", () => {
    const anchor = actionPanelAnchor(
      { top: 40, right: 600, bottom: 80 },
      { width: 320, height: 640 },
    );
    expect(anchor["--action-panel-right"]).toBe("12px");
    expect(
      Number.parseFloat(anchor["--action-panel-width"]),
    ).toBeLessThanOrEqual(296);
  });

  it("copies the dashboard history state and its index into the panel entry", () => {
    expect(
      panelHistoryState({ wuDashboardIndex: 9, route: "roster" }, "panel-1"),
    ).toEqual({
      wuDashboardIndex: 9,
      route: "roster",
      wuActionPanel: "panel-1",
    });
  });

  it("closes on Back before the dashboard popstate handler can prompt about selection state", () => {
    const windowPort = new EventTarget() as Window;
    Object.defineProperty(windowPort, "location", {
      value: { href: "/manage-roster" },
    });
    const historyPort = {
      state: { wuDashboardIndex: 9, wuActionPanel: "panel-1" },
      pushState: vi.fn(),
    };
    const close = vi.fn();
    const appPop = vi.fn();
    const remove = installPanelBackHandler({
      windowPort,
      historyPort: historyPort as never,
      marker: "panel-1",
      panelState: { wuDashboardIndex: 9, wuActionPanel: "panel-1" },
      isBusy: () => false,
      close,
    });
    windowPort.addEventListener("popstate", appPop);
    const event = new Event("popstate") as PopStateEvent;
    Object.defineProperty(event, "state", { value: { wuDashboardIndex: 9 } });
    windowPort.dispatchEvent(event);
    expect(close).toHaveBeenCalledOnce();
    expect(appPop).not.toHaveBeenCalled();
    remove();
  });

  it("lets only the top nested panel handle Back or keyboard ownership", () => {
    const windowPort = new EventTarget() as Window;
    Object.defineProperty(windowPort, "location", {
      value: { href: "/roster" },
    });
    const historyPort = {
      state: { wuDashboardIndex: 9, wuActionPanel: "outer" },
      pushState: vi.fn(),
    };
    const outerClose = vi.fn();
    const innerClose = vi.fn();
    const removeOuterFromStack = registerActionPanel("outer");
    const removeOuterHandler = installPanelBackHandler({
      windowPort,
      historyPort: historyPort as never,
      marker: "outer",
      panelState: {},
      isBusy: () => false,
      isTop: () => isTopActionPanel("outer"),
      close: outerClose,
    });
    const removeInnerFromStack = registerActionPanel("inner");
    const removeInnerHandler = installPanelBackHandler({
      windowPort,
      historyPort: historyPort as never,
      marker: "inner",
      panelState: {},
      isBusy: () => false,
      isTop: () => isTopActionPanel("inner"),
      close: innerClose,
    });
    expect(isTopActionPanel("outer")).toBe(false);
    expect(isTopActionPanel("inner")).toBe(true);
    const event = new Event("popstate") as PopStateEvent;
    Object.defineProperty(event, "state", {
      value: { wuDashboardIndex: 9, wuActionPanel: "outer" },
    });
    windowPort.dispatchEvent(event);
    expect(innerClose).toHaveBeenCalledOnce();
    expect(outerClose).not.toHaveBeenCalled();
    removeInnerHandler();
    removeInnerFromStack();
    removeOuterHandler();
    removeOuterFromStack();
  });

  it("installs explicit-close suppression on the capture phase", () => {
    const listeners: {
      listener: EventListenerOrEventListenerObject;
      capture: boolean;
    }[] = [];
    const windowPort = {
      addEventListener: (
        _type: string,
        listener: EventListenerOrEventListenerObject,
        options?: boolean | AddEventListenerOptions,
      ) => {
        listeners.push({
          listener,
          capture:
            options === true ||
            !!(options && typeof options === "object" && options.capture),
        });
      },
      removeEventListener: vi.fn(),
      setTimeout: globalThis.setTimeout.bind(globalThis),
      clearTimeout: globalThis.clearTimeout.bind(globalThis),
    } as unknown as Window;
    const historyPort = {
      state: { wuDashboardIndex: 9, wuActionPanel: "panel-1" },
      back: vi.fn(),
    };
    backOutOfPanelEntry({
      windowPort,
      historyPort: historyPort as never,
      marker: "panel-1",
    });
    expect(listeners).toHaveLength(1);
    expect(listeners[0].capture).toBe(true);
    expect(historyPort.back).toHaveBeenCalledOnce();
  });

  it("keeps the same dashboard index and panel open when Back arrives during work", () => {
    const windowPort = new EventTarget() as Window;
    Object.defineProperty(windowPort, "location", {
      value: { href: "/manage-roster" },
    });
    const panelState = { wuDashboardIndex: 9, wuActionPanel: "panel-1" };
    const historyPort = { state: panelState, pushState: vi.fn() };
    const close = vi.fn();
    const remove = installPanelBackHandler({
      windowPort,
      historyPort: historyPort as never,
      marker: "panel-1",
      panelState,
      isBusy: () => true,
      close,
    });
    const event = new Event("popstate") as PopStateEvent;
    Object.defineProperty(event, "state", { value: { wuDashboardIndex: 9 } });
    windowPort.dispatchEvent(event);
    expect(historyPort.pushState).toHaveBeenCalledWith(
      panelState,
      "",
      "/manage-roster",
    );
    expect(close).not.toHaveBeenCalled();
    remove();
  });
});
