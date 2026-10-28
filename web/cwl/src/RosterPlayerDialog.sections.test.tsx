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
async function render(
  overrides: Partial<RosterAccount> = {},
  permissions = ["cwl_roster", "cwl_signups"],
  extra: { archived?: boolean; viewOnly?: "declaration" } = {},
) {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: false, permissions }}>
        <RosterPlayerDialog
          {...extra}
          account={{ ...account, ...overrides }}
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

it("Loot defaults to the manual value, previews full weight, and blank clears to source", async () => {
  await render();
  const input = document.querySelector<HTMLInputElement>(
    ".compact-weight-controls input",
  )!;
  expect(input.value).toBe("25000");
  expect(input.getAttribute("aria-label")).toBe("Loot for Amber");
  expect(document.body.textContent).toContain(
    "= 125,000 full weight · saved for future seasons",
  );
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Save");
  expect(save).toHaveBeenCalledExactlyOnceWith({ manual_weight: null });
  expect(close).not.toHaveBeenCalled();
});
it("keeps the last known location with age rather than an unavailable placeholder", async () => {
  await render({
    current_clan_tag: "#OTHER",
    current_clan_name: "Other clan",
    current_clan_checked_at: new Date(Date.now() - 720000).toISOString(),
    current_clan_status: "stale",
  });
  expect(document.body.textContent).toContain("Other clan");
  expect(document.body.textContent).toContain("12m ago");
  expect(document.body.textContent).not.toContain("Unavailable");
  await render({ current_clan_status: "unavailable" });
  expect(document.body.textContent).toContain("Other clan");
  expect(document.body.textContent).toContain("12m ago");
});

it.each([
  ["Archived season · view only", { archived: true }],
  [
    "View only here · change placements in Build roster ›",
    { viewOnly: "declaration" as const },
  ],
])("view-only hides every editing section: %s", async (reason, extra) => {
  await render({}, undefined, extra);
  expect(document.body.textContent).toContain(reason);
  for (const label of ["Placement", "Weight", "Signup", "Danger area"])
    expect(document.querySelector(`section[aria-label="${label}"]`)).toBeNull();
  expect(document.body.textContent).toContain("Source & history");
  expect(save).not.toHaveBeenCalled();
});
it("signup-only staff can edit Signup, but cannot edit placements or weights", async () => {
  await render({}, ["cwl_signups"]);
  expect(document.body.textContent).toContain(
    "View only · you don't have roster editing access",
  );
  expect(document.querySelector('section[aria-label="Signup"]')).not.toBeNull();
  expect(document.querySelector('section[aria-label="Placement"]')).toBeNull();
  expect(document.querySelector(".compact-weight-controls")).toBeNull();
});
it("staff without roster or signup access see no editing actions", async () => {
  await render({}, []);
  expect(document.querySelector('section[aria-label="Signup"]')).toBeNull();
  expect(
    document.querySelector('section[aria-label="Danger area"]'),
  ).toBeNull();
  expect(document.body.textContent).toContain(
    "View only · you don't have roster editing access",
  );
});

it("a concurrent refresh does not erase unsaved weight text", async () => {
  await render();
  const input = document.querySelector<HTMLInputElement>(
    ".compact-weight-controls input",
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "31000");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await render({ manual_weight: 130000 });
  expect(input.value).toBe("31000");
  expect(save).not.toHaveBeenCalled();
});
