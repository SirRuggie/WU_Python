// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./ServerManagement", () => ({
  default: () => <p>Server page reached</p>,
}));
vi.mock("./DashboardHome", () => ({ default: () => <p>Home reached</p> }));
vi.mock("./ModerationWorkspace", () => ({
  default: () => <p>Member activity reached</p>,
}));
afterEach(() => {
  state.api.mockReset();
  sessionStorage.clear();
  localStorage.clear();
});
it.each([
  ["/server", true, [], true],
  ["/server", false, ["server_tools"], false],
  ["/server/member-activity", false, ["member_roles"], true],
  ["/server/member-activity", false, ["server_tools"], false],
] as const)(
  "direct access to %s keeps the existing owner/moderation grants",
  async (path, owner, permissions, allowed) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    history.replaceState({ wuDashboardIndex: 0 }, "", path);
    state.api.mockImplementation(async (route: string) => {
      if (route === "/prank/state") throw new Error("Fixture disabled");
      if (route === "/auth/me")
        return {
          authenticated: true,
          user: { id: "fixture", username: "Fixture staff" },
          is_owner: owner,
          can_edit: true,
          csrf_token: "fixture",
          dashboard_permissions: permissions,
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
      if (allowed) {
        expect(host.textContent).toContain(
          path === "/server"
            ? "Server page reached"
            : "Member activity reached",
        );
        expect(host.textContent).not.toContain("You do not have access");
      } else {
        expect(host.textContent).toContain("Home reached");
        expect(host.textContent).toContain("You do not have access");
        expect(host.textContent).not.toContain("Server page reached");
        expect(host.textContent).not.toContain("Member activity reached");
      }
      expect(
        state.api.mock.calls.every(([, method]) => !method || method === "GET"),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
