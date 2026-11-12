// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import ResultsSettingsSheet from "./ResultsSettingsSheet";
import { pickerByLabel, pickOption } from "./searchPickerTestUtils";

const sync = {
  cycle: "2026-11",
  enabled: false,
  cycle_source: "settings",
  status: "waiting",
  warning: null,
  last_checked_at: null,
  last_success_at: null,
  updated_at: "2026-11-01T00:00:00Z",
};
const participation = { accounts: [], publication_version: 1, sync };
const rep = (tag: string, name: string, user: string | null, note = "") => ({
  tag,
  player_name: name,
  town_hall: 16,
  user_id: user,
  note,
  revision: 1,
});
const raffle = {
  season_status: "draft",
  revision: 7,
  rep_accounts: [
    rep("#P2Y", "Alpha", "111111111111111111", "REP for Edrag Rush/420"),
    rep("#Q2Y", "Bravo", null),
    rep("#R2Y", "Charlie", "111111111111111111"),
  ],
};
const clanReps = {
  members: [
    { id: "111111111111111111", display_name: "Ruggie", username: "ruggie" },
  ],
};
const linked = {
  accounts: [
    { tag: "#P2Y", name: "Alpha", town_hall: 16 },
    { tag: "#V2Y", name: "Victor", town_hall: 15 },
  ],
};
const members = {
  options: [{ id: "111111111111111111", display_name: "Ruggie" }],
};
let host: HTMLDivElement;
let root: Root;
const onClose = vi.fn();
const onSaved = vi.fn();
const onDirty = vi.fn();
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent?.trim() === name,
  )!;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const type = async (input: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
async function open(
  props: Partial<Parameters<typeof ResultsSettingsSheet>[0]> = {},
) {
  await act(async () =>
    root.render(
      <ResultsSettingsSheet
        seasonId="1"
        canCapture
        canOdds
        archived={false}
        trigger={null}
        onDirty={onDirty}
        onClose={onClose}
        onSaved={onSaved}
        {...props}
      />,
    ),
  );
  await settle();
}
const month = () =>
  document.querySelector<HTMLInputElement>('input[type="month"]')!;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  onClose.mockReset();
  onSaved.mockReset();
  onDirty.mockReset();
  api
    .mockReset()
    .mockImplementation(async (route: string) =>
      route.startsWith("/staff-signup-members")
        ? members
        : route.endsWith("/bonus-raffle/clan-rep-members")
          ? clanReps
          : route.includes("/staff-signups/accounts?user_id=")
            ? linked
            : route.endsWith("/bonus-raffle/rep-accounts")
              ? { ...raffle, revision: 8, rep_accounts: [] }
              : route.endsWith("/participation/sync-settings")
                ? { sync: { ...sync, cycle: "2026-12", enabled: true } }
                : route.endsWith("/bonus-raffle")
                  ? raffle
                  : participation,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("Settings sheet", () => {
  it("holds CWL capture and FWA Rep accounts, and no disclosure", async () => {
    await open();
    const sections = [
      ...document.querySelectorAll(".results-settings-section h3"),
    ].map((node) => node.textContent);
    expect(sections).toEqual([
      "CWL capture",
      "Sit-out after a win",
      "FWA Rep accounts",
    ]);
    expect(document.querySelector("dialog.results-settings")).not.toBeNull();
    expect(document.querySelector("details")).toBeNull();
    expect(month().value).toBe("2026-11");
    expect(writes()).toHaveLength(0);
  });
  it("shows only the section a user can use", async () => {
    await open({ canOdds: false });
    expect(
      document.querySelector('[aria-label="FWA Rep accounts"]'),
    ).toBeNull();
    expect(
      api.mock.calls.some((call) => String(call[0]).includes("bonus-raffle")),
    ).toBe(false);
    await act(async () => root.render(<></>));
    await open({ canCapture: false });
    expect(document.querySelector('[aria-label="CWL capture"]')).toBeNull();
    expect(
      document.querySelector('[aria-label="FWA Rep accounts"]'),
    ).not.toBeNull();
    expect(
      api.mock.calls.filter((call) =>
        String(call[0]).endsWith("/participation"),
      ),
    ).toHaveLength(1);
  });
  it("saves capture settings with the revision it loaded", async () => {
    await open();
    expect(document.querySelector(".results-settings-actions")).toBeNull();
    await type(month(), "2026-12");
    await act(async () =>
      document
        .querySelector<HTMLInputElement>('input[name="capture-enabled"]')!
        .click(),
    );
    expect(onDirty).toHaveBeenLastCalledWith(true);
    await act(async () => button("Save capture settings").click());
    expect(writes()).toEqual([
      [
        "/seasons/1/participation/sync-settings",
        "POST",
        {
          cycle: "2026-12",
          enabled: true,
          expected_updated_at: "2026-11-01T00:00:00Z",
        },
      ],
    ]);
    expect(onSaved).toHaveBeenCalledExactlyOnceWith({
      kind: "capture",
      cycleChanged: true,
      enabled: true,
    });
    expect(onDirty).toHaveBeenLastCalledWith(false);
  });
  it("groups FWA Rep accounts by Discord user with notes, unlinked last", async () => {
    await open();
    const groups = [...document.querySelectorAll(".rep-accounts-group")].map(
      (group) => ({
        head: group.querySelector("header small")?.textContent,
        rows: [...group.querySelectorAll(".rep-account-row strong")].map(
          (node) => node.textContent,
        ),
      }),
    );
    expect(groups).toEqual([
      { head: "2 accounts", rows: ["Alpha", "Charlie"] },
      { head: "1 account", rows: ["Bravo"] },
    ]);
    expect(
      document.querySelector(".rep-accounts-group header")?.textContent,
    ).toContain("Ruggie");
    expect(
      document.querySelectorAll(".rep-accounts-group")[1].textContent,
    ).toContain("Not linked");
    expect(document.querySelector(".rep-account-note")?.textContent).toBe(
      "REP for Edrag Rush/420",
    );
    expect(
      api.mock.calls.filter((call) =>
        String(call[0]).startsWith("/staff-signup-members"),
      ),
    ).toEqual([["/staff-signup-members?ids=111111111111111111"]]);
    expect(writes()).toHaveLength(0);
  });
  it("finds a Clan Rep, shows their accounts and adds one for x2", async () => {
    await open();
    expect(document.body.textContent).toContain("Find Clan Rep (x2 odds)");
    await pickOption(
      pickerByLabel(document.body, "Find Clan Rep (x2 odds)"),
      "Ruggie",
    );
    await settle();
    expect(
      api.mock.calls.some(
        (call) =>
          call[0] ===
          "/seasons/1/staff-signups/accounts?user_id=111111111111111111",
      ),
    ).toBe(true);
    const finder = document.querySelector(".rep-finder")!;
    // Already listed: no add control, the x2 status shows instead.
    expect(finder.textContent).toContain("x2 · Listed");
    expect(button("Add for x2", finder)).toBeDefined();
    expect(
      [...finder.querySelectorAll("button")].filter(
        (node) => node.textContent === "Add for x2",
      ),
    ).toHaveLength(1);
    await type(
      finder.querySelector<HTMLInputElement>('input[name="rep-finder-note"]')!,
      "REP for Edrag Rush",
    );
    expect(onDirty).toHaveBeenLastCalledWith(true);
    await act(async () => button("Add for x2", finder).click());
    expect(writes()).toEqual([
      [
        "/seasons/1/bonus-raffle/rep-accounts",
        "POST",
        { tag: "#V2Y", note: "REP for Edrag Rush", revision: 7 },
      ],
    ]);
    expect(onDirty).toHaveBeenLastCalledWith(false);
  });
  it("adds an account by tag with a note and the draw revision it loaded", async () => {
    await open();
    const add = button("Add account");
    expect(add.disabled).toBe(true);
    await type(
      document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
      " #V2Y ",
    );
    await type(
      document.querySelector<HTMLInputElement>('input[name="rep-note"]')!,
      "REP for Edrag Rush ",
    );
    expect(onDirty).toHaveBeenLastCalledWith(true);
    await act(async () => add.click());
    expect(writes()).toEqual([
      [
        "/seasons/1/bonus-raffle/rep-accounts",
        "POST",
        { tag: "#V2Y", note: "REP for Edrag Rush", revision: 7 },
      ],
    ]);
    expect(onSaved).toHaveBeenCalledExactlyOnceWith({ kind: "odds" });
    expect(
      document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
    ).toBe("");
    expect(document.body.textContent).toContain("No FWA Rep accounts");
    expect(onDirty).toHaveBeenLastCalledWith(false);
  });
  it("edits a note and removes an account only after confirmation", async () => {
    await open();
    await act(async () => button("Edit note").click());
    const input = document.querySelector<HTMLInputElement>(
      'input[name="rep-edit-note"]',
    )!;
    expect(input.value).toBe("REP for Edrag Rush/420");
    expect(button("Save note").disabled).toBe(true);
    await type(input, "REP for Edrag Rush");
    await act(async () => button("Save note").click());
    expect(writes()).toEqual([
      [
        "/seasons/1/bonus-raffle/rep-accounts",
        "PATCH",
        {
          tag: "#P2Y",
          note: "REP for Edrag Rush",
          rep_revision: 1,
          revision: 7,
        },
      ],
    ]);
    api.mockClear();
    await act(async () => root.render(<></>));
    await open();
    await act(async () => button("Remove").click());
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog.textContent).toContain("Remove Alpha (#P2Y)?");
    await act(async () => button("Cancel", dialog).click());
    expect(writes()).toHaveLength(0);
    await act(async () => button("Remove").click());
    await act(async () =>
      button(
        "Remove account",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    expect(writes()).toEqual([
      [
        "/seasons/1/bonus-raffle/rep-accounts",
        "DELETE",
        { tag: "#P2Y", rep_revision: 1, revision: 7 },
      ],
    ]);
  });
  it("shows a list conflict, reloads the list and keeps the typed tag", async () => {
    await open();
    await type(
      document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
      "#V2Y",
    );
    api.mockImplementation(async (route: string, method?: string) => {
      if (method === "POST")
        throw new ApiError("This account is already an FWA Rep account", 409);
      return route.endsWith("/bonus-raffle")
        ? raffle
        : route.startsWith("/staff")
          ? members
          : participation;
    });
    await act(async () => button("Add account").click());
    await settle();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "already an FWA Rep account",
    );
    expect(
      document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
    ).toBe("#V2Y");
    expect(writes()).toHaveLength(1);
    expect(onSaved).not.toHaveBeenCalled();
  });
  it("blocks a second save while one is running", async () => {
    await open();
    await type(month(), "2026-12");
    let release!: (value: object) => void;
    api.mockImplementation(
      (route: string) =>
        new Promise((resolve) => {
          if (route.endsWith("/sync-settings")) release = resolve;
        }),
    );
    await act(async () => {
      button("Save capture settings").click();
      button("Save capture settings").click();
    });
    expect(writes()).toHaveLength(1);
    await act(async () => release({ sync }));
  });
  it("shows a revision conflict, reloads and writes nothing more", async () => {
    await open();
    await type(month(), "2026-12");
    api.mockImplementation(async (_route: string, method?: string) => {
      if (method === "POST")
        throw new ApiError("Settings changed elsewhere. Refresh.", 409);
      return participation;
    });
    await act(async () => button("Save capture settings").click());
    await settle();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "Settings changed elsewhere",
    );
    expect(writes()).toHaveLength(1);
    expect(onSaved).not.toHaveBeenCalled();
  });
  it("asks before closing with unsaved edits and closes at once without", async () => {
    await open();
    await act(async () => button("Close").click());
    expect(onClose).toHaveBeenCalledTimes(1);
    onClose.mockReset();
    await type(month(), "2026-12");
    await act(async () => button("Close").click());
    expect(onClose).not.toHaveBeenCalled();
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog.textContent).toContain("Discard unsaved settings?");
    await act(async () => button("Cancel", dialog).click());
    expect(onClose).not.toHaveBeenCalled();
    expect(month().value).toBe("2026-12");
    await act(async () => button("Close").click());
    await act(async () =>
      button(
        "Discard settings",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(writes()).toHaveLength(0);
  });
  it("Escape closes through the same guard", async () => {
    await open();
    await type(month(), "2026-12");
    const panel = document.querySelector("dialog.results-settings")!;
    await act(async () => {
      panel.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  });
  it("confirms a CWL month change that discards result edits, once", async () => {
    await open({ dirtyResults: 2 });
    await type(month(), "2026-12");
    await act(async () => {
      button("Save capture settings").click();
      button("Save capture settings").click();
    });
    expect(writes()).toHaveLength(0);
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "unsaved result edits for 2 accounts",
    );
    await act(async () => {
      const confirm = button(
        "Change CWL month",
        document.querySelector(".confirm-dialog")!,
      );
      confirm.click();
      confirm.click();
    });
    expect(writes()).toHaveLength(1);
  });
  it("is read only for an archived season", async () => {
    await open({ archived: true });
    expect(month().disabled).toBe(true);
    expect(button("Add account").disabled).toBe(true);
    expect(button("Remove").disabled).toBe(true);
    expect(document.body.textContent).toContain("Read only");
  });
});

it("shows one sit-out row per Lazy clan and saves only through its explicit button and bonus revision", async () => {
  api.mockImplementation(async (route: string) => {
    if (route.endsWith("/bonus-raffle/policy"))
      return {
        ...raffle,
        revision: 8,
        sit_out_settings: [{ tag: "#C2Y", name: "Lazy fixture", months: 2 }],
      };
    if (route.endsWith("/bonus-raffle"))
      return {
        ...raffle,
        sit_out_settings: [{ tag: "#C2Y", name: "Lazy fixture", months: 3 }],
      };
    return route.includes("participation") ? participation : members;
  });
  await open();
  const select = document.querySelector<HTMLSelectElement>(
    'select[name="sit-out-#C2Y"]',
  )!;
  expect(select.value).toBe("3");
  expect([...select.options].map((item) => item.textContent)).toEqual([
    "None",
    "1 month",
    "2 months",
    "3 months",
    "4 months",
    "5 months",
    "6 months",
  ]);
  await act(async () => {
    select.value = "2";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(writes()).toHaveLength(0);
  await act(async () => {
    button("Save Lazy fixture").click();
    button("Save Lazy fixture").click();
  });
  expect(writes()).toEqual([
    [
      "/seasons/1/bonus-raffle/policy",
      "PATCH",
      { clan_tag: "#C2Y", sit_out_months: 2, revision: 7 },
    ],
  ]);
  expect(select.value).toBe("2");
});
