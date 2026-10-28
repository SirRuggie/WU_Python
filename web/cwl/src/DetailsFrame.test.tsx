// @vitest-environment happy-dom
import { act } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import DetailsFrame from "./DetailsFrame";
import {
  detailsAccount,
  detailsUrl,
  requestDetailsNavigation,
} from "./detailsNavigation";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const close = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/cwl/roster?season=1");
  vi.spyOn(history, "back").mockImplementation(() => {});
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        matches: query.includes("min-width"),
        media: query,
        addEventListener() {},
        removeEventListener() {},
        onchange: null,
        addListener() {},
        removeListener() {},
        dispatchEvent: () => true,
      }) as unknown as MediaQueryList,
  );
  HTMLDialogElement.prototype.show = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  close.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
  host.remove();
  vi.restoreAllMocks();
});
async function render(tag = "#P028YU9Q", dirty = false) {
  await act(async () =>
    root.render(
      <DetailsFrame
        tag={tag}
        name="Amber"
        dirty={dirty}
        busy={false}
        onClose={close}
      >
        <p>Account content</p>
      </DetailsFrame>,
    ),
  );
}
it("encodes account tags, pushes once and replaces on switching players", async () => {
  const push = vi.spyOn(history, "pushState"),
    replace = vi.spyOn(history, "replaceState");
  await render();
  expect(detailsAccount()).toBe("#P028YU9Q");
  expect(location.search).toContain("account=%23P028YU9Q");
  expect(push).toHaveBeenCalledOnce();
  await render("#P028YU9R");
  expect(detailsAccount()).toBe("#P028YU9R");
  expect(push).toHaveBeenCalledOnce();
  expect(replace).toHaveBeenCalled();
  expect(detailsUrl(null)).toBe("/cwl/roster?season=1");
});
it("direct links insert a list baseline and clean Back closes", async () => {
  history.replaceState({}, "", "/cwl/roster?season=1&account=%23P028YU9Q");
  const replace = vi.spyOn(history, "replaceState");
  await render();
  expect(replace.mock.calls[0][2]).toBe("/cwl/roster?season=1");
  await act(async () =>
    window.dispatchEvent(new PopStateEvent("popstate", { state: {} })),
  );
  expect(close).toHaveBeenCalledOnce();
});
it("dirty navigation uses a discard dialog and Cancel keeps the player", async () => {
  await render(undefined, true);
  const change = vi.fn();
  await act(async () => requestDetailsNavigation(change));
  expect(change).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain(
    "Discard the unsaved weight for Amber?",
  );
  const cancel = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === "Cancel",
  )!;
  await act(async () => cancel.click());
  expect(change).not.toHaveBeenCalled();
  await act(async () => requestDetailsNavigation(change));
  const discard = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === "Discard",
  )!;
  await act(async () => discard.click());
  expect(change).toHaveBeenCalledOnce();
});
it("dirty Back restores the panel entry and requires confirmation", async () => {
  await render(undefined, true);
  await act(async () =>
    window.dispatchEvent(new PopStateEvent("popstate", { state: {} })),
  );
  expect(close).not.toHaveBeenCalled();
  expect(detailsAccount()).toBe("#P028YU9Q");
  expect(document.body.textContent).toContain("Discard the unsaved weight");
});

it.each(["‹ Previous", "Next ›", "‹ Build roster"])(
  "dirty %s waits for discard confirmation",
  async (label) => {
    const navigate = vi.fn();
    await act(async () =>
      root.render(
        <DetailsFrame
          tag="#P028YU9Q"
          name="Amber"
          dirty
          busy={false}
          onClose={close}
          previous={navigate}
          next={navigate}
        >
          Account
        </DetailsFrame>,
      ),
    );
    const button = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === label,
    )!;
    await act(async () => button.click());
    expect(navigate).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(
      "Discard the unsaved weight for Amber?",
    );
  },
);
it("phone navigation follows the supplied filtered order and disables its ends", async () => {
  const next = vi.fn();
  await act(async () =>
    root.render(
      <DetailsFrame
        tag="#P028YU9Q"
        name="Amber"
        dirty={false}
        busy={false}
        onClose={close}
        next={next}
      >
        Account
      </DetailsFrame>,
    ),
  );
  const previous = Array.from(document.querySelectorAll("button")).find(
    (b) => b.textContent?.trim() === "‹ Previous",
  )!;
  expect(previous.disabled).toBe(true);
  await act(async () =>
    Array.from(document.querySelectorAll("button"))
      .find((b) => b.textContent?.trim() === "Next ›")!
      .click(),
  );
  expect(next).toHaveBeenCalledOnce();
});

it("contains phone Tab events but does not consume events from a nested portal dialog", async () => {
  vi.mocked(window.matchMedia).mockImplementation(
    (query) =>
      ({
        matches: query.includes("max-width"),
        media: query,
        addEventListener() {},
        removeEventListener() {},
      }) as unknown as MediaQueryList,
  );
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
    {},
  ] as unknown as DOMRectList);
  await act(async () =>
    root.render(
      <DetailsFrame
        tag="#TAG"
        name="Amber"
        dirty={false}
        busy={false}
        onClose={close}
      >
        {createPortal(
          <button id="foreign-portal-control">Nested dialog control</button>,
          document.body,
        )}
      </DetailsFrame>,
    ),
  );
  const panel = document.querySelector<HTMLDialogElement>(".details-frame")!;
  const first = panel.querySelector<HTMLButtonElement>("button")!;
  first.focus();
  const tab = new KeyboardEvent("keydown", {
    key: "Tab",
    bubbles: true,
    cancelable: true,
  });
  await act(async () => first.dispatchEvent(tab));
  expect(tab.defaultPrevented).toBe(true);
  const outside = document.querySelector<HTMLButtonElement>(
    "#foreign-portal-control",
  )!;
  outside.focus();
  const foreignTab = new KeyboardEvent("keydown", {
    key: "Tab",
    bubbles: true,
    cancelable: true,
  });
  await act(async () => outside.dispatchEvent(foreignTab));
  expect(foreignTab.defaultPrevented).toBe(false);
  expect(document.activeElement).toBe(outside);
  expect(close).not.toHaveBeenCalled();
});
