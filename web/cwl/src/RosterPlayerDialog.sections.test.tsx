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
  permissions = ["cwl_roster", "cwl_signups", "clan_weights"],
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
it("uses the shared Now in pin for a checked location", async () => {
  await render({
    current_clan_tag: "#OTHER",
    current_clan_name: "Other clan",
    current_clan_checked_at: "2026-10-28T12:00:00Z",
  });
  expect(
    document.querySelector(
      '.player-clan-status .player-location-pin[aria-hidden="true"]',
    ),
  ).not.toBeNull();
  expect(
    document.querySelector(".player-clan-status")?.textContent,
  ).not.toContain("→");
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

it("Loot shows the linked value and blank saves Not Available", async () => {
  await render();
  const input = document.querySelector<HTMLInputElement>(
    'input[aria-label="Loot for Amber"]',
  )!;
  expect(input.value).toBe("25000");
  expect(input.getAttribute("aria-label")).toBe("Loot for Amber");
  expect(document.body.textContent).toContain(
    "Loot × storages = full weight. Blank means Not Available.",
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
  expect(save).toHaveBeenCalledExactlyOnceWith({
    manual_weight: null,
    weight_revision: 0,
    weight_storages: 5,
  });
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
    'input[aria-label="Loot for Amber"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "31000");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await render({
    manual_weight: 130000,
    effective_weight: 130000,
    weight_revision: 2,
  });
  expect(input.value).toBe("31000");
  expect(save).not.toHaveBeenCalled();
});

it("blocks a second tap before the first lock save settles", async () => {
  let resolve!: (value: boolean) => void;
  save.mockImplementationOnce(
    () =>
      new Promise<boolean>((done) => {
        resolve = done;
      }),
  );
  await render();
  const lock = document.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  await act(async () => {
    lock.click();
    lock.click();
  });
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => resolve(true));
});
it("rechecks permission at confirmation after access is revoked", async () => {
  await render();
  await click("Remove signup");
  await render({}, []);
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>(".confirm-dialog .confirm-danger")!
      .click(),
  );
  expect(remove).not.toHaveBeenCalled();
});
it("rechecks dirty weight at confirmation", async () => {
  await render();
  await click("Remove signup");
  const input = document.querySelector<HTMLInputElement>(
    'input[aria-label="Loot for Amber"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "31000");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>(".confirm-dialog .confirm-danger")!
      .click(),
  );
  expect(remove).not.toHaveBeenCalled();
});
it("disables an unchanged weight Save and exposes a real Declaration link", async () => {
  await render();
  expect(
    Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === "Save",
    )?.disabled,
  ).toBe(true);
  await render({}, undefined, { viewOnly: "declaration" });
  expect(
    document
      .querySelector<HTMLAnchorElement>(".details-view-only a")
      ?.getAttribute("href"),
  ).toBe("/cwl/roster?season=1&account=%23P028YU9Q");
});

it("Change clan immediately sends the exact manual placement body", async () => {
  await render({ assigned_clan_tag: null, kept: false });
  await click("Change clan");
  const target = document.querySelector<HTMLButtonElement>(
    ".roster-assign-clan",
  )!;
  expect(target).toBeTruthy();
  await act(async () => target.click());
  expect(save).toHaveBeenCalledExactlyOnceWith({
    assigned_clan_tag: "#CLAN",
    kept: true,
  });
});

it("keeps Save disabled for an equivalent full-weight value", async () => {
  await render();
  const input = document.querySelector<HTMLInputElement>(
    'input[aria-label="Full weight for Amber"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "125000");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(
    Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent === "Save",
    )?.disabled,
  ).toBe(true);
});

it("routes an FWA member without a saved weight to Clan weights consistently", async () => {
  await render(
    {
      clan_weight_managed: false,
      current_fwa_clan_tag: "#FWA",
      effective_weight: null,
      manual_weight: null,
    },
    ["cwl_roster", "clan_weights"],
  );
  const section = document.querySelector('[aria-label="Weight"]')!;
  expect(section.textContent).toContain("Also on Clan weights ›");
  expect(section.querySelector("input")).not.toBeNull();
  expect(save).not.toHaveBeenCalled();
});

it.each(["179000", "179,000", "179k"])(
  "FWA popup saves %s through the linked revision",
  async (text) => {
    await render({
      clan_weight_managed: true,
      current_fwa_clan_tag: "#FWA",
      weight_revision: 7,
    });
    const input = document.querySelector<HTMLInputElement>(
      'input[aria-label="Full weight for Amber"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, text);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click("Save");
    expect(save).toHaveBeenCalledExactlyOnceWith({
      manual_weight: 179000,
      weight_revision: 7,
      weight_storages: 5,
    });
  },
);

it("a weight conflict preserves typed text and Clear waits for Save", async () => {
  await render({ clan_weight_managed: true, weight_revision: 4 });
  const input = document.querySelector<HTMLInputElement>(
    'input[aria-label="Full weight for Amber"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "179k");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  save.mockRejectedValueOnce(new Error("Changed by someone else · Reload"));
  await click("Save");
  expect(input.value).toBe("179k");
  expect(document.body.textContent).toContain(
    "Changed by someone else · Reload",
  );
  await click("Clear weight");
  expect(input.value).toBe("");
  expect(save).toHaveBeenCalledTimes(1);
  await click("Save");
  expect(save).toHaveBeenLastCalledWith({
    manual_weight: null,
    weight_revision: 4,
    weight_storages: 5,
  });
});

it("opens a historical fractional-thousand weight clean and closes without a discard prompt", async () => {
  await render({ effective_weight: 151500 });
  expect(document.body.textContent).toContain(
    "Saved value isn't a whole thousand. Enter a new one to change it.",
  );
  expect(
    document.querySelector<HTMLInputElement>(
      'input[aria-label="Full weight for Amber"]',
    )!.value,
  ).toBe("");
  await click("‹ Build roster");
  expect(close).toHaveBeenCalledOnce();
  expect(document.body.textContent).not.toContain("Discard the unsaved weight");
  expect(save).not.toHaveBeenCalled();
});
it("roster-only staff can place players but cannot edit linked weights", async () => {
  await render({ current_fwa_clan_tag: "#R2Y", clan_weight_managed: true }, [
    "cwl_roster",
  ]);
  const section = document.querySelector('[aria-label="Weight"]')!;
  expect(section.querySelector("input")).toBeNull();
  expect(section.textContent).toContain("125,000");
  expect(section.textContent).toContain("Clan weights access required");
  expect(save).not.toHaveBeenCalled();
});

it("allows clearing a historical fractional-thousand value only after explicit Save", async () => {
  await render({ effective_weight: 151500, weight_revision: 4 });
  expect(document.body.textContent).not.toContain("Will clear on Save");
  await click("Clear weight");
  expect(document.body.textContent).toContain("Will clear on Save");
  expect(save).not.toHaveBeenCalled();
  await click("Save");
  expect(save).toHaveBeenLastCalledWith({
    manual_weight: null,
    weight_revision: 4,
    weight_storages: 5,
  });
});
