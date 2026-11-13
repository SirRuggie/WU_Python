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
  sit_out_settings: [
    { tag: "#C2Y", name: "Lazy One", months: 1 },
    { tag: "#Q2Y", name: "Lazy Two", months: 3 },
    { tag: "#L2Y", name: "Lazy Three", months: 2 },
  ],
  rep_accounts: [
    rep("#P2Y", "Alpha", "111111111111111111", "REP for Edrag Rush/420"),
    rep("#Q2Y", "Bravo", null),
    rep("#R2Y", "Charlie", "111111111111111111"),
  ],
};
const clanReps = {
  members: [
    { id: "111111111111111111", display_name: "Ruggie", username: "ruggie" },
    { id: "444444444444444444", display_name: "Edrag", username: "edrag" },
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
async function openAdd() {
  const section = document.querySelector<HTMLDetailsElement>(
    'details[aria-label="FWA Rep accounts"]',
  )!;
  await act(async () => {
    section.open = true;
    button("Add account").click();
  });
  await settle();
  const byTag = document.querySelector<HTMLDetailsElement>(".rep-add-by-tag")!;
  await act(async () => {
    byTag.open = true;
    byTag.dispatchEvent(new Event("toggle"));
  });
}
async function rowAction(label: string, name = "Alpha") {
  document.querySelector<HTMLDetailsElement>(
    'details[aria-label="FWA Rep accounts"]',
  )!.open = true;
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>(`[aria-label="Actions for ${name}"]`)!
      .click(),
  );
  await act(async () =>
    [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')]
      .find((node) => node.textContent?.trim() === label)!
      .click(),
  );
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
            ? route.endsWith("111111111111111111")
              ? linked
              : { accounts: [linked.accounts[1]] }
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
  vi.restoreAllMocks();
});

describe("Settings sheet", () => {
  it("holds all three sections as closed disclosures with mounted content", async () => {
    await open();
    const sections = [
      ...document.querySelectorAll(".results-settings-title"),
    ].map((node) => node.textContent);
    expect(sections).toEqual([
      "CWL capture",
      "Sit-out after a win",
      "FWA Rep accounts",
    ]);
    expect(document.querySelector("dialog.results-settings")).not.toBeNull();
    expect(
      document.querySelectorAll("details.results-settings-section"),
    ).toHaveLength(3);
    expect(
      [
        ...document.querySelectorAll<HTMLDetailsElement>(
          "details.results-settings-section",
        ),
      ].every((node) => !node.open),
    ).toBe(true);
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
    // 1 account per member (237): a 2-account member shows the warning;
    // the unlinked group never does.
    const warnings = [...document.querySelectorAll(".rep-accounts-warning")];
    expect(warnings.map((node) => node.textContent)).toEqual([
      "Keep 1 account",
    ]);
    expect(document.querySelector(".rep-accounts > p")?.textContent).toBe(
      "1 account per member. It gets 2 chances in Lazy draws and no sit-out.",
    );
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
    await openAdd();
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
    // Already listed: no add control, the x2 status shows instead. The
    // member has a listed account, so the other one cannot be added (237 D1).
    expect(finder.textContent).toContain("x2 · Listed");
    expect(finder.textContent).toContain(
      "Member already has an FWA Rep account",
    );
    expect(
      [...finder.querySelectorAll("button")].filter(
        (node) => node.textContent === "Add for x2",
      ),
    ).toHaveLength(0);
    await pickOption(
      pickerByLabel(document.body, "Find Clan Rep (x2 odds)"),
      "Edrag",
    );
    await settle();
    expect(button("Add for x2", finder)).toBeDefined();
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
    await openAdd();
    const add = button("Add tag");
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
    await rowAction("Edit note");
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
    await rowAction("Remove");
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog.textContent).toContain("Remove Alpha (#P2Y)?");
    await act(async () => button("Cancel", dialog).click());
    expect(writes()).toHaveLength(0);
    await rowAction("Remove");
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
    await openAdd();
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
    await act(async () => button("Add tag").click());
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
    expect(
      document.querySelector<HTMLButtonElement>(
        '[aria-label="Actions for Alpha"]',
      )!.disabled,
    ).toBe(true);
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

const section = (name: string) =>
  document.querySelector<HTMLDetailsElement>(`details[aria-label="${name}"]`)!;
const summaryText = (name: string) =>
  section(name)
    .querySelector("summary")!
    .textContent?.replace(/\s+/g, " ")
    .trim();
const frame = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 40));
  });
