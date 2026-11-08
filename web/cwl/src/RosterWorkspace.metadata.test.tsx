// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
import type { RosterAccount, RosterSnapshot } from "./roster";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./RosterHeader", () => ({ default: () => null }));
vi.mock("./SignupActivity", () => ({ default: () => null }));

it("announces metadata inside the count and removes only that status after the read completes", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  sessionStorage.clear();
  localStorage.clear();
  const accounts = [
    {
      tag: "#FIXTURE",
      user_id: "1",
      player_name: "Fixture player",
      pool: "main",
      town_hall: 16,
      source_weight: null,
      source_status: "missing",
      source_name: null,
      source_checked_at: null,
      source_modified_at: null,
      manual_weight: null,
      effective_weight: null,
      assigned_clan_tag: null,
      kept: false,
      prefer_crystal_1_or_lower: false,
    },
  ] as RosterAccount[];
  const snapshot: RosterSnapshot = {
    revision: 1,
    accounts,
    clans: [],
    undo: null,
    metadata_updating: true,
  };
  let reads = 0;
  api.mockImplementation(async () => ({
    ...snapshot,
    metadata_updating: ++reads === 1,
  }));
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <RosterWorkspace
            seasonId="1"
            seasons={[]}
            onSeasonChange={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    const heading = host.querySelector(".roster-list-heading")!;
    const countArea = heading.querySelector(".roster-list-count")!;
    const countNode = heading.querySelector(".roster-list-count-text")!;
    const count = countNode.textContent;
    const countLayoutClass = countArea.className;
    expect(heading.querySelector('[role="status"]')?.textContent).toBe(
      "Updating live clan details…",
    );
    expect(host.querySelectorAll(".roster-list-updating")).toHaveLength(1);
    expect(host.textContent).not.toContain("Saved assignments are ready.");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(heading.querySelector('[role="status"]')).toBeNull();
    expect(heading.querySelector(".roster-list-count")).toBe(countArea);
    expect(heading.querySelector(".roster-list-count-text")).toBe(countNode);
    expect(countArea.className).toBe(countLayoutClass);
    expect(heading.querySelector(".roster-list-count-text")!.textContent).toBe(
      count,
    );
    expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
      true,
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});
