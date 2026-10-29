// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMobileNavigation } from "./useMobileNavigation";

let root: Root, host: HTMLDivElement;
const close = vi.fn();

function Fixture() {
  const { drawerRef } = useMobileNavigation(true, close, true);
  return (
    <>
      <aside ref={drawerRef}>
        <button>Drawer control</button>
      </aside>
      <div className="account-menu-popover" tabIndex={-1}>
        <button>Account action</button>
      </div>
    </>
  );
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
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
  close.mockClear();
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
