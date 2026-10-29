// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import MemberTour from "./MemberTour";
import SidebarNavigation from "../SidebarNavigation";
import {
  TOUR_KEY,
  readPreference,
  savePreference,
  shouldInvite,
  steps,
} from "./model";

let root: Root, host: HTMLDivElement;
const menu = vi.fn(),
  active = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("Tour must not fetch")),
  );
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.removeAttribute("open");
  });
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
    {},
  ] as unknown as DOMRectList);
  vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(
    () => {},
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
  } as MediaQueryList);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  menu.mockClear();
  active.mockClear();
});
async function render(view = "home") {
  await act(async () => {
    root.render(
      <>
        <nav>
          {["home", "todo", "register", "saved", "assignments"].map((id) => (
            <button key={id} data-tour-target={id}>
              {id}
            </button>
          ))}
        </nav>
        <MemberTour
          view={view}
          menuOpen={false}
          onMenu={menu}
          onActive={active}
        />
      </>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 25));
  });
}
async function click(selector: string) {
  await act(async () => {
    (document.querySelector(selector) as HTMLElement).click();
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 25));
  });
}
it("walks every step, target advances, phone menu closes for practice, finishes without any request", async () => {
  await render();
  for (let i = 0; i < steps.length; i++) {
    expect(document.querySelector("#tour-title")?.textContent).toBe(
      steps[i].title,
    );
    expect(
      document.querySelector(".tour-character")?.getAttribute("loading"),
    ).toBe("lazy");
    if (steps[i].target)
      expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    if (i === 1) expect(menu).toHaveBeenLastCalledWith(true);
    if (i === 4) {
      expect(menu).toHaveBeenLastCalledWith(false);
      expect(
        document.querySelector(".tour-real-submit")?.hasAttribute("disabled"),
      ).toBe(true);
      expect(document.querySelector(".tour-practice-badge")?.textContent).toBe(
        "PRACTICE · nothing is saved",
      );
    }
    if (i === 8)
      expect(document.querySelector(".tour-confetti")).not.toBeNull();
    if (i === 9) expect(document.querySelector(".tour-practice")).toBeNull();
    if (i === 12)
      expect(document.querySelector(".tour-policy")?.textContent).toContain(
        "This material is unofficial",
      );
    await click(steps[i].target ? ".tour-spotlight" : ".tour-next");
  }
  expect(document.querySelector("dialog")).toBeNull();
  expect(readPreference().dismissed).toBe(true);
  expect(fetch).not.toHaveBeenCalled();
  await click(".tour-launcher");
  expect(document.querySelector("#tour-title")?.textContent).toBe(
    steps[0].title,
  );
});
it("skips only three visits, not three renders, and does not invite away from Home", async () => {
  await render("todo");
  expect(document.querySelector("dialog")).toBeNull();
  for (let i = 1; i <= 3; i++) {
    await render();
    await click(".tour-skip");
    await render();
    expect(document.querySelector("dialog")).toBeNull();
    expect(readPreference().skips).toBe(i);
    await render("todo");
  }
  await render();
  expect(document.querySelector("dialog")).toBeNull();
});
it("checkbox persists dismissal and Escape prevents another invite this session", async () => {
  await render();
  await click(".tour-remember input");
  expect(readPreference().dismissed).toBe(true);
  await act(async () =>
    document
      .querySelector("dialog")!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
  );
  await render("todo");
  await render();
  expect(document.querySelector("dialog")).toBeNull();
  await click(".tour-launcher");
  expect(document.querySelector("dialog")).not.toBeNull();
});
it("X exits without persistent dismissal but does not auto-reopen in the same session", async () => {
  await render();
  await click(".tour-close");
  await render("todo");
  await render();
  expect(document.querySelector("dialog")).toBeNull();
  expect(readPreference().dismissed).toBe(false);
});
it("focus enters the card and wraps in both directions; dim clicks do nothing", async () => {
  await render();
  expect(document.activeElement?.id).toBe("tour-title");
  const dialog = document.querySelector("dialog")!;
  await act(async () =>
    dialog.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
      }),
    ),
  );
  expect(document.activeElement?.tagName).toBe("A");
  await act(async () =>
    dialog.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true }),
    ),
  );
  expect(document.activeElement?.getAttribute("aria-label")).toBe("Close tour");
  await click(".tour-dim");
  expect(document.querySelector("#tour-title")?.textContent).toBe(
    steps[0].title,
  );
});
it("corrupt or unavailable browser storage fails safely", () => {
  localStorage.setItem(TOUR_KEY, '{"skips":-1}');
  expect(readPreference()).toEqual({ skips: 0, dismissed: false });
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("private");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("private");
  });
  expect(shouldInvite(readPreference())).toBe(true);
  expect(() => savePreference({ skips: 3, dismissed: true })).not.toThrow();
});

it("real member and staff navigation expose every sidebar tour target", async () => {
  for (const isOwner of [false, true]) {
    await act(async () =>
      root.render(
        <SidebarNavigation
          userId="tour-fixture"
          view="home"
          canEdit={isOwner}
          isOwner={isOwner}
          onNavigate={vi.fn()}
          tourExpanded
        />,
      ),
    );
    for (const id of ["home", "todo", "register", "saved", "assignments"]) {
      const target = host.querySelector(`[data-tour-target="${id}"]`);
      expect(target).not.toBeNull();
      expect(target?.closest("[hidden]")).toBeNull();
    }
  }
});
