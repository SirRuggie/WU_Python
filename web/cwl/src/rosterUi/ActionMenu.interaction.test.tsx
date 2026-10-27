// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ActionMenu from "./ActionMenu";
import { closeRosterActionMenus } from "./actionMenuState";
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.matchMedia = vi
    .fn()
    .mockReturnValue({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() =>
    root.render(
      <>
        <div id="outside">Non-focusable outside</div>
        <ActionMenu
          name="One"
          items={[
            { id: "details", label: "Details", onAction: action },
            {
              id: "dm",
              label: "DM ↗",
              href: "https://discord.com/users/123456789012345678",
            },
          ]}
        />
        <ActionMenu
          name="Two"
          items={[{ id: "details", label: "Details", onAction: action }]}
        />
      </>,
    ),
  );
});
const action = vi.fn();
afterEach(() => {
  act(() => {
    root.unmount();
    closeRosterActionMenus();
  });
  host.remove();
  vi.clearAllMocks();
});
async function click(el: Element) {
  await act(async () => {
    el.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    el.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0 }));
    (el as HTMLElement).click();
  });
}
const trigger = (name: string) =>
  document.querySelector(`[aria-label="Actions for ${name}"]`)!;
it("outside click closes even on a non-focusable container", async () => {
  await click(trigger("One"));
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  await click(document.getElementById("outside")!);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});
it("opening a second menu leaves only the second open", async () => {
  await click(trigger("One"));
  await click(trigger("Two"));
  expect(document.querySelectorAll('[role="menu"]').length).toBe(1);
  expect(
    document.querySelector('[role="menu"]')?.getAttribute("aria-label"),
  ).toBe("Actions for Two");
});
it("Escape closes and returns focus to the trigger", async () => {
  const button = trigger("One");
  await click(button);
  await act(async () => {
    document
      .querySelector('[role="menu"]')!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    await new Promise((r) => setTimeout(r, 30));
  });
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(button);
});
it("choosing an item closes and runs its action once", async () => {
  await click(trigger("One"));
  await click(document.querySelector('[role="menuitem"]')!);
  expect(action).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});
it("preserves secure Discord link attributes", async () => {
  await click(trigger("One"));
  const link = document.querySelector('a[role="menuitem"]')!;
  expect(link.getAttribute("href")).toBe(
    "https://discord.com/users/123456789012345678",
  );
  expect(link.getAttribute("target")).toBe("_blank");
  expect(link.getAttribute("rel")).toBe("noopener noreferrer");
});
