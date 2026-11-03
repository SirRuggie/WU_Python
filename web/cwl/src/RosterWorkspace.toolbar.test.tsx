// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mock.api,
}));
vi.mock("./RosterHeader", () => ({ default: () => null }));
vi.mock("./RosterClanChips", () => ({ default: () => null }));
vi.mock("./StaffSignupControls", () => ({ default: () => null }));
vi.mock("./useStaffDetailsPage", () => ({ default: () => {} }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
import RosterWorkspace from "./RosterWorkspace";
it("keeps a direct toolbar Refresh that actually rereads the roster", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  vi.spyOn(window, "matchMedia").mockImplementation(
    () =>
      ({
        matches: false,
        addEventListener() {},
        removeEventListener() {},
      }) as any,
  );
  Element.prototype.scrollIntoView = vi.fn();
  const snapshot = {
    revision: 1,
    undo: null,
    clans: [],
    accounts: [
      {
        tag: "#P2Y",
        player_name: "Local account",
        pool: "main",
        user_id: "",
        town_hall: 18,
        assigned_clan_tag: null,
        effective_weight: 100000,
        source_weight: 100000,
        source_status: "current",
        source_name: "Local",
        source_checked_at: null,
        source_modified_at: null,
        manual_weight: null,
        kept: false,
        prefer_crystal_1_or_lower: false,
      },
    ],
  };
  mock.api.mockResolvedValue(snapshot);
  const host = document.createElement("div"),
    root = createRoot(host);
  document.body.append(host);
  try {
    await act(async () =>
      root.render(
        <RosterWorkspace
          seasonId="1"
          seasons={[
            { id: 1, label: "November", status: "draft", signup_open: true },
          ]}
          onSeasonChange={() => {}}
        />,
      ),
    );
    const refresh = host.querySelector<HTMLButtonElement>(
      '.roster-filters-toolbar button[aria-label="Refresh roster"]',
    );
    expect(refresh).not.toBeNull();
    expect(refresh!.disabled).toBe(false);
    const before = mock.api.mock.calls.filter((call) =>
      String(call[0]).includes("/roster"),
    ).length;
    await act(async () => refresh!.click());
    expect(
      mock.api.mock.calls.filter((call) => String(call[0]).includes("/roster"))
        .length,
    ).toBe(before + 1);
    expect(
      mock.api.mock.calls.every((call) => !call[1] || call[1] === "GET"),
    ).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.restoreAllMocks();
    mock.api.mockReset();
  }
});
