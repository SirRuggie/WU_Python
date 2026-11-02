// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import App from "./App";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./ExportWorkspace", () => ({
  default: ({
    seasonId,
    onSeasonChange,
  }: {
    seasonId: string;
    onSeasonChange: (v: string) => void;
  }) => (
    <div data-testid="export-season">
      {seasonId}
      <button onClick={() => onSeasonChange("2")}>
        Choose October fixture
      </button>
    </div>
  ),
}));
it.each([
  ["/cwl/exports", "1"],
  ["/cwl/exports?season=2", "2"],
])(
  "direct %s automatically resolves available season and preserves explicit choice",
  async (url, expected) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    history.replaceState({}, "", url);
    localStorage.clear();
    sessionStorage.clear();
    api.mockImplementation(async (path: string) => {
      if (path === "/auth/me")
        return {
          authenticated: true,
          user: { id: "1", username: "Fixture staff" },
          is_owner: true,
          can_edit: true,
          csrf_token: "fixture",
        };
      if (path === "/seasons")
        return {
          seasons: [
            {
              id: 1,
              label: "November 2026",
              status: "draft",
              signup_open: true,
            },
            {
              id: 2,
              label: "October 2026",
              status: "archived",
              signup_open: false,
            },
          ],
          member_season: { season_id: 1, revision: 0 },
        };
      if (path === "/config") return { dev_fixture: true };
      return {};
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<App />));
      for (let i = 0; i < 5; i++)
        await act(async () => {
          await new Promise((r) => setTimeout(r, 10));
        });
      expect(
        host.querySelector('[data-testid="export-season"]')?.textContent,
      ).toContain(expected);
      expect(host.querySelector(".topbar strong")?.textContent).toBe("Exports");
      expect(
        [...host.querySelectorAll(".sidebar button")].some(
          (b) => b.textContent?.trim() === "Exports",
        ),
      ).toBe(true);
      expect(
        host.querySelector(".roster-flow-tabs")?.textContent ||
          host.textContent,
      ).not.toContain("Exports & history");
    } finally {
      await act(async () => root.unmount());
      host.remove();
      localStorage.clear();
      sessionStorage.clear();
    }
  },
);
