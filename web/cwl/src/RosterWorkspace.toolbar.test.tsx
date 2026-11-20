// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mock.api,
}));
vi.mock("./RosterClanChips", () => ({ default: () => null }));
vi.mock("./StaffSignupControls", () => ({ default: () => null }));
vi.mock("./useStaffDetailsPage", () => ({ default: () => {} }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
import RosterWorkspace from "./RosterWorkspace";
it("keeps one header Refresh that actually rereads the roster", async () => {
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
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(
    function (this: HTMLElement) {
      return this.isConnected
        ? ([new DOMRect(0, 0, 44, 44)] as unknown as DOMRectList)
        : ([] as unknown as DOMRectList);
    },
  );
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
    const tabs = host.querySelector('[aria-label="Roster workspace views"]')!;
    expect(tabs.getAttribute("role")).toBe("tablist");
    expect(tabs.querySelectorAll('[role="tab"]')).toHaveLength(4);
    const toolbar = host.querySelector(".roster-filters-toolbar")!;
    const pool = toolbar.querySelector('[aria-label="CWL account pool"]')!;
    expect(pool.getAttribute("role")).toBe("group");
    expect(
      host.querySelectorAll('[aria-label="CWL account pool"]'),
    ).toHaveLength(1);
    const lazy = [...pool.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent?.includes("Lazy"),
    )!;
    const beforePoolUrl = window.location.search;
    await act(async () => lazy.click());
    expect(lazy.getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).toContain("0 matching");
    expect(window.location.search).toBe(beforePoolUrl);
    expect(
      JSON.parse(sessionStorage.getItem("wu-roster-1-release-v1")!).pool,
    ).toBe("lazy");
    const all = [...pool.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent?.includes("All"),
    )!;
    await act(async () => all.click());
    expect(host.textContent).toContain("1 matching");
    const icon = host.querySelector<HTMLButtonElement>(".roster-sort-trigger")!;
    await act(async () => icon.click());
    const highest = [
      ...document.querySelectorAll<HTMLButtonElement>(
        ".roster-sort-options button",
      ),
    ].find((b) => b.textContent === "Weight: highest first")!;
    await act(async () => highest.click());
    const countSort = host.querySelector<HTMLButtonElement>(
      ".roster-count-sort > button",
    )!;
    expect(countSort.textContent).toBe("Weight ↓");
    expect(countSort.getAttribute("aria-label")).toBe(
      icon.getAttribute("aria-label"),
    );
    await act(async () => countSort.click());
    expect(document.querySelector(".action-panel")?.textContent).toContain(
      "Sort accounts",
    );
    const group = document.querySelector<HTMLInputElement>(
      ".roster-group-toggle input",
    )!;
    await act(async () => group.click());
    expect(countSort.textContent).toBe("Weight ↓ · Grouped");
    expect(countSort.getAttribute("aria-label")).toBe(
      "Sort: Weight: highest first, grouped by Discord user",
    );
    await act(async () =>
      document
        .querySelector("dialog.action-panel")!
        .dispatchEvent(new Event("cancel", { cancelable: true })),
    );
    await act(
      async () =>
        new Promise<void>((resolve) => requestAnimationFrame(() => resolve())),
    );
    expect(document.activeElement).toBe(countSort);
    await act(async () => icon.click());
    await act(async () =>
      document
        .querySelector("dialog.action-panel")!
        .dispatchEvent(new Event("cancel", { cancelable: true })),
    );
    await act(
      async () =>
        new Promise<void>((resolve) => requestAnimationFrame(() => resolve())),
    );
    expect(document.activeElement).toBe(icon);
    const refresh = host.querySelector<HTMLButtonElement>(
      '.roster-header button[aria-label="Refresh"]',
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
