// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { dashboardPath } from "./dashboardHistory";
const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./DashboardHome", () => ({ default: () => <h1>Home</h1> }));
vi.mock("./BaseBank", () => ({ default: () => <h1>Base bank</h1> }));
vi.mock("./RosterWorkspace", () => ({
  default: ({ steps }: { steps?: React.ReactNode }) => (
    <section>
      <h1>Build roster</h1>
      {steps}
    </section>
  ),
}));
vi.mock("./PublicationWorkspace", () => ({
  default: ({ steps }: { steps?: React.ReactNode }) => (
    <section>
      <h1>Finalize roster</h1>
      {steps}
    </section>
  ),
}));
vi.mock("./SignupPage", () => ({
  default: ({ steps }: { steps?: React.ReactNode }) => (
    <section>
      <h1>Sign up</h1>
      {steps}
    </section>
  ),
}));
vi.mock("./MemberAssignments", () => ({
  default: ({ steps }: { steps?: React.ReactNode }) => (
    <section>
      <h1>My clan assignments</h1>
      {steps}
    </section>
  ),
}));
vi.mock("./ownerPrank/OwnerPrank", () => ({ default: () => null }));
afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  localStorage.clear();
});
it.each([
  ["/home", "Home", null],
  ["/bases", "Base bank", "Activity"],
] as const)(
  "keeps useful desktop location context on %s without repeating an equal crumb",
  async (path, label, expectedCrumb) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    history.replaceState({ wuDashboardIndex: 0 }, "", path);
    state.api.mockImplementation(async (route: string) => {
      if (route === "/auth/me")
        return {
          authenticated: true,
          user: { id: "fixture", username: "Fixture staff" },
          is_owner: false,
          can_edit: true,
          csrf_token: "fixture",
          dashboard_permissions: [],
        };
      if (route === "/seasons")
        return {
          seasons: [
            { id: 1, label: "November", status: "draft", signup_open: true },
          ],
          member_season: { season_id: 1, revision: 0 },
        };
      if (route === "/config") return { dev_fixture: true };
      return {};
    });
    const host = document.createElement("div"),
      root = createRoot(host);
    document.body.append(host);
    try {
      await act(async () => root.render(<App />));
      for (let i = 0; i < 4; i++)
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 10));
        });
      const topbar = host.querySelector(".topbar")!;
      expect(topbar.querySelector("strong")?.textContent).toBe(label);
      expect(topbar.querySelector(".crumb")?.textContent ?? null).toBe(
        expectedCrumb,
      );
      expect(topbar.querySelector(".menu-open")).not.toBeNull();
      expect(topbar.querySelector(".topbar-logo")).not.toBeNull();
      expect(
        state.api.mock.calls.every(([, method]) => !method || method === "GET"),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
it("applies heading visibility only to the phone title, keeping desktop label styles unchanged", () => {
  const css = readFileSync("src/sidebar.css", "utf8");
  const marker = '[data-page-heading-visible="true"]';
  const selector = css.indexOf(marker);
  expect(selector).toBeGreaterThan(css.indexOf("@media (max-width: 650px)"));
  expect(css.slice(selector, css.indexOf("}", selector))).toContain(
    "display: none",
  );
  expect(css.match(/data-page-heading-visible/g)).toHaveLength(1);
});

it.each(["roster", "publication", "signup", "assignments"] as const)(
  "passes the unchanged %s steps into the page's below-heading slot once",
  async (view) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    history.replaceState(
      { wuDashboardIndex: 0 },
      "",
      dashboardPath({ view, season: "1" }),
    );
    state.api.mockImplementation(async (route: string) => {
      if (route === "/auth/me")
        return {
          authenticated: true,
          user: { id: "fixture", username: "Fixture owner" },
          is_owner: true,
          can_edit: true,
          csrf_token: "fixture",
          dashboard_permissions: [],
        };
      if (route === "/seasons")
        return {
          seasons: [
            { id: 1, label: "November", status: "draft", signup_open: true },
          ],
          member_season: { season_id: 1, revision: 0 },
        };
      if (route === "/config") return { dev_fixture: true };
      if (route.startsWith("/linked-accounts"))
        return {
          accounts: [],
          updating: false,
          total: 0,
          link_instruction: "Fixture",
        };
      if (route.includes("/signups")) return { signups: [] };
      return {};
    });
    const host = document.createElement("div"),
      root = createRoot(host);
    document.body.append(host);
    try {
      await act(async () => root.render(<App />));
      for (let i = 0; i < 4; i++)
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 10));
        });
      const main = host.querySelector("#dashboard-main")!;
      const heading = main.querySelector("h1")!;
      const steps = main.querySelector(".cwl-step-strip")!;
      expect(heading).not.toBeNull();
      expect(steps).not.toBeNull();
      expect(main.querySelectorAll(".cwl-step-strip")).toHaveLength(1);
      expect(
        heading.compareDocumentPosition(steps) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(steps.getAttribute("aria-label")).toBe(
        view === "signup" || view === "assignments"
          ? "My CWL steps"
          : "CWL workflow",
      );
      expect(
        state.api.mock.calls.every(([, method]) => !method || method === "GET"),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
