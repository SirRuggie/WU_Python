// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./SignupActivity", () => ({ default: () => null }));
vi.mock("./StaffSignupControls", () => ({ default: () => null }));
vi.mock("./CompareClans", () => ({ default: () => null }));
vi.mock("./WeightQueue", () => ({ default: () => null }));

it("consumes capacity-link focus so a later ordinary Clan settings visit does not refocus", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  sessionStorage.clear();
  localStorage.clear();
  const scrollIntoView = vi
    .spyOn(HTMLElement.prototype, "scrollIntoView")
    .mockImplementation(() => {});
  const account = {
    tag: "#PLAYER",
    user_id: "1",
    player_name: "Assigned player",
    pool: "main",
    town_hall: 16,
    prefer_crystal_1_or_lower: false,
    source_weight: 120000,
    source_status: "current",
    source_name: "game",
    source_checked_at: null,
    source_modified_at: null,
    manual_weight: null,
    effective_weight: 120000,
    assigned_clan_tag: "#FUN",
    kept: false,
  };
  const clan = {
    tag: "#FUN",
    name: "Funnies",
    pool: "main",
    capacity: null,
    effective_capacity: 0,
    assigned_count: 1,
    min_weight: null,
    max_weight: null,
    archived: false,
  };
  api.mockImplementation(async (path: string) =>
    path.endsWith("/publication")
      ? {
          draft_revision: 1,
          draft_changed: false,
          published: null,
          last_publication: null,
          next_version: 1,
          preview: {
            accounts: [account],
            clans: [clan],
            assigned_count: 1,
            unassigned_count: 0,
          },
        }
      : {
          revision: 1,
          undo: null,
          accounts: [account],
          clans: [clan],
          metadata_updating: false,
        },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const button = (text: string) =>
    [...host.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
      item.textContent?.includes(text),
    )!;
  const tab = (text: string) =>
    [
      ...host.querySelectorAll<HTMLButtonElement>(
        ".roster-workflow-nav button",
      ),
    ].find((item) => item.textContent?.includes(text))!;
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <RosterWorkspace
            seasonId="1"
            seasons={
              [{ id: 1, label: "November 2026", status: "draft" }] as never
            }
            onSeasonChange={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => button("Set in Clan settings").click());
    expect(
      host
        .querySelector('.clan-settings-row[data-clan="#FUN"]')
        ?.classList.contains("is-selected"),
    ).toBe(true);
    expect(document.activeElement).toBe(
      host.querySelector('.clan-settings-row[data-clan="#FUN"]'),
    );
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    await act(async () => tab("Accounts & signups").click());
    await act(async () => tab("Clan settings").click());
    expect(
      host
        .querySelector('.clan-settings-row[data-clan="#FUN"]')
        ?.classList.contains("is-selected"),
    ).toBe(false);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    await act(async () => button("Set in Clan settings").click());
    expect(scrollIntoView).toHaveBeenCalledTimes(2);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    api.mockReset();
    scrollIntoView.mockRestore();
    sessionStorage.clear();
    localStorage.clear();
  }
});
