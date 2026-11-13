// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import SeasonsPage from "./SeasonsPage";
import { pickOption, pickerByLabel } from "./searchPickerTestUtils";
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

it.each([false, true])(
  "settings-only staff retain shared signup window controls when Build is unavailable: open=%s",
  async (signupOpen) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const season = {
      id: 1,
      label: "November",
      status: "draft",
      signup_open: signupOpen,
    } as Season;
    api.mockResolvedValue({
      seasons: [season],
      member_season: { season_id: 1, revision: 1 },
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: false, permissions: ["cwl_settings"] }}
          >
            <SeasonsPage
              seasonId="1"
              seasons={[season]}
              memberSeason={{ season_id: 1, revision: 1 }}
              onSeasonChange={() => {}}
              onRefresh={async () => {}}
              onBusy={() => {}}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      const settings = host.querySelector<HTMLButtonElement>(
        'button[aria-label="Signup window settings"]',
      );
      expect(settings).not.toBeNull();
      await act(async () => settings!.click());
      expect(document.body.textContent).toContain(
        signupOpen ? "Close signups" : "Open signups",
      );
      expect(host.querySelector(".cwl-next-cue")).toBeNull();
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);

it("reports a real pool-role draft as dirty without saving it", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const season = {
    id: 1,
    label: "November",
    status: "draft",
    signup_open: false,
  } as Season;
  api.mockImplementation(async (path: string) =>
    path.startsWith("/pool-roles")
      ? {
          pools: ["main", "lazy"].map((pool) => ({
            pool,
            role_id: null,
            revision: 0,
            member_basis: "fixture",
            member_count: 0,
            progress: {},
            failure: null,
          })),
          roles: [{ id: "123456789012345678", name: "CWL players" }],
        }
      : { seasons: [season], member_season: { season_id: 1, revision: 1 } },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const dirty = vi.fn();
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider
          value={{ owner: false, permissions: ["cwl_settings", "cwl_roster"] }}
        >
          <SeasonsPage
            seasonId="1"
            seasons={[season]}
            memberSeason={{ season_id: 1, revision: 1 }}
            onSeasonChange={() => {}}
            onRefresh={async () => {}}
            onBusy={() => {}}
            onDirty={dirty}
            onClans={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    const main = pickerByLabel(host, "Main role");
    await pickOption(main, "CWL players");
    expect(dirty).toHaveBeenLastCalledWith(true);
    expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
      true,
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("offers Try again that reloads the season list when the refresh fails", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
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
  const onRefresh = vi
    .fn<() => Promise<void>>()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue(undefined);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <SeasonsPage
            seasonId="1"
            seasons={[season]}
            memberSeason={{ season_id: 1, revision: 1 }}
            onSeasonChange={() => {}}
            onRefresh={onRefresh}
            onBusy={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    const hide = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Hide member season",
    )!;
    await act(async () => hide.click());
    const confirm = [...document.querySelectorAll("button")].find(
      (button) => button.textContent === "Hide season",
    )!;
    await act(async () => confirm.click());
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(host.querySelector(".load-error")?.textContent).toContain(
      "The season list could not refresh.",
    );
    const retry = [
      ...host.querySelectorAll<HTMLButtonElement>(".load-error button"),
    ].find((button) => button.textContent === "Try again")!;
    await act(async () => retry.click());
    expect(onRefresh).toHaveBeenCalledTimes(2);
    expect(host.querySelector(".load-error")).toBeNull();
    // The retry only reloads; it never writes again.
    expect(api.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
