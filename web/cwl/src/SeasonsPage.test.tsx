// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import SeasonsPage from "./SeasonsPage";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (load) => ({ ...(await load<object>()), api }));
vi.mock("./CwlPoolRoles", () => ({ default: () => null }));
it.each([true, false])(
  "signup action remains visible with or without Build roster shortcut (%s)",
  async (canBuild) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const season = {
      id: 1,
      label: "November 2026",
      status: "draft",
      signup_open: false,
    };
    api.mockResolvedValue({
      seasons: [season],
      member_season: { season_id: 1, revision: 4 },
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const next = vi.fn();
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            <SeasonsPage
              seasonId="1"
              seasons={[season]}
              memberSeason={{ season_id: 1, revision: 4 }}
              onRefresh={async () => {}}
              onSeasonChange={() => {}}
              onClans={canBuild ? next : undefined}
              onBusy={() => {}}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      expect(host.textContent).toContain("Open signups");
      expect(host.textContent).not.toContain("Season selector");
      expect(api.mock.calls.every((c) => !c[1])).toBe(true);
      const cue = host.querySelector<HTMLButtonElement>(".cwl-next-cue");
      if (canBuild) {
        expect(cue).toBeTruthy();
        await act(async () => cue!.click());
        expect(next).toHaveBeenCalledOnce();
      } else expect(cue).toBeNull();
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
