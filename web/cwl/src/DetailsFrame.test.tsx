// @vitest-environment happy-dom
import { act } from "react";
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
      }) as MediaQueryList,
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
