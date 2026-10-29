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

it("opens the named clan settings target from the top warning", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onCapacitySettings = vi.fn();
  const roster = {
    revision: 1,
    undo: null,
    accounts: [],
    clans: [
      {
        tag: "#FUN",
        name: "Funnies",
        archived: false,
        pool: "main",
        capacity: null,
        effective_capacity: 0,
        min_weight: null,
        max_weight: null,
        assigned_count: 0,
      },
    ],
  } as RosterSnapshot;
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
        uiLocked={false}
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
  const link = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Set in Clan settings ›",
  );
  expect(link).toBeTruthy();
  await act(async () => link!.click());
  expect(onCapacitySettings).toHaveBeenCalledExactlyOnceWith("#FUN");
  act(() => root.unmount());
  host.remove();
});
