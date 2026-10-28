// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import App from "./App";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./RosterWorkspace", () => ({
  default: () => (
    <p data-testid="roster-mode">
      {sessionStorage.getItem("wu-roster-1-mode")}
    </p>
  ),
}));
vi.mock("./PublicationWorkspace", () => ({
  default: () => <p>Publication body</p>,
}));
vi.mock("./SeasonsPage", () => ({ default: () => <p>Seasons body</p> }));
it("sidebar Build resets to Accounts and topbar names follow each CWL destination", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/cwl/roster?season=1");
  sessionStorage.clear();
  localStorage.clear();
  sessionStorage.setItem("wu-roster-1-mode", JSON.stringify("compare"));
  api.mockImplementation(async (path: string) => {
    if (path === "/auth/me")
      return {
        authenticated: true,
        user: { id: "1", username: "Staff" },
        is_owner: true,
        can_edit: true,
        csrf_token: "fixture",
      };
    if (path === "/seasons")
      return {
        seasons: [
          { id: 1, label: "November", status: "draft", signup_open: true },
        ],
        member_season: { season_id: 1, revision: 0 },
      };
    if (path === "/config") return { dev_fixture: true };
    return {};
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const settle = async () => {
    for (let i = 0; i < 4; i++)
      await act(async () => {
        await new Promise((r) => setTimeout(r, 10));
      });
  };
  const nav = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>(".sidebar button")].find(
      (b) => b.textContent?.trim() === label,
    )!;
  try {
    await act(async () => root.render(<App />));
    await settle();
    expect(host.querySelector(".topbar strong")?.textContent).toBe(
      "Build roster",
    );
    expect(host.querySelector('[data-testid="roster-mode"]')?.textContent).toBe(
      '"compare"',
    );
    await act(async () => nav("Build roster").click());
    await settle();
    expect(host.querySelector('[data-testid="roster-mode"]')?.textContent).toBe(
      '"assign"',
    );
    for (const label of ["Finalize roster", "Announcements", "Seasons"]) {
      await act(async () => nav(label).click());
      await settle();
      expect(host.querySelector(".topbar strong")?.textContent).toBe(label);
    }
    const results = [
      ...host.querySelectorAll<HTMLButtonElement>(".sidebar button"),
    ].find((b) => b.textContent?.trim() === "Results")!;
    expect(results).toBeDefined();
    expect(results.getAttribute("aria-expanded")).toBe("false");
    await act(async () => results.click());
    expect(results.getAttribute("aria-expanded")).toBe("true");
    const children = host.querySelector(
      "#" + results.getAttribute("aria-controls"),
    )!;
    expect(children.hasAttribute("hidden")).toBe(false);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    sessionStorage.clear();
    localStorage.clear();
  }
});
