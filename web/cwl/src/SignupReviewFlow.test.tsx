// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./DashboardHome", () => ({ default: () => <p>Home</p> }));
vi.mock("./TodoWorkspace", () => ({ default: () => <p>Tasks</p> }));
vi.mock("./MemberAssignments", () => ({ default: () => <p>Assignments</p> }));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("review Change links keep selections, retain eligible accounts across pools, and never submit", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/signup");
  localStorage.clear();
  sessionStorage.clear();
  vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(
    () => {},
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  } as unknown as MediaQueryList);

  const signupPosts: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).replace("/api/cwl", "");
      if (init?.method === "POST" && /\/seasons\/1\/signups$/.test(path))
        signupPosts.push(path);
      let data: object = {};
      if (path === "/auth/me")
        data = {
          user: { id: "1", username: "Member" },
          authenticated: true,
          csrf_token: "fixture",
          can_edit: false,
        };
      else if (path === "/seasons")
        data = {
          seasons: [
            { id: 1, label: "November", status: "draft", signup_open: true },
          ],
          member_season: { season_id: 1, revision: 0 },
        };
      else if (path.includes("accounts"))
        data = {
          accounts: [
            {
              tag: "#P222222Y",
              name: "Normal fixture",
              town_hall: 18,
              current_clan_type: "NORMAL",
            },
            {
              tag: "#Q222222Y",
              name: "FWA fixture",
              town_hall: 17,
              current_clan_type: "FWA",
            },
          ],
        };
      else if (path.includes("signups")) data = { signups: [] };
      return new Response(JSON.stringify(data), { status: 200 });
    }),
  );

  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const settle = async () => {
    for (let i = 0; i < 4; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
  };
  const click = async (selector: string) => {
    const element = host.querySelector<HTMLElement>(selector);
    expect(element, selector).not.toBeNull();
    await act(async () => element!.click());
    await settle();
  };
  const card = (name: string) =>
    [...host.querySelectorAll<HTMLElement>(".account-card")].find((element) =>
      element.textContent?.includes(name),
    );
  const checked = (name: string) =>
    card(name)?.querySelector<HTMLInputElement>('input[type="checkbox"]')
      ?.checked;
  const reviewNames = () =>
    [...host.querySelectorAll(".signup-review .review-row")].map(
      (row) => row.querySelector("strong")?.textContent,
    );
  const choosePool = async (name: "Lazy CWL" | "Main CWL") => {
    const button = [
      ...host.querySelectorAll<HTMLButtonElement>(".pool-choice-grid button"),
    ].find((item) => item.querySelector("strong")?.textContent === name);
    expect(button, name).toBeTruthy();
    await act(async () => button!.click());
    await settle();
  };

  try {
    await act(async () => root.render(<App />));
    await settle();
    await choosePool("Lazy CWL");
    expect(checked("Normal fixture")).toBe(false);
    expect(checked("FWA fixture")).toBe(false);
    await act(async () =>
      card("Normal fixture")!
        .querySelector<HTMLInputElement>('input[type="checkbox"]')!
        .click(),
    );
    await act(async () =>
      card("FWA fixture")!
        .querySelector<HTMLInputElement>('input[type="checkbox"]')!
        .click(),
    );
    await click(".signup-action-buttons .primary");
    expect(reviewNames()).toEqual(["Normal fixture", "FWA fixture"]);

    await click('[aria-label="Change accounts"]');
    expect(checked("Normal fixture")).toBe(true);
    expect(checked("FWA fixture")).toBe(true);
    await click(".signup-action-buttons .primary");
    expect(reviewNames()).toEqual(["Normal fixture", "FWA fixture"]);

    await click('[aria-label="Change CWL pool"]');
    await choosePool("Lazy CWL");
    expect(reviewNames()).toEqual(["Normal fixture", "FWA fixture"]);

    await click('[aria-label="Change CWL pool"]');
    await choosePool("Main CWL");
    expect(reviewNames()).toEqual(["Normal fixture"]);
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      "No longer eligible for this pool: FWA fixture",
    );
    expect(signupPosts).toEqual([]);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
