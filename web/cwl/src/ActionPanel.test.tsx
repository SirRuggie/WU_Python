// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import ActionPanel from "./ActionPanel";

let host: HTMLDivElement, root: Root;
const onClose = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) =>
    setTimeout(() => fn(0), 0),
  );
  onClose.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function mount() {
  await act(async () =>
    root.render(
      <ActionPanel
        title="Pick"
        onClose={onClose}
        trigger={null}
        expandOnSearchFocus
      >
        <input type="search" aria-label="Find" />
        <button type="button">Option</button>
      </ActionPanel>,
    ),
  );
  return document.querySelector("dialog")!;
}
const press = (target: Element, type: string) =>
  act(async () => {
    target.dispatchEvent(new Event(type, { bubbles: true }));
  });

it("stays expanded after the search box loses focus", async () => {
  const dialog = await mount();
  const input = dialog.querySelector("input")!;
  await act(async () => {
    input.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    input.focus();
  });
  expect(dialog.classList.contains("is-search-focused")).toBe(true);
  await act(async () => {
    dialog
      .querySelector("button.action-panel-close")!
      .dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    input.blur();
  });
  expect(dialog.classList.contains("is-search-focused")).toBe(true);
});

it("does not close when the press began inside the panel", async () => {
  const dialog = await mount();
  await press(
    dialog.querySelector("button:not(.action-panel-close)")!,
    "pointerdown",
  );
  await act(async () => dialog.click());
  expect(onClose).not.toHaveBeenCalled();
});

it("closes when the press and the click are both on the backdrop", async () => {
  const dialog = await mount();
  await press(dialog, "pointerdown");
  await act(async () => dialog.click());
  expect(onClose).toHaveBeenCalledTimes(1);
});
