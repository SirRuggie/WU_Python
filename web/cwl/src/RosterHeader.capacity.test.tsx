// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterHeader from "./RosterHeader";
import type { RosterSnapshot } from "./roster";

vi.mock("./SignupActivity", () => ({ default: () => null }));
vi.mock("./api", () => ({
  api: vi.fn(() => new Promise(() => {})),
  ApiError: class ApiError extends Error {},
}));

function rosterWithAssignments(assignedClanTags: string[]): RosterSnapshot {
  const clans = Array.from({ length: 23 }, (_, index) => {
    const number = String(index + 1).padStart(2, "0");
    return {
      tag: `#${number}`,
      name: `Clan ${number}`,
      archived: false,
      pool: "main" as const,
      capacity: null,
      effective_capacity: 0,
      min_weight: null,
      max_weight: null,
      assigned_count: 0,
    };
  });
  return {
    revision: 1,
    undo: null,
    accounts: assignedClanTags.map((assigned_clan_tag, index) => ({
      tag: `#PLAYER${index}`,
      assigned_clan_tag,
    })) as RosterSnapshot["accounts"],
    clans: [
      ...clans,
      {
        ...clans[0],
        tag: "#ARCHIVED",
        name: "Archived",
        archived: true,
      },
      {
        ...clans[0],
        tag: "#NOPOOL",
        name: "No pool",
        pool: null,
      },
      {
        ...clans[0],
        tag: "#CONFIGURED",
        name: "Configured",
        capacity: 15,
      },
    ],
  };
}

async function renderHeader(
  roster: RosterSnapshot,
  uiLocked = false,
  navigationDisabled?: boolean,
) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onCapacitySettings = vi.fn();

  await act(async () =>
    root.render(
      <RosterHeader
        seasonId="1"
        seasons={[]}
        roster={roster}
        pool="all"
        canRoster
        canSignups={false}
        canPublish={false}
        uiLocked={uiLocked}
        navigationDisabled={navigationDisabled}
        archived={false}
        onSeasonChange={() => {}}
        onRefresh={() => {}}
        onAutoPlace={() => {}}
        onStatusFilter={() => {}}
        onAccessError={() => {}}
        onFillSignupSpot={() => false}
        onSignupDetails={() => false}
        onCapacitySettings={onCapacitySettings}
      />,
    ),
  );

  return {
    host,
    onCapacitySettings,
    cleanup: () => {
      act(() => root.unmount());
      host.remove();
    },
  };
}

it("shows no capacity warning when no hosting clan has an assignment", async () => {
  const view = await renderHeader(rosterWithAssignments([]));
  expect(view.host.querySelectorAll(".roster-capacity-alert")).toHaveLength(0);
  view.cleanup();
});

it("names the one hosting clan with missing capacity and opens its settings", async () => {
  const view = await renderHeader(
    rosterWithAssignments(["#17", "#ARCHIVED", "#NOPOOL", "#CONFIGURED"]),
  );
  const alerts = view.host.querySelectorAll(".roster-capacity-alert");
  expect(alerts).toHaveLength(1);
  expect(alerts[0].textContent).toBe(
    "⚠ Clan 17 has no capacity setSet in Clan settings ›",
  );
  const link = alerts[0].querySelector("button");
  await act(async () => link!.click());
  expect(view.onCapacitySettings).toHaveBeenCalledExactlyOnceWith("#17");
  view.cleanup();
});

it("shows one warning for two assigned clans among 23 empty clans and opens the first in clan order", async () => {
  const view = await renderHeader(rosterWithAssignments(["#17", "#04"]));
  const alerts = view.host.querySelectorAll(".roster-capacity-alert");
  expect(alerts).toHaveLength(1);
  expect(alerts[0].textContent).toBe(
    "⚠ 2 clans have no capacity setSet in Clan settings ›",
  );
  const link = alerts[0].querySelector("button");
  await act(async () => link!.click());
  expect(view.onCapacitySettings).toHaveBeenCalledExactlyOnceWith("#04");
  view.cleanup();
});

it("keeps the capacity settings link disabled while the UI is locked", async () => {
  const view = await renderHeader(rosterWithAssignments(["#04"]), true);
  const link = view.host.querySelector(".roster-capacity-alert button");
  expect(link).toBeInstanceOf(HTMLButtonElement);
  expect((link as HTMLButtonElement).disabled).toBe(true);
  await act(async () => (link as HTMLButtonElement).click());
  expect(view.onCapacitySettings).not.toHaveBeenCalled();
  view.cleanup();
});

it("allows navigation guards to handle season and settings while other controls are locked", async () => {
  const view = await renderHeader(rosterWithAssignments(["#04"]), true, false);
  const season = view.host.querySelector(".roster-menu-trigger");
  const capacity = view.host.querySelector(".roster-capacity-alert button");
  const refresh = view.host.querySelector(".roster-header-actions button");
  expect((season as HTMLButtonElement).disabled).toBe(false);
  expect((capacity as HTMLButtonElement).disabled).toBe(false);
  expect((refresh as HTMLButtonElement).disabled).toBe(true);
  await act(async () => (capacity as HTMLButtonElement).click());
  expect(view.onCapacitySettings).toHaveBeenCalledExactlyOnceWith("#04");
  view.cleanup();
});
