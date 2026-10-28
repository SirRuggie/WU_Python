// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./RosterHeader", () => ({ default: () => null }));
vi.mock("./SignupActivity", () => ({ default: () => null }));
vi.mock("./WeightQueue", () => ({
  default: () => <div>Weights target content</div>,
}));
vi.mock("./CompareClans", () => ({
  default: () => <div>Compare target content</div>,
}));
it.each([
  ["missing_weight", "Missing weights", "Weights target content"],
  ["over_capacity", "Compare clans", "Compare target content"],
] as const)(
  "opens the real workspace mode for %s",
  async (filter, label, content) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    sessionStorage.clear();
    localStorage.clear();
    api.mockResolvedValue({
      revision: 1,
      accounts: [],
      clans: [],
      metadata_updating: false,
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            <RosterWorkspace
              initialReadiness={filter}
              seasonId="1"
              seasons={
                [{ id: 1, label: "November 2026", status: "draft" }] as never
              }
              onSeasonChange={() => {}}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      const active = host.querySelector(
        '.roster-workflow-nav button[aria-pressed="true"]',
      );
      expect(active?.textContent).toContain(label);
      expect(host.textContent).toContain(content);
    } finally {
      act(() => root.unmount());
      host.remove();
      sessionStorage.clear();
      localStorage.clear();
      api.mockReset();
    }
  },
);
