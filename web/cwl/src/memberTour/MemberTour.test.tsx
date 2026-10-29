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
async function render(
  view = "home",
  signupState: import("./session").SignupTourState = "open",
  startBlocked = false,
  inviteBlocked = false,
) {
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
        <button
          data-tour-target="signup-pool"
          onClick={() => control("signup-pool")}
        >
          Lazy CWL
        </button>
        <article data-tour-target="signup-account">
          <input
            type="checkbox"
            aria-label="Select account"
            onClick={() => control("signup-account")}
          />
          <span>Account name · tag · current clan</span>
        </article>
        <section data-tour-target="signup-review">Review block</section>
        <button data-tour-target="signup-confirm">Sign up</button>
        <MemberTour
          view={view}
          signupState={signupState}
          startBlocked={startBlocked}
          inviteBlocked={inviteBlocked}
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
it("waits for the owner prank before inviting the member tour", async () => {
  await render("home", "open", false, true);
  expect(document.querySelector(".member-tour")).toBeNull();
  await render("home", "open", false, false);
  expect(document.querySelector(".member-tour")).not.toBeNull();
});
it("queues manual Help & tour while the prank owns the dialog", async () => {
  await render("home", "open", false, true);
  await click(".tour-launcher");
  expect(document.querySelector(".member-tour")).toBeNull();
  expect(document.querySelector(".tour-launcher")?.textContent).toContain(
    "Tour queued",
  );
  await render("home", "open", false, false);
  expect(document.querySelectorAll(".member-tour")).toHaveLength(1);
  expect(document.querySelector("#tour-title")?.textContent).toBe(
    steps[0].title,
  );
  expect(active).toHaveBeenCalledTimes(1);
});
it("opens manual Help & tour immediately for ordinary members", async () => {
  await render("todo");
  await click(".tour-launcher");
  expect(document.querySelector(".member-tour")).not.toBeNull();
});
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
    if (i === 5)
      expect(
        document.querySelector<HTMLInputElement>(
          '[data-tour-target="signup-account"] input',
        )?.checked,
      ).toBe(true);
  }
  expect(document.querySelector("dialog")).toBeNull();
  expect(readPreference().dismissed).toBe(true);
  expect(fetch).not.toHaveBeenCalled();
  expect(control.mock.calls).toEqual([["signup-pool"], ["signup-account"]]);
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

it("tour opens only the target sidebar section and preserves the saved expansion state", async () => {
  localStorage.setItem(
    "wu-navigation-v3:tour-fixture",
    JSON.stringify({ "my-cwl": false }),
  );
  await act(async () =>
    root.render(
      <SidebarNavigation
        userId="tour-fixture"
        view="home"
        canEdit={false}
        isOwner={false}
        onNavigate={vi.fn()}
      />,
    ),
  );
  for (const isOwner of [false, true]) {
    for (const view of ["home", "todo", "signup", "assignments"] as const) {
      const before = localStorage.getItem("wu-navigation-v3:tour-fixture");
      await act(async () =>
        root.render(
          <SidebarNavigation
            userId="tour-fixture"
            view={view}
            canEdit={isOwner}
            isOwner={isOwner}
            onNavigate={vi.fn()}
            tourExpanded
          />,
        ),
      );
      const target = host.querySelector(
        `[data-tour-target="${view === "signup" ? "register" : view}"]`,
      );
      expect(target?.closest("[hidden]")).toBeNull();
      expect(
        host
          .querySelector("#navigation-cwl-management")
          ?.hasAttribute("hidden") ?? true,
      ).toBe(true);
      expect(localStorage.getItem("wu-navigation-v3:tour-fixture")).toBe(
        before,
      );
    }
  }
  await act(async () =>
    root.render(
      <SidebarNavigation
        userId="tour-fixture"
        view="home"
        canEdit={false}
        isOwner={false}
        onNavigate={vi.fn()}
      />,
    ),
  );
  expect(host.querySelector("#navigation-my-cwl")?.hasAttribute("hidden")).toBe(
    true,
  );
});
it("failed account reads explain the error and allow continuing", async () => {
  await render("home", "error");
  for (let i = 0; i < 3; i++) await click(".tour-next");
  expect(document.querySelector(".tour-copy")?.textContent).toContain(
    "We couldn't load your accounts — you can still finish the tour.",
  );
  expect(
    document.querySelector<HTMLButtonElement>(".tour-next")?.disabled,
  ).toBe(false);
  await click(".tour-next");
  expect(document.querySelector("#tour-title")?.textContent).toBe(
    steps[9].title,
  );
});
it("clears the blocked staff editor explanation as soon as the editor is clean", async () => {
  active.mockReturnValueOnce(false);
  await render("signup", "open", true);
  await click(".tour-launcher");
  expect(host.textContent).toContain("Save or discard your changes first.");
  expect(document.querySelector("dialog")).toBeNull();
  await render("signup", "open", false);
  expect(host.textContent).not.toContain("Save or discard your changes first.");
});

it("uses the approved playful tour copy and bolds each navigation tap target", () => {
  expect(steps.map(({ title, text }) => [title, text])).toEqual([
    [
      "Hey Chief! Welcome to Warriors United!",
      "Let's take a minute to show you around.",
    ],
    ["Start here, Chief!", "Tap **Home** — it shows what to do next."],
    [
      "Ready to smash some bases?",
      "Tap **Tasks** — your attacks and events live here.",
    ],
    [
      "Up here, Chief!",
      "Tap **Sign up** — this is where you join every month.",
    ],
    ["Feeling lazy? Same.", "Tap **Lazy CWL** — we'll practice with Lazy."],
    ["That one! Pick an account.", "Tap your account to select it."],
    [
      "Hmm… did you pick the right ones?",
      "Check your accounts before you finish.",
    ],
    [
      "SMASH that button!",
      "…for real, when you're ready. In the tour we stop here, so nothing's saved.",
    ],
    ["WOOO! That's all it takes!", "Practice — nothing saved."],
    [
      "Don't sleep on the job!",
      "Sign up for real every month before signups close.",
    ],
    [
      "Going crazy wondering if you signed up? 🤪",
      "Tap **My signups** — every account you signed up is right here.",
    ],
    [
      "Don't give the King a headache!",
      "Make sure you join the right clan — tap **My clan assignments** to check yours.",
    ],
    [
      "Told you it was easy.",
      "Tap ? anytime to see this again. In Discord, Check my signups works too.",
    ],
  ]);
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
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 900));
  });
  left = 10;
  await act(async () => {
    document.dispatchEvent(new Event("transitionend", { bubbles: true }));
  });
  expect(
    (document.querySelector(".tour-spotlight") as HTMLElement).style.left,
  ).toBe("10px");
});
