// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import PublicationWorkspace from "./PublicationWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({
  api,
  ApiError: class extends Error {
    status = 409;
  },
}));
vi.mock("./ClanRosterImages", () => ({ default: () => null }));
vi.mock("./ManageBridgeWorkspace", () => ({ default: () => null }));
vi.mock("./StaffPlayerButton", () => ({ default: () => null }));
it("publish requires explicit confirmation; Cancel sends no write", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  const account = {
    tag: "#P",
    player_name: "Ann",
    user_id: "1",
    pool: "main",
    town_hall: 18,
    assigned_clan_tag: "#A",
    effective_weight: 170000,
    kept: false,
  };
  const draft = {
    draft_revision: 7,
    draft_changed: true,
    published: { version: 1, published_at: "2026-10-27T00:00:00Z" },
    preview: {
      accounts: [account],
      clans: [
        { tag: "#A", name: "Clan A", pool: "main", effective_capacity: 15 },
      ],
      assigned_count: 1,
      unassigned_count: 0,
    },
  };
  api.mockImplementation(async (path: string) =>
    path.includes("export-preview")
      ? {
          rows: [{ ...account, assigned_clan_tag: "#B" }],
          summary: { published_version: 1 },
        }
      : draft,
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <PublicationWorkspace
          seasonId="1"
          seasons={
            [{ id: 1, label: "November 2026", status: "draft" }] as never
          }
          onSeasonChange={() => {}}
          onFix={() => {}}
          step="review"
          onStepChange={() => {}}
        />
      </DashboardPermissions.Provider>,
    ),
  );
  const button = [...host.querySelectorAll("button")].find(
    (e) => e.textContent === "Publish updated roster",
  )!;
  expect(button.disabled).toBe(false);
  expect(document.querySelector("dialog")).toBeNull();
  await act(async () => button.click());
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Publish version 2?",
  );
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
  await act(async () =>
    [...document.querySelectorAll("dialog button")]
      .find((e) => e.textContent === "Cancel")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true })),
  );
  expect(document.querySelector("dialog")).toBeNull();
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
  act(() => root.unmount());
  host.remove();
  api.mockReset();
});
