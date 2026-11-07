// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMobileNavigation } from "./useMobileNavigation";

let root: Root, host: HTMLDivElement;
const close = vi.fn();

let frames: Map<number, FrameRequestCallback>;
let nextFrameId: number;

function frame() {
  const callbacks = [...frames.values()];
  frames.clear();
  act(() => callbacks.forEach((callback) => callback(0)));
}

function Fixture({ open = true }: { open?: boolean }) {
  const { drawerRef, triggerRef } = useMobileNavigation(open, close, true);
  return (
    <>
      <button ref={triggerRef}>Menu</button>
      <aside ref={drawerRef} tabIndex={-1} style={{ visibility: "visible" }}>
        <button className="fixture-close" onClick={close}>
          Close menu
        </button>
        <a
          className="fixture-link"
          href="/tasks"
          onClick={(event) => {
            event.preventDefault();
            close();
          }}
        >
          Tasks
        </a>
      </aside>
      <button className="fixture-scrim" onClick={close}>
        Scrim
      </button>
      <div className="account-menu-popover" tabIndex={-1}>
        <button>Account action</button>
      </div>
    </>
  );
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  frames = new Map();
  nextFrameId = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const id = ++nextFrameId;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  window.matchMedia = vi.fn().mockReturnValue({
    matches: true,
    addEventListener() {},
    removeEventListener() {},
  });
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
    {},
  ] as unknown as DOMRectList);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root.render(<Fixture />));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  close.mockReset();
});

it("lets the portalled account menu own Escape and Tab", () => {
  const action = host.querySelector<HTMLButtonElement>(
    ".account-menu-popover button",
  )!;
  action.focus();
  for (const key of ["Escape", "Tab"]) {
    const event = new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
    act(() => action.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
  }
  expect(close).not.toHaveBeenCalled();
});

it("continues to trap Tab and close the drawer on Escape from drawer controls", () => {
  const control = host.querySelector<HTMLButtonElement>("aside button")!;
  const tab = new KeyboardEvent("keydown", {
    key: "Tab",
    bubbles: true,
    cancelable: true,
  });
  act(() => control.dispatchEvent(tab));
  expect(tab.defaultPrevented).toBe(true);

  const escape = new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
  });
  act(() => control.dispatchEvent(escape));
  expect(escape.defaultPrevented).toBe(true);
  expect(close).toHaveBeenCalledTimes(1);
});

it("waits for drawer visibility before entering focus", () => {
  const drawer = host.querySelector<HTMLElement>("aside")!;
  const menu = host.querySelector<HTMLButtonElement>("button")!;
  drawer.style.visibility = "hidden";
  menu.focus();
  frame();
  expect(document.activeElement).toBe(menu);
  expect(frames.size).toBe(1);
  drawer.style.visibility = "visible";
  frame();
  expect(document.activeElement).toBe(drawer.querySelector("button"));
  expect(frames.size).toBe(0);
});

it("bounds a permanently hidden drawer wait and tries the drawer fallback", () => {
  const drawer = host.querySelector<HTMLElement>("aside")!;
  drawer.style.visibility = "hidden";
  const fallback = vi.spyOn(drawer, "focus");
  for (let index = 0; index < 9; index++) frame();
  expect(fallback).not.toHaveBeenCalled();
  frame();
  expect(fallback).toHaveBeenCalledTimes(1);
  expect(frames.size).toBe(0);
});

it("cancels delayed focus when the drawer closes before becoming visible", () => {
  const drawer = host.querySelector<HTMLElement>("aside")!;
  drawer.style.visibility = "hidden";
  frame();
  act(() => root.render(<Fixture open={false} />));
  expect(frames.size).toBe(0);
  frame();
  expect(document.activeElement).toBe(host.querySelector("button"));
});

it.each(["close button", "Escape", "scrim", "navigation link"])(
  "restores Menu focus after %s closes the drawer",
  (method) => {
    close.mockImplementation(() => root.render(<Fixture open={false} />));
    frame();
    expect(host.querySelector("aside")!.contains(document.activeElement)).toBe(
      true,
    );
    act(() => {
      if (method === "Escape") {
        document.activeElement!.dispatchEvent(
          new KeyboardEvent("keydown", {
            key: "Escape",
            bubbles: true,
            cancelable: true,
          }),
        );
      } else {
        const selector =
          method === "close button"
            ? ".fixture-close"
            : method === "scrim"
              ? ".fixture-scrim"
              : ".fixture-link";
        host.querySelector<HTMLElement>(selector)!.click();
      }
    });
    expect(close).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(host.querySelector("button"));
    expect(frames.size).toBe(0);
  },
);

it("leaves an open native dialog in charge of Escape and Tab", () => {
  const dialog = document.createElement("dialog");
  dialog.setAttribute("open", "");
  const action = document.createElement("button");
  dialog.append(action);
  host.append(dialog);
  action.focus();
  for (const key of ["Escape", "Tab"]) {
    const event = new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
    act(() => action.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
  }
  expect(close).not.toHaveBeenCalled();
});

it.each(["native dialog", "AccountMenu popover"])(
  "does not steal focus acquired by a %s before the pending frame",
  (overlay) => {
    let action: HTMLButtonElement;
    if (overlay === "native dialog") {
      const dialog = document.createElement("dialog");
      dialog.setAttribute("open", "");
      action = document.createElement("button");
      dialog.append(action);
      host.append(dialog);
    } else {
      action = host.querySelector<HTMLButtonElement>(
        ".account-menu-popover button",
      )!;
    }
    action.focus();
    expect(frames.size).toBe(1);
    frame();
    expect(document.activeElement).toBe(action);
    expect(frames.size).toBe(0);
  },
);
