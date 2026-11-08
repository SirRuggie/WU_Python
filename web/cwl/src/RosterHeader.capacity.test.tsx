// @vitest-environment happy-dom
import { act, type ComponentProps } from "react";
import { api as sourceApi } from "./api";
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
  extra: Partial<ComponentProps<typeof RosterHeader>> = {},
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
        {...extra}
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
    "⚠ Clan 17 has no clan size setSet in Hosting clans ›",
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
    "⚠ 2 clans have no clan size setSet in Hosting clans ›",
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
  const refresh = view.host.querySelector(
    'button[aria-label="Refresh roster"]',
  );
  expect((season as HTMLButtonElement).disabled).toBe(false);
  expect((capacity as HTMLButtonElement).disabled).toBe(false);
  expect((refresh as HTMLButtonElement).disabled).toBe(true);
  await act(async () => (capacity as HTMLButtonElement).click());
  expect(view.onCapacitySettings).toHaveBeenCalledExactlyOnceWith("#04");
  view.cleanup();
});

it("keeps publication Retry next to the visible failed-status alert without opening details", async () => {
  vi.mocked(sourceApi).mockRejectedValueOnce(new Error("Read failed"));
  const view = await renderHeader(rosterWithAssignments([]));
  try {
    const retry = [...view.host.querySelectorAll("button")].find(
      (button) => button.textContent === "Retry status",
    )!;
    expect(retry).toBeDefined();
    expect(retry.closest("details")).toBeNull();
    expect(retry.closest(".publication-awareness")?.textContent).toContain(
      "Publication status unavailable",
    );
    vi.mocked(sourceApi).mockResolvedValueOnce({
      draft_revision: 1,
      draft_changed: false,
      published: { version: 2, published_at: "2026-11-03T00:00:00Z" },
      last_publication: null,
      preview: { accounts: [], clans: [] },
    });
    await act(async () => retry.click());
    expect(
      view.host.querySelector(".roster-header-status")?.textContent,
    ).toContain("Published v2");
    expect(
      [...view.host.querySelectorAll("button")].some(
        (button) => button.textContent === "Retry status",
      ),
    ).toBe(false);
  } finally {
    view.cleanup();
  }
});

it("announces Archived instead of closed signups in the restored status region", async () => {
  const view = await renderHeader(rosterWithAssignments([]), false, false, {
    archived: true,
    seasons: [
      { id: 1, label: "November", status: "archived", signup_open: false },
    ],
  });
  try {
    const status = view.host.querySelector(
      '.roster-header-status[role="status"]',
    );
    expect(status).not.toBeNull();
    expect(status?.textContent).toContain("Archived");
    expect(status?.textContent).not.toContain("Signups closed");
  } finally {
    view.cleanup();
  }
});

it("keeps loading publication in the summary without a standalone status box", async () => {
  const view = await renderHeader(rosterWithAssignments([]));
  try {
    expect(
      view.host.querySelector(".roster-header-status")?.textContent,
    ).toContain("Checking publication…");
    expect(view.host.querySelector(".publication-awareness")).toBeNull();
    expect(
      [...view.host.querySelectorAll("button")].some(
        (button) => button.textContent === "Retry status",
      ),
    ).toBe(false);
  } finally {
    view.cleanup();
  }
});
