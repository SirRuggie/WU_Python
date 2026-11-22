// @vitest-environment happy-dom
import { act, createRef, useState, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import SignupPage from "./SignupPage";
vi.mock("./api", async (load) => ({
  ...(await load<object>()),
  api: vi.fn(async () => ({})),
}));
import type { Account } from "./api";
const accounts: Account[] = Array.from({ length: 23 }, (_, i) => ({
  tag: `#TAG${i}`,
  name: `Account ${i}`,
  town_hall: 18,
  current_clan_name: null,
  current_clan_tag: null,
  verified: true,
  lazy_eligible: true,
  lazy_ineligible_reason: null,
  family_clan_status: "approved",
}));
const noop = () => {};
function Fixture({ closed = false }: { closed?: boolean }) {
  const [count, setCount] = useState(10);
  const [draft, setDraft] = useState({ "#TAG22": false });
  const props: ComponentProps<typeof SignupPage> = {
    accountError: "",
    accounts,
    accountsReady: true,
    activeCompletion: null,
    available: accounts,
    changeReviewStep: noop,
    changeSignupPanel: noop,
    changeView: noop,
    choosePool: noop,
    completionHeadingRef: createRef(),
    dataError: "",
    draft,
    existing: [],
    loadSeasons: async () => {},
    loadSignup: async () => {},
    loadingData: false,
    matchingAccounts: accounts,
    notice: null,
    pageAccounts: accounts.slice(0, count),
    pending: false,
    pool: "main",
    poolRemoved: [],
    registeredHeadingRef: createRef(),
    retrySignupRead: async () => {},
    review: false,
    saveSavedSignups: async () => ({ saved: [], error: null }),
    savedSignupsLoaded: true,
    season: {
      id: 1,
      label: "December 2026",
      status: "draft",
      signup_open: !closed,
    },
    seasonError: "",
    seasonId: "1",
    seasonsKnown: true,
    seasonsLoading: false,
    selected: [{ tag: "#TAG22", prefer_crystal_1_or_lower: false }],
    selectionHeadingRef: createRef(),
    setCompletion: noop,
    setDraft: (next) => setDraft(next as typeof draft),
    setFwaBlocked: noop,
    setPool: noop,
    setPoolRemoved: noop,
    setReturnToReview: noop,
    setReview: noop,
    setSavedSignupDirty: noop,
    setSignupPage: setCount,
    setSignupPanel: noop,
    setSignupSearch: noop,
    setSignupStep: noop,
    showSavedSignups: async () => {},
    signupPanel: "register",
    signupSearch: "",
    signupStep: 2,
    stepHeadingRef: createRef(),
    submit: async () => {},
    visibleAccounts: accounts,
    withdraw: async () => {},
    joinRequired: false,
  };
  return <SignupPage {...props} />;
}
it("shows10, then10, thenrest; focuses first new account and keeps hidden selection", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Fixture />));
    expect(host.querySelectorAll(".account-card")).toHaveLength(10);
    expect(host.textContent).toContain("1 account selected");
    const more = () =>
      host.querySelector<HTMLButtonElement>(".bonus-show-more")!;
    expect(more().textContent).toBe("Show 10 more · 13 remaining");
    await act(async () => more().click());
    expect(host.querySelectorAll(".account-card")).toHaveLength(20);
    expect(document.activeElement).toBe(
      host.querySelectorAll(".account-card input[type=checkbox]")[10],
    );
    expect(more().textContent).toBe("Show 3 more");
    await act(async () => more().click());
    expect(host.querySelectorAll(".account-card")).toHaveLength(23);
    expect(more()).toBeNull();
    expect(
      host.querySelector<HTMLInputElement>(
        ".account-card:last-child input[type=checkbox]",
      )?.checked,
    ).toBe(true);
    expect(host.textContent).toContain("Selections across the full list");
    expect(host.textContent).not.toContain("Next accounts");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("closed signup card uses shared card and no retired guide/olive-edge class", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Fixture closed />));
    expect(
      host
        .querySelector('[data-tour-target="signup-closed"]')
        ?.classList.contains("card"),
    ).toBe(true);
    expect(host.querySelector(".signup-guide")).toBeNull();
    expect(host.querySelector(".account-card")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

import App from "./App";
import { api } from "./api";
vi.mock("./memberTour/MemberTour", () => ({ default: () => null }));

it("real App resets Show more on search, pool and account refresh without dropping hidden selections", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
  history.replaceState({}, "", "/signup");
  const season = {
    id: 1,
    label: "December 2026",
    status: "draft",
    signup_open: true,
  };
  vi.mocked(api).mockImplementation(async (path: string) =>
    structuredClone(
      path === "/auth/me"
        ? {
            authenticated: true,
            user: { id: "123456789012345678", username: "Fixture" },
            is_owner: false,
            can_edit: false,
            csrf_token: "fixture",
            server_member: true,
            dashboard_permissions: [],
          }
        : path === "/seasons"
          ? { seasons: [season], member_season: { season_id: 1, revision: 1 } }
          : path.startsWith("/linked-accounts")
            ? {
                accounts,
                updating: false,
                total: accounts.length,
                link_instruction: "",
              }
            : path.endsWith("/signups")
              ? { signups: [] }
              : path.endsWith("/my-assignments")
                ? {
                    accounts: [],
                    published: null,
                    visibility: "current",
                    draft_changed: false,
                  }
                : {},
    ),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const settle = async () => {
    for (let i = 0; i < 5; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
  };
  const more = () => host.querySelector<HTMLButtonElement>(".bonus-show-more")!;
  const rows = () => host.querySelectorAll(".account-card");
  const named = (text: string) =>
    Array.from(host.querySelectorAll("button")).find((b) =>
      b.textContent?.includes(text),
    )!;
  try {
    await act(async () => root.render(<App />));
    await settle();
    await act(async () => named("Select Main CWL").click());
    await settle();
    expect(rows()).toHaveLength(10);
    // Select all matching includes accounts not yet displayed, through the real App draft.
    const all = host.querySelector<HTMLInputElement>(
      ".selection-bar input[type=checkbox]",
    )!;
    await act(async () => all.click());
    expect(host.textContent).toContain("23 selected");
    await act(async () => more().click());
    expect(rows()).toHaveLength(20);
    const search = host.querySelector<HTMLInputElement>(
      ".signup-account-search input",
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(search, "Account");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await settle();
    expect(rows()).toHaveLength(10);
    expect(host.textContent).toContain("23 selected");
    await act(async () => more().click());
    expect(rows()).toHaveLength(20);
    const lazy =
      Array.from(
        host.querySelectorAll<HTMLButtonElement>(
          ".cwl-pool-tabs button, [role=tablist] button",
        ),
      ).find((b) => b.textContent?.includes("Lazy")) || named("Lazy CWL");
    await act(async () => lazy.click());
    await settle();
    expect(rows()).toHaveLength(20);
    expect(host.textContent).toContain("23 selected");
    let dialog = document.querySelector("dialog")!;
    expect(dialog.textContent).toContain("clear your unsubmitted selections");
    await act(async () =>
      Array.from(dialog.querySelectorAll<HTMLButtonElement>("button"))
        .find((button) => button.textContent === "Cancel")!
        .click(),
    );
    expect(rows()).toHaveLength(20);
    expect(host.textContent).toContain("23 selected");
    await act(async () => lazy.click());
    dialog = document.querySelector("dialog")!;
    await act(async () =>
      Array.from(dialog.querySelectorAll<HTMLButtonElement>("button"))
        .find((button) => button.textContent === "Change CWL pool")!
        .click(),
    );
    await settle();
    expect(rows()).toHaveLength(10);
    expect(host.textContent).toContain("0 selected");
    await act(async () => more().click());
    expect(rows()).toHaveLength(20);
    await act(async () => named("Refresh accounts").click());
    await settle();
    expect(rows()).toHaveLength(10);
    expect(
      vi.mocked(api).mock.calls.every((call) => !call[1] || call[1] === "GET"),
    ).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.mocked(api).mockReset().mockResolvedValue({});
  }
});
