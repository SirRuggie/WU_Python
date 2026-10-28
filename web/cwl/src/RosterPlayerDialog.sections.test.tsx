// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import RosterPlayerDialog from "./RosterPlayerDialog";
import { DashboardPermissions } from "./DashboardPermissions";
import type { RosterAccount, RosterSnapshot } from "./roster";
const account = {
  tag: "#P028YU9Q",
  player_name: "Amber",
  town_hall: 18,
  pool: "main",
  user_id: "",
  kept: true,
  assigned_clan_tag: "#CLAN",
  manual_weight: 125000,
  effective_weight: 125000,
  source_weight: 120000,
  source_status: "current",
  source_name: null,
  source_checked_at: null,
  source_modified_at: null,
  prefer_crystal_1_or_lower: false,
} as RosterAccount;
const roster = {
  revision: 1,
  undo: null,
  accounts: [account],
  clans: [
    {
      tag: "#CLAN",
      name: "Amber Knights",
      pool: "main",
      archived: false,
      assigned_count: 1,
      effective_capacity: 15,
    },
  ],
} as RosterSnapshot;
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const save = vi.fn(async () => true),
  remove = vi.fn(async () => true),
  close = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/cwl/roster?season=1");
  vi.spyOn(history, "back").mockImplementation(() => {});
  HTMLDialogElement.prototype.show = HTMLDialogElement.prototype.showModal =
    function () {
      this.open = true;
    };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  save.mockClear();
  remove.mockClear();
  close.mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
  host.remove();
  vi.restoreAllMocks();
});
async function render() {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <RosterPlayerDialog
          account={account}
          clans={roster.clans}
          roster={roster}
          busy={false}
          onClose={close}
          onSave={save}
          onRemove={remove}
          onPoolChange={vi.fn()}
        />
      </DashboardPermissions.Provider>,
    ),
  );
}
async function click(text: string) {
  const button = Array.from(document.querySelectorAll("button")).find(
    (b) => b.textContent?.trim() === text,
  )!;
  expect(button).toBeTruthy();
  await act(async () => button.click());
}
it("keeps the section order and saves a lock immediately without closing", async () => {
  await render();
  expect(
    Array.from(document.querySelectorAll("h3")).map((n) => n.textContent),
  ).toEqual(["At a glance", "Placement", "Weight", "Signup", "Danger area"]);
  expect(save).not.toHaveBeenCalled();
  await act(async () =>
    document.querySelector<HTMLInputElement>(".details-lock input")!.click(),
  );
  expect(save).toHaveBeenCalledExactlyOnceWith({ kept: false });
  expect(close).not.toHaveBeenCalled();
});
it("unassign and remove require their own confirmation; cancel sends nothing", async () => {
  await render();
  await click("Unassign from clan");
  expect(save).not.toHaveBeenCalled();
  await click("Cancel");
  expect(save).not.toHaveBeenCalled();
  await click("Remove signup");
  expect(remove).not.toHaveBeenCalled();
  await click("Cancel");
  expect(remove).not.toHaveBeenCalled();
});
it("unassign confirms its exact existing placement body and stays open", async () => {
  await render();
  await click("Unassign from clan");
  const buttons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("button"),
  ).filter((b) => b.textContent?.trim() === "Unassign from clan");
  await act(async () => buttons.at(-1)!.click());
  expect(save).toHaveBeenCalledExactlyOnceWith({
    assigned_clan_tag: null,
    kept: false,
  });
  expect(close).not.toHaveBeenCalled();
});
