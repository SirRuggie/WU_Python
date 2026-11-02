// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import SeasonsPage from "./SeasonsPage";
import type { Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./rosterUi/Menu", () => ({
  default: () => <span>Season selector</span>,
}));
it("keeps signup writes on Build roster and offers one read-only Next destination", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  const season = {
    id: 1,
    label: "November 2026",
    signup_open: false,
    status: "draft",
  } as Season;
  api.mockResolvedValue({
    seasons: [season],
    member_season: { season_id: 1, revision: 1 },
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const next = vi.fn();
  const render = (canBuild = true) => (
    <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
      <SeasonsPage
        userId="12"
        seasonId="1"
        seasons={[season]}
        memberSeason={{ season_id: 1, revision: 1 }}
        onSeasonChange={() => {}}
        onRefresh={async () => {}}
        onClans={canBuild ? next : undefined}
        onBusy={() => {}}
      />
    </DashboardPermissions.Provider>
  );
  try {
    await act(async () => root.render(render()));
    expect(host.textContent).toContain("Create season");
    expect(host.textContent).toContain("Direct signup link");
    expect(host.textContent).not.toContain("Hosting clan directory");
    expect(host.textContent).not.toContain("Family clans");
    expect(host.textContent).not.toContain("Hosting clans moved to");
    expect(host.querySelectorAll(".cwl-next-cue")).toHaveLength(1);
    expect(host.textContent).not.toContain("Open signups");
    expect(host.textContent).not.toContain("Close signups");
    await act(async () =>
      (host.querySelector(".cwl-next-cue") as HTMLButtonElement).click(),
    );
    expect(next).toHaveBeenCalledOnce();
    await act(async () => root.render(render(false)));
    expect(host.querySelector(".cwl-next-cue")).toBeNull();
    expect(host.textContent).toContain("Create season");
    expect(api.mock.calls.every((call) => call[1] === undefined)).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