const selectMonths = (tag: string, months: string) =>
  act(async () => {
    const input = document.querySelector<HTMLSelectElement>(
      `select[name="sit-out-${tag}"]`,
    )!;
    input.value = months;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
it("shows exact saved summaries, with no heading/button inside summary and no request on section toggles", async () => {
  await open();
  expect(summaryText("CWL capture")).toBe("CWL capture · Off · Nov 2026");
  expect(summaryText("Sit-out after a win")).toBe(
    "Sit-out after a win · 3 clans · 1–3 months",
  );
  expect(summaryText("FWA Rep accounts")).toBe("FWA Rep accounts · 3 accounts");
  const before = api.mock.calls.length;
  for (const node of document.querySelectorAll<HTMLDetailsElement>(
    "details.results-settings-section",
  )) {
    expect(node.open).toBe(false);
    expect(node.querySelector("summary h3, summary button")).toBeNull();
    await act(async () => {
      node.open = true;
      node.open = false;
    });
  }
  expect(api.mock.calls).toHaveLength(before);
  expect(writes()).toHaveLength(0);
});
it.each([
  { months: [], reps: [], sit: "No Lazy clans", rep: "None" },
  {
    months: [0],
    reps: [raffle.rep_accounts[0]],
    sit: "1 clan · None",
    rep: "1 account",
  },
  { months: [1], reps: [], sit: "1 clan · 1 month", rep: "None" },
  { months: [3, 3, 3], reps: [], sit: "3 clans · 3 months", rep: "None" },
])(
  "formats saved sit-out/account counts: $sit / $rep",
  async ({ months, reps, sit, rep }) => {
    const original = api.getMockImplementation()!;
    api.mockImplementation((route: string) =>
      route.endsWith("/bonus-raffle")
        ? Promise.resolve({
            ...raffle,
            sit_out_settings: months.map((n, i) => ({
              tag: `#P${i}`,
              name: `Clan ${i}`,
              months: n,
            })),
            rep_accounts: reps,
          })
        : original(route),
    );
    await open();
    expect(summaryText("Sit-out after a win")).toBe(
      `Sit-out after a win · ${sit}`,
    );
    expect(summaryText("FWA Rep accounts")).toBe(`FWA Rep accounts · ${rep}`);
  },
);
it.each([false, true])(
  "shows On/Off and Month not set from saved capture (enabled=%s)",
  async (enabled) => {
    const original = api.getMockImplementation()!;
    api.mockImplementation((route: string) =>
      route.endsWith("/participation")
        ? Promise.resolve({
            ...participation,
            sync: { ...sync, cycle: null, enabled },
          })
        : original(route),
    );
    await open();
    expect(summaryText("CWL capture")).toBe(
      `CWL capture · ${enabled ? "On" : "Off"} · Month not set`,
    );
  },
);
it("shows Loading then Not loaded, with capture Retry/odds Refresh above all closed sections", async () => {
  const pending: ((value: object) => void)[] = [];
  api.mockImplementation(() => new Promise((resolve) => pending.push(resolve)));
  await open();
  expect(summaryText("CWL capture")).toBe("CWL capture · Loading…");
  expect(summaryText("Sit-out after a win")).toBe(
    "Sit-out after a win · Loading…",
  );
  expect(summaryText("FWA Rep accounts")).toBe("FWA Rep accounts · Loading…");
  await act(async () => root.render(<></>));
  api.mockRejectedValue(new Error("Fixture read unavailable"));
  await open();
  for (const name of ["CWL capture", "Sit-out after a win", "FWA Rep accounts"])
    expect(summaryText(name)).toBe(`${name} · Not loaded`);
  const alerts = [...document.querySelectorAll('[role="alert"]')];
  expect(alerts).toHaveLength(2);
  for (const alert of alerts)
    expect(
      alert.compareDocumentPosition(section("CWL capture")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  expect(button("Retry")).toBeDefined();
  expect(button("Refresh")).toBeDefined();
  expect(
    [
      ...document.querySelectorAll<HTMLDetailsElement>(
        "details.results-settings-section",
      ),
    ].every((node) => !node.open),
  ).toBe(true);
});
it("switches native exclusive names with the680px media query and removes its listener on unmount", async () => {
  let listener: (() => void) | undefined;
  const media = {
    matches: true,
    addEventListener: vi.fn((_name, fn) => {
      listener = fn;
    }),
    removeEventListener: vi.fn(),
  };
  vi.spyOn(window, "matchMedia").mockReturnValue(
    media as unknown as MediaQueryList,
  );
  await open();
  expect(
    [...document.querySelectorAll("details.results-settings-section")].map(
      (node) => node.getAttribute("name"),
    ),
  ).toEqual(["results-settings", "results-settings", "results-settings"]);
  await act(async () => {
    media.matches = false;
    listener!();
  });
  expect(
    [...document.querySelectorAll("details.results-settings-section")].every(
      (node) => !node.hasAttribute("name"),
    ),
  ).toBe(true);
  await act(async () => root.render(<></>));
  expect(media.removeEventListener).toHaveBeenCalledWith("change", listener);
});
it("retains capture/sit-out/tag/note drafts through closed sections and names Unsaved using saved summary values", async () => {
  await open();
  await type(month(), "2026-12");
  await selectMonths("#C2Y", "6");
  await openAdd();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
    "#V2Y",
  );
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!,
    "Pending tag note",
  );
  for (const name of [
    "CWL capture",
    "Sit-out after a win",
    "FWA Rep accounts",
  ]) {
    await act(async () => {
      section(name).open = false;
      section(name).open = true;
    });
    expect(summaryText(name)).toContain(" · Unsaved");
  }
  expect(summaryText("CWL capture")).toBe(
    "CWL capture · Off · Nov 2026 · Unsaved",
  );
  expect(summaryText("Sit-out after a win")).toBe(
    "Sit-out after a win · 3 clans · 1–3 months · Unsaved",
  );
  expect(month().value).toBe("2026-12");
  expect(
    document.querySelector<HTMLSelectElement>('select[name="sit-out-#C2Y"]')!
      .value,
  ).toBe("6");
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
  ).toBe("#V2Y");
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!.value,
  ).toBe("Pending tag note");
  expect(document.querySelector(".rep-add-by-tag summary")?.textContent).toBe(
    "Add by player tag · Unsaved",
  );
  expect(writes()).toHaveLength(0);
  await act(async () => button("Close").click());
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved settings?",
  );
});
it("places unique primary Add account above the list; Cancel clears both forms/finder, returns focus and clears only its own dirty ownership", async () => {
  await open();
  const add = button("Add account");
  expect(
    [...document.querySelectorAll("button")].filter(
      (node) => node.textContent?.trim() === "Add account",
    ),
  ).toHaveLength(1);
  expect(add.classList.contains("is-primary")).toBe(true);
  expect(add.getAttribute("aria-expanded")).toBe("false");
  expect(
    add.compareDocumentPosition(document.querySelector(".rep-accounts-list")!) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  section("FWA Rep accounts").open = true;
  await act(async () => add.click());
  await frame();
  expect(
    document.getElementById(add.getAttribute("aria-controls")!),
  ).not.toBeNull();
  expect(
    document.querySelector<HTMLDetailsElement>(".rep-add-by-tag")!.open,
  ).toBe(false);
  expect(
    document.querySelector(".rep-finder")!.contains(document.activeElement),
  ).toBe(true);
  await pickOption(
    pickerByLabel(document.body, "Find Clan Rep (x2 odds)"),
    "Ruggie",
  );
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-finder-note"]')!,
    "Finder draft",
  );
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
    "#V2Y",
  );
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!,
    "Tag draft",
  );
  await act(async () =>
    button("Cancel", document.querySelector(".rep-add-area")!).click(),
  );
  await frame();
  expect(add.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(add);
  expect(onDirty).toHaveBeenLastCalledWith(false);
  expect(writes()).toHaveLength(0);
  await act(async () => add.click());
  await frame();
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
  ).toBe("");
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!.value,
  ).toBe("");
  expect(document.querySelector('input[name="rep-finder-note"]')).toBeNull();
  expect(
    pickerByLabel(document.body, "Find Clan Rep (x2 odds)").textContent,
  ).toContain("Select a Clan Rep");
});
it("automatically opens Add by player tag for a selected Rep with no linked accounts", async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation((route: string) =>
    route.includes("/staff-signups/accounts?")
      ? Promise.resolve({ accounts: [] })
      : original(route),
  );
  await open();
  section("FWA Rep accounts").open = true;
  await act(async () => button("Add account").click());
  await settle();
  await pickOption(
    pickerByLabel(document.body, "Find Clan Rep (x2 odds)"),
    "Ruggie",
  );
  await settle();
  expect(
    document.querySelector<HTMLDetailsElement>(".rep-add-by-tag")!.open,
  ).toBe(true);
  expect(writes()).toHaveLength(0);
});
it("successful tag add keeps the area open and retains another section's actual dirty guard", async () => {
  await open();
  await type(month(), "2026-12");
  await selectMonths("#C2Y", "6");
  await openAdd();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
    "#V2Y",
  );
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!,
    "New note",
  );
  await act(async () => button("Add tag").click());
  expect(button("Add account").getAttribute("aria-expanded")).toBe("true");
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
  ).toBe("");
  expect(
    document.querySelector<HTMLSelectElement>('select[name="sit-out-#C2Y"]')!
      .value,
  ).toBe("6");
  expect(month().value).toBe("2026-12");
  expect(summaryText("Sit-out after a win")).toContain("Unsaved");
  await act(async () =>
    button("Cancel", document.querySelector(".rep-add-area")!).click(),
  );
  await act(async () => button("Close").click());
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved settings?",
  );
  expect(writes()).toHaveLength(1);
});
it("row menus portal inside the dialog; Edit note focuses input and disables other edits, then Cancel returns row focus", async () => {
  await open();
  section("FWA Rep accounts").open = true;
  const trigger = document.querySelector<HTMLButtonElement>(
    '[aria-label="Actions for Alpha"]',
  )!;
  await act(async () => trigger.click());
  const menu = document.querySelector('[role="menu"]')!;
  expect(
    document.querySelector("dialog.results-settings")!.contains(menu),
  ).toBe(true);
  expect(
    [...menu.querySelectorAll('[role="menuitem"]')].map((node) =>
      node.textContent?.trim(),
    ),
  ).toEqual(["Edit note", "Remove"]);
  expect(menu.querySelector('[role="separator"]')).not.toBeNull();
  expect(menu.querySelector(".roster-action-danger")?.textContent).toBe(
    "Remove",
  );
  await act(async () =>
    [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]')][0].click(),
  );
  await frame();
  const input = document.querySelector<HTMLInputElement>(
    'input[name="rep-edit-note"]',
  )!;
  expect(document.activeElement).toBe(input);
  await type(input, "Dirty inline note");
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('[aria-label="Actions for Charlie"]')!
      .click(),
  );
  expect(
    [...document.querySelectorAll('[role="menuitem"]')]
      .find((node) => node.textContent?.trim() === "Edit note")
      ?.getAttribute("aria-disabled"),
  ).toBe("true");
  await act(async () =>
    document
      .querySelector('[role="menu"]')!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
  );
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(
    document.querySelector<HTMLDialogElement>("dialog.results-settings")!.open,
  ).toBe(true);
  await act(async () =>
    button("Cancel", document.querySelector(".rep-account-note-edit")!).click(),
  );
  await frame();
  expect(document.activeElement).toBe(trigger);
  expect(writes()).toHaveLength(0);
});
it("first Escape closes only a row menu; second native cancel reaches the dirty sheet discard guard", async () => {
  await open();
  await type(month(), "2026-12");
  section("FWA Rep accounts").open = true;
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('[aria-label="Actions for Alpha"]')!
      .click(),
  );
  await act(async () =>
    document
      .querySelector('[role="menu"]')!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
  );
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(onClose).not.toHaveBeenCalled();
  await act(async () =>
    document
      .querySelector("dialog.results-settings")!
      .dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved settings?",
  );
  expect(writes()).toHaveLength(0);
});
it("Cancel in Add preserves an inline note draft and the real sheet dirty guard", async () => {
  await open();
  await rowAction("Edit note");
  await frame();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-edit-note"]')!,
    "Dirty note",
  );
  await openAdd();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
    "#V2Y",
  );
  await act(async () =>
    button("Cancel", document.querySelector(".rep-add-area")!).click(),
  );
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-edit-note"]')!
      .value,
  ).toBe("Dirty note");
  expect(summaryText("FWA Rep accounts")).toContain("Unsaved");
  await act(async () => button("Close").click());
  expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  expect(writes()).toHaveLength(0);
});
it("successful remove focuses the next grouped row menu", async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation((route: string, method?: string) =>
    route.endsWith("/rep-accounts") && method === "DELETE"
      ? Promise.resolve({
          ...raffle,
          revision: 8,
          rep_accounts: raffle.rep_accounts.slice(1),
        })
      : original(route, method),
  );
  await open();
  await rowAction("Remove");
  await act(async () =>
    button(
      "Remove account",
      document.querySelector(".confirm-dialog")!,
    ).click(),
  );
  await frame();
  expect(document.activeElement).toBe(
    document.querySelector('[aria-label="Actions for Charlie"]'),
  );
  expect(writes()).toHaveLength(1);
});
it("saving a note restores that row menu focus without clearing a pending add form", async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation((route: string, method?: string) =>
    route.endsWith("/rep-accounts") && method === "PATCH"
      ? Promise.resolve({
          ...raffle,
          revision: 8,
          rep_accounts: raffle.rep_accounts.map((row) =>
            row.tag === "#P2Y"
              ? { ...row, note: "Updated note", revision: 2 }
              : row,
          ),
        })
      : original(route, method),
  );
  await open();
  await openAdd();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
    "#V2Y",
  );
  await rowAction("Edit note");
  await frame();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-edit-note"]')!,
    "Updated note",
  );
  await act(async () => button("Save note").click());
  await frame();
  expect(document.activeElement).toBe(
    document.querySelector('[aria-label="Actions for Alpha"]'),
  );
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
  ).toBe("#V2Y");
  expect(summaryText("FWA Rep accounts")).toContain("Unsaved");
  expect(writes()).toHaveLength(1);
});
it.each([
  { name: "Bravo", accounts: raffle.rep_accounts, target: "Charlie" },
  { name: "Alpha", accounts: [raffle.rep_accounts[0]], target: null },
])(
  "successful removal of $name focuses previous menu or Add account when no row remains",
  async ({ name, accounts, target }) => {
    const original = api.getMockImplementation()!;
    api.mockImplementation((route: string, method?: string) =>
      route.endsWith("/rep-accounts") && method === "DELETE"
        ? Promise.resolve({
            ...raffle,
            revision: 8,
            rep_accounts: accounts.filter((row) => row.player_name !== name),
          })
        : route.endsWith("/bonus-raffle")
          ? Promise.resolve({ ...raffle, rep_accounts: accounts })
          : original(route, method),
    );
    await open();
    await rowAction("Remove", name);
    await act(async () =>
      button(
        "Remove account",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    await frame();
    expect(document.activeElement).toBe(
      target
        ? document.querySelector(`[aria-label="Actions for ${target}"]`)
        : button("Add account"),
    );
    expect(writes()).toHaveLength(1);
  },
);
it("a successful finder add clears only its note and keeps the tag form/draft and Add area", async () => {
  await open();
  await openAdd();
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!,
    "#Q2Y",
  );
  await type(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!,
    "Other form draft",
  );
  await pickOption(
    pickerByLabel(document.body, "Find Clan Rep (x2 odds)"),
    "Edrag",
  );
  await settle();
  const finder = document.querySelector(".rep-finder")!;
  await type(
    finder.querySelector<HTMLInputElement>('input[name="rep-finder-note"]')!,
    "Finder note",
  );
  await act(async () => button("Add for x2", finder).click());
  expect(
    finder.querySelector<HTMLInputElement>('input[name="rep-finder-note"]')!
      .value,
  ).toBe("");
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-tag"]')!.value,
  ).toBe("#Q2Y");
  expect(
    document.querySelector<HTMLInputElement>('input[name="rep-note"]')!.value,
  ).toBe("Other form draft");
  expect(button("Add account").getAttribute("aria-expanded")).toBe("true");
  expect(summaryText("FWA Rep accounts")).toContain("Unsaved");
  expect(writes()).toHaveLength(1);
});
