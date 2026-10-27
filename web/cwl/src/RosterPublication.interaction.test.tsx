// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api, ApiError: class extends Error {} }));
vi.mock("./CompareClans", () => ({ default: () => null }));
vi.mock("./WeightQueue", () => ({ default: () => null }));
vi.mock("./SignupActivity", () => ({ default: () => null }));
vi.mock("./StaffSignupControls", () => ({ default: () => null }));
vi.mock("./RosterAccountCard", () => ({
  default: ({ onAssign, onSignup }: any) => (
    <>
      <button onClick={(e) => onAssign(e.currentTarget)}>Test assign</button>
      <button onClick={(e) => onSignup(e.currentTarget)}>Test signup</button>
    </>
  ),
}));
vi.mock("./RosterAssignPanel", () => ({
  default: ({ onAssign, onClose }: any) => (
    <button
      onClick={async () => {
        await onAssign(null);
        onClose();
      }}
    >
      Test apply assignment
    </button>
  ),
}));
vi.mock("./RosterSignupPanel", () => ({
  default: ({ onApply, onClose }: any) => (
    <button
      onClick={async () => {
        await onApply("lazy", ["#P"]);
        onClose();
      }}
    >
      Test apply signup
    </button>
  ),
}));

it("retains banner on refetch, scopes it to roster tabs and labels only placement and Undo toasts", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  sessionStorage.clear();
  localStorage.clear();
  const account = {
    tag: "#P",
    player_name: "Ann",
    user_id: "1",
    pool: "main",
    town_hall: 18,
    effective_weight: 170000,
    assigned_clan_tag: null,
    kept: false,
  };
  let snapshot = {
    revision: 1,
    accounts: [account],
    clans: [],
    undo: null as null | { id: number; revision: number; label: string },
  };
  let published = {
    draft_changed: true,
    published: { version: 1, published_at: "2026-10-27T18:05:00Z" },
  };
  let pending = false;
  let resolve!: (value: unknown) => void;
  api.mockImplementation(async (path: string, method?: string) => {
    if (path.endsWith("/publication"))
      return pending ? new Promise((r) => (resolve = r)) : published;
    if (method && method !== "GET") {
      snapshot = {
        ...snapshot,
        revision: snapshot.revision + 1,
        undo: {
          id: 1,
          revision: snapshot.revision + 1,
          label: "Assignment changed",
        },
      };
      return { count: 1 };
    }
    return snapshot;
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <RosterWorkspace
          seasonId="1"
          seasons={
            [{ id: 1, label: "November 2026", status: "draft" }] as never
          }
          onSeasonChange={() => {}}
          onReviewPublication={() => {}}
        />
      </DashboardPermissions.Provider>,
    ),
  );
  const click = async (label: string) => {
    const b = [...host.querySelectorAll("button")].find(
      (e) => e.textContent === label,
    )!;
    expect(b, label).toBeTruthy();
    await act(async () => b.click());
  };
  const banner = () => host.querySelector(".publication-awareness");
  expect(banner()?.textContent).toMatch(
    /Published Oct 27, \d{1,2}:\d{2} [AP]M/,
  );
  expect(banner()?.textContent).not.toMatch(/:\d{2}:\d{2}/);
  for (const tab of ["Compare clans", "Clan settings", "Accounts & signups"]) {
    await click(tab);
    expect(banner()).not.toBeNull();
  }
  await click("Weights · 0 missing");
  expect(banner()).toBeNull();
  await click("Accounts & signups");
  await click("Test assign");
  pending = true;
  await click("Test apply assignment");
  expect(banner()?.textContent).toContain("Members still see roster version 1");
  expect(host.querySelector(".notice.success")?.textContent).toContain(
    "Draft only, not published",
  );
  expect(host.querySelector(".roster-undo-toast")?.textContent).toContain(
    "Draft only, not published",
  );
  pending = false;
  await act(async () => resolve(published));
  await click("Undo");
  expect(host.querySelector(".notice.success")?.textContent).toContain(
    "Last placement change undone. · Draft only, not published",
  );
  await click("Test signup");
  await click("Test apply signup");
  expect(host.querySelector(".notice.success")?.textContent).toContain(
    "signup changed to Lazy CWL",
  );
  expect(host.querySelector(".notice.success")?.textContent).not.toContain(
    "Draft only",
  );
  published = { ...published, draft_changed: false };
  await click("Test assign");
  await click("Test apply assignment");
  expect(banner()).toBeNull();
  act(() => root.unmount());
  host.remove();
  api.mockReset();
});
