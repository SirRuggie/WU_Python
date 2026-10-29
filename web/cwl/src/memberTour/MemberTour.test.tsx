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
  active = vi.fn(),
  navigate = vi.fn(),
  control = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
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
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    top: 10,
    left: 10,
    right: 110,
    bottom: 54,
    width: 100,
    height: 44,
    x: 10,
    y: 10,
    toJSON() {
      return {};
    },
  });
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
  navigate.mockClear();
  control.mockClear();
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
        {[
          "signup-pool",
          "signup-account",
          "signup-review",
          "signup-confirm",
        ].map((id) => (
          <button key={id} data-tour-target={id} onClick={() => control(id)}>
            {id}
          </button>
        ))}
        <MemberTour
          view={view}
          menuOpen={false}
          onMenu={menu}
          onActive={active}
          onNavigate={navigate}
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
  expect(document.querySelector(".tour-back")).toBeNull();
  expect(document.body.textContent).not.toContain(
    "This material is unofficial",
  );
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
    if (i === 4) expect(menu).toHaveBeenLastCalledWith(false);
    if (i === 8)
      expect(document.querySelector(".tour-confetti")).not.toBeNull();
    if (i === 9) expect(document.querySelector(".tour-practice")).toBeNull();
    expect(document.querySelector(".tour-policy")).toBeNull();
    if (i === 7) {
      await click(".tour-spotlight");
      expect(document.querySelector(".tour-shake")).not.toBeNull();
      expect(control).not.toHaveBeenCalledWith("signup-confirm");
      expect(document.querySelector("#tour-title")?.textContent).toBe(
        steps[7].title,
      );
    }
    await click(".tour-next");
  }
  expect(document.querySelector("dialog")).toBeNull();
  expect(readPreference().dismissed).toBe(true);
  expect(fetch).not.toHaveBeenCalled();
  expect(control.mock.calls).toEqual([
    ["signup-pool"],
    ["signup-account"],
    ["signup-review"],
  ]);
  expect(navigate.mock.calls.map((call) => call[0])).toEqual([
    "home",
    "todo",
    "register",
    "register",
    "register",
    "register",
    "register",
    "register",
    "register",
    "saved",
    "assignments",
    "home",
  ]);
  expect(active).toHaveBeenLastCalledWith(false);
  await click(".tour-launcher");
  expect(document.querySelector("#tour-title")?.textContent).toBe(
    steps[0].title,
  );
}, 20000);
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
    await act(async () => root.render(<div />));
    sessionStorage.clear(); // A genuinely new browser session, not in-app navigation.
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
  await act(async () => root.render(<div />));
  await render(); // sessionStorage survives a page reload/remount.
  expect(document.querySelector("dialog")).toBeNull();
});

it("in-app navigation and manual replays do not consume a skip", async () => {
  await render();
  await click(".tour-skip");
  await render("todo");
  await render();
  expect(document.querySelector("dialog")).toBeNull();
  await click(".tour-launcher");
  await click(".tour-skip");
  expect(readPreference().skips).toBe(1);
});

it("crossing the phone breakpoint re-syncs the menu mid-step", async () => {
  await render();
  await click(".tour-next");
  expect(menu).toHaveBeenLastCalledWith(true);
  vi.mocked(window.matchMedia).mockReturnValue({
    matches: false,
  } as MediaQueryList);
  await act(async () => window.dispatchEvent(new Event("resize")));
  expect(menu).toHaveBeenLastCalledWith(false);
  vi.mocked(window.matchMedia).mockReturnValue({
    matches: true,
  } as MediaQueryList);
  await act(async () => window.dispatchEvent(new Event("resize")));
  expect(menu).toHaveBeenLastCalledWith(true);
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
  expect(document.activeElement?.textContent).toBe("Skip for now");
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

it("hides offscreen rings and remeasures the real target after drawer transition", async () => {
  let left = -283;
  vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockImplementation(
    function (this: HTMLElement) {
      const x = this.dataset.tourTarget ? left : 10;
      return {
        top: 10,
        left: x,
        right: x + 100,
        bottom: 54,
        width: 100,
        height: 44,
        x,
        y: 10,
        toJSON() {
          return {};
        },
      };
    },
  );
  await render();
  await click(".tour-next");
  expect(document.querySelector(".tour-spotlight")).toBeNull();
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 900)); });
  left = 10;
  await act(async () => {
    document.dispatchEvent(new Event("transitionend", { bubbles: true }));
  });
  expect(
    (document.querySelector(".tour-spotlight") as HTMLElement).style.left,
  ).toBe("10px");
});
