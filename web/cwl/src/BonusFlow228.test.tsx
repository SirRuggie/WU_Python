// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
const permission = vi.hoisted(() => ({ value: true }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => permission.value,
}));
import BonusWorkspace from "./BonusWorkspace";
import { pickerByLabel, pickOption } from "./searchPickerTestUtils";
import {
  bonusReviewBlockers,
  reviewBlocked,
  type BonusReviewGuard,
} from "./bonusRaffle";

const INACTIVE = "Hosting clan is no longer an active Lazy clan in this season";
const account = (tag: string, name: string, clan: string, patch = {}) => ({
  tag,
  player_name: name,
  pool: "lazy",
  assigned_clan_tag: clan,
  assigned_clan_name: clan === "#2YQ" ? "Lazy One" : "Lazy Two",
  town_hall: 16,
  attacks: 4,
  stars: 9,
  source_status: "complete",
  source_complete: true,
  representative_status: "verified",
  ...patch,
});
const base = {
  season_status: "draft",
  cycle: "2026-11",
  revision: 1,
  policies: { main: 3, lazy: null },
  policy: {},
  clans: [
    { tag: "#2YQ", name: "Lazy One", slots: null },
    { tag: "#8QQ", name: "Lazy Two", slots: null },
  ],
  lazy_hosts: [
    { tag: "#2YQ", name: "Lazy One", slots: null },
    { tag: "#8QQ", name: "Lazy Two", slots: null },
  ],
  accounts: [
    account("#P1", "Alpha", "#2YQ"),
    account("#P2", "Bravo", "#2YQ", {
      attacks: 3,
      stars: 7,
      exclusion:
        "Does not meet the Lazy CWL participation rule; Missed CWL sync",
    }),
    account("#P3", "Charlie", "#8QQ"),
  ],
  draws: [],
  history: [],
  cycle_confirmed: [],
  active_other_cycles: [],
  sync: { enabled: true, warning: null, last_checked_at: null },
  publication_version: 1,
};
const status = {
  season_id: 1,
  cycle: "2026-11",
  archived: false,
  main_minimum: 3,
  pools: {
    main: [],
    lazy: [
      {
        tag: "#2YQ",
        name: "Lazy One",
        active: true,
        candidates: 8,
        meets_rule: 5,
        results_state: "captured",
        allowance_ready: false,
        draw_state: "none",
      },
      {
        tag: "#8QQ",
        name: "Lazy Two",
        active: true,
        candidates: 3,
        meets_rule: 3,
        results_state: "captured",
        allowance_ready: true,
        draw_state: "saved",
      },
    ],
  },
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const urlState = vi.fn();
const results = vi.fn();
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
async function mount(data: object = base, state = "pool=lazy") {
  api
    .mockReset()
    .mockImplementation((route: string) =>
      Promise.resolve(route.endsWith("/bonus-status") ? status : data),
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <BonusWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
        urlState={state}
        onUrlState={urlState}
        onResults={results}
      />,
    ),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  permission.value = true;
  urlState.mockReset();
  results.mockReset();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const cards = () => [
  ...host.querySelectorAll<HTMLButtonElement>(".bonus-clan-card"),
];
const typeCount = async (value: string) => {
  const input = host.querySelector<HTMLInputElement>(
    ".bonus-inline-count input",
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const review = () => button("Review eligibility");
const blockerText = () =>
  [...host.querySelectorAll(".bonus-blockers li")].map(
    (item) => item.textContent,
  );

describe("Bonus page loading", () => {
  it("renders the candidate list while the status request is pending", async () => {
    let release!: (value: object) => void;
    const held = new Promise<object>((resolve) => (release = resolve));
    api
      .mockReset()
      .mockImplementation((route: string) =>
        route.endsWith("/bonus-status") ? held : Promise.resolve(base),
      );
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () =>
      root.render(
        <BonusWorkspace
          seasonId="1"
          seasons={[
            { id: 1, label: "November", status: "draft", signup_open: true },
          ]}
          onSeasonChange={() => {}}
          urlState="pool=lazy"
          onUrlState={urlState}
          onResults={results}
        />,
      ),
    );
    expect(host.textContent).toContain("Alpha");
    expect(cards().map((card) => card.textContent)).not.toContain(
      "Lazy One5 of 8 meet · Draft",
    );
    await act(async () => release(status));
    expect(cards().map((card) => card.textContent)).toContain(
      "Lazy One5 of 8 meet · Draft",
    );
  });
});

describe("Bonus clan cards", () => {
  it("show name, meet count and state from the status read", async () => {
    await mount();
    expect(cards().map((card) => card.textContent)).toEqual([
      "Lazy One5 of 8 meet · Draft",
      "Lazy Two3 of 3 meet · Saved",
    ]);
    expect(cards()[0].getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector(".bonus-clan-search")).toBeNull();
    expect(
      host.querySelector(
        '[role="menuitem"], .bonus-controls .roster-menu-trigger',
      ),
    ).toBeNull();
  });
  it("select with the unsaved-change guard and never write", async () => {
    await mount();
    await act(async () => cards()[0].click());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(urlState).not.toHaveBeenCalled();
    await typeCount("4");
    await act(async () => cards()[1].click());
    expect(document.querySelector(".confirm-dialog")).not.toBeNull();
    await act(async () =>
      button("Cancel", document.querySelector(".confirm-dialog")!).click(),
    );
    expect(cards()[0].getAttribute("aria-pressed")).toBe("true");
    expect(
      host.querySelector<HTMLInputElement>(".bonus-inline-count input")!.value,
    ).toBe("4");
    await act(async () => cards()[1].click());
    await act(async () =>
      button(
        "Discard bonus edits",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    expect(cards()[1].getAttribute("aria-pressed")).toBe("true");
    expect(urlState).toHaveBeenLastCalledWith("pool=lazy&clan=%238QQ", true);
    expect(writes()).toHaveLength(0);
  });
  it("restores the clan from the URL", async () => {
    await mount(base, "pool=lazy&clan=%238QQ&step=draw");
    expect(cards()[1].getAttribute("aria-pressed")).toBe("true");
  });
});

describe("Review eligibility blockers", () => {
  const ready: BonusReviewGuard = {
    canManage: true,
    archived: false,
    policyDirty: false,
    roleDirty: false,
    reviewDirty: false,
    candidateOpen: false,
    countReady: true,
    needsMinimum: false,
    rolesUnavailable: false,
    resultsMissing: false,
  };
  it("has one line for every disabled condition and none when ready", () => {
    expect(bonusReviewBlockers(ready)).toEqual([]);
    const lines: Record<string, string> = {};
    const blocking: Record<string, boolean> = {};
    for (const key of Object.keys(ready) as (keyof BonusReviewGuard)[]) {
      const value = key === "canManage" || key === "countReady" ? false : true;
      const blockers = bonusReviewBlockers({ ...ready, [key]: value });
      expect(blockers, key).toHaveLength(1);
      lines[key] = blockers[0].text;
      blocking[key] = reviewBlocked(blockers);
    }
    // Exactly today's disabled conditions block; Discord and Results only inform.
    expect(blocking).toEqual({
      canManage: true,
      archived: true,
      policyDirty: true,
      roleDirty: true,
      reviewDirty: true,
      candidateOpen: true,
      countReady: true,
      needsMinimum: true,
      rolesUnavailable: false,
      resultsMissing: false,
    });
    expect(lines).toEqual({
      canManage: "Bonus access needed",
      archived: "Archived season · read only",
      policyDirty: "Save the minimum",
      roleDirty: "Save the representative role",
      reviewDirty: "Save the open review",
      candidateOpen: "Save the open review",
      countReady: "Enter the bonus count",
      needsMinimum: "Set the Main minimum",
      rolesUnavailable: "Discord roles unavailable · Retry",
      resultsMissing: "Results not captured",
    });
  });
  it("shows the lines under the disabled button and clears them with the inline count", async () => {
    await mount();
    expect(review().disabled).toBe(true);
    expect(blockerText()).toEqual(["Enter the bonus count"]);
    expect(
      host.querySelector(".bonus-stats .bonus-inline-count"),
    ).not.toBeNull();
    await typeCount("51");
    expect(review().disabled).toBe(true);
    await typeCount("5");
    expect(blockerText()).toEqual([]);
    expect(review().disabled).toBe(false);
    expect(writes()).toHaveLength(0);
  });
  it("shows Discord, Results and open-review blockers with their fixes", async () => {
    await mount({
      ...base,
      accounts: [
        account("#P1", "Alpha", "#2YQ", {
          representative_status: "unavailable",
          attacks: null,
          source_complete: false,
        }),
        account("#P2", "Bravo", "#2YQ", {
          attacks: null,
          source_complete: false,
        }),
      ],
    });
    expect(blockerText()).toEqual([
      "Enter the bonus count",
      "Discord roles unavailable · Retry",
      "Results not captured",
    ]);
    expect(review().disabled).toBe(true);
    // With the count entered, Discord and Results lines stay but never disable.
    await typeCount("5");
    expect(blockerText()).toEqual([
      "Discord roles unavailable · Retry",
      "Results not captured",
    ]);
    expect(review().disabled).toBe(false);
    expect(writes()).toHaveLength(0);
    await act(async () => button("Add player by tag").click());
    expect(review().disabled).toBe(true);
    expect(blockerText()).toContain("Save the open review");
    const resultsLink =
      host.querySelector<HTMLAnchorElement>(".bonus-blockers a")!;
    expect(resultsLink.getAttribute("href")).toBe(
      "/cwl/results?season=1&pool=lazy&clan=%232YQ",
    );
  });
  it("shows Set the Main minimum on Main with no saved minimum", async () => {
    await mount(
      {
        ...base,
        policies: { main: null, lazy: null },
        accounts: [account("#P9", "Main player", "#2YQ", { pool: "main" })],
        allowances: {
          "#2YQ": {
            status: "ready",
            total: 6,
            base: 4,
            wins: 2,
            completed_wars: 7,
            rounds: 7,
            league: "Crystal League I",
            team_size: 15,
            reason: "",
            rules_version: "1",
          },
        },
      },
      "pool=main",
    );
    expect(blockerText()).toEqual(["Set the Main minimum"]);
    expect(review().disabled).toBe(true);
  });
  it("shows the inline count field only when the league was not captured", async () => {
    await mount({
      ...base,
      allowances: {
        "#2YQ": {
          status: "ready",
          total: 6,
          base: 4,
          wins: 2,
          completed_wars: 7,
          rounds: 7,
          league: "Crystal League I",
          team_size: 15,
          reason: "",
          rules_version: "1",
        },
      },
    });
    expect(host.querySelector(".bonus-inline-count")).toBeNull();
    expect(review().disabled).toBe(false);
  });
});

describe("clan notice", () => {
  it("shows a clan-wide reason once and keeps rows to player reasons", async () => {
    await mount({
      ...base,
      accounts: [
        account("#P1", "Alpha", "#2YQ", { exclusion: INACTIVE }),
        account("#P2", "Bravo", "#2YQ", {
          attacks: 3,
          stars: 7,
          exclusion: INACTIVE,
        }),
      ],
    });
    const text = host.textContent || "";
    expect(
      text.split("Hosting clan is not an active Lazy clan this season"),
    ).toHaveLength(2);
    expect(text).not.toContain(INACTIVE);
    const rows = [...host.querySelectorAll(".bonus-account-list li")];
    expect(
      rows.map((row) => row.querySelector(".roster-ui-status")?.textContent),
    ).toEqual(["Meets rule", "Below rule"]);
  });
  it("rows show short player reasons next to the chip", async () => {
    await mount();
    const bravo = [...host.querySelectorAll(".bonus-account-list li")].find(
      (row) => row.textContent?.includes("Bravo"),
    )!;
    expect(bravo.querySelector(".roster-ui-status")?.textContent).toBe(
      "Below rule",
    );
    expect(bravo.querySelector(".bonus-account-reason")?.textContent).toBe(
      "Missed sync",
    );
  });
});

it("the step bar opens Results with the pool and clan", async () => {
  await mount();
  const link = host.querySelector<HTMLAnchorElement>(".bonus-step-list a")!;
  expect(link.getAttribute("href")).toBe(
    "/cwl/results?season=1&pool=lazy&clan=%232YQ",
  );
  await act(async () => link.click());
  expect(results).toHaveBeenCalledExactlyOnceWith("pool=lazy&clan=%232YQ");
  expect(host.querySelector(".bonus-steps")).toBeNull();
});

describe("phone layout", () => {
  const trigger = () =>
    host.querySelector<HTMLButtonElement>(
      ".bonus-context .roster-action-trigger",
    )!;
  // Label → disabled for each item of the open ⋯ menu, then closes it.
  const menuItems = async () => {
    await act(async () => trigger().click());
    const items = Object.fromEntries(
      [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].map(
        (item) => [
          item.textContent?.trim(),
          item.getAttribute("aria-disabled") === "true",
        ],
      ),
    );
    await act(async () => trigger().click());
    return items;
  };
  const select = async (label: string) => {
    await act(async () => trigger().click());
    const item = [
      ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ].find((node) => node.textContent?.trim() === label)!;
    await act(async () => {
      item.dispatchEvent(
        new MouseEvent("mousedown", { bubbles: true, button: 0 }),
      );
      item.dispatchEvent(
        new MouseEvent("mouseup", { bubbles: true, button: 0 }),
      );
      item.click();
    });
  };
  const type = async (input: HTMLInputElement, value: string) =>
    act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  const never = () => new Promise(() => {});
  const reads = () =>
    api.mock.calls.filter((call) => call[0] === "/seasons/1/bonus-raffle")
      .length;
  it("the month line ⋯ menu holds both refresh actions", async () => {
    await mount();
    expect(host.querySelector(".bonus-context p")?.textContent).toBe(
      "November 2026 · Clash not checked yet",
    );
    expect(host.querySelector(".bonus-controls")).toBeNull();
    expect(button("Refresh attacks from Clash", host)).toBeUndefined();
    expect(await menuItems()).toEqual({
      Refresh: false,
      "Refresh attacks from Clash": false,
    });
    expect(writes()).toHaveLength(0);
  });
  // Each of the nine existing conditions; Refresh itself waits only on work.
  it.each([
    [
      "no bonus access",
      async () => {
        permission.value = false;
        await mount();
      },
    ],
    ["archived season", () => mount({ ...base, season_status: "archived" })],
    ["no CWL month", () => mount({ ...base, cycle: null })],
    [
      "open candidate editor",
      async () => {
        await mount();
        await act(async () => button("Add player by tag").click());
      },
    ],
    [
      "player lookup running",
      async () => {
        await mount();
        await act(async () => button("Add player by tag").click());
        await type(
          host.querySelector<HTMLInputElement>('input[name="player-tag"]')!,
          "#P9",
        );
        api.mockImplementation(never);
        await act(async () => button("Find player").click());
      },
    ],
    [
      "request running",
      async () => {
        await mount();
        api.mockImplementation(never);
        await select("Refresh attacks from Clash");
      },
    ],
    [
      "unsaved Main minimum",
      async () => {
        await mount(
          {
            ...base,
            accounts: [account("#P9", "Main player", "#2YQ", { pool: "main" })],
          },
          "pool=main",
        );
        await type(
          host.querySelector<HTMLInputElement>(
            'input[name="minimum-attacks"]',
          )!,
          "4",
        );
      },
    ],
    [
      "unsaved representative role",
      async () => {
        await mount();
        const roles = { roles: [{ id: "111111111111111111", name: "Rep" }] };
        api.mockImplementation((route: string) =>
          Promise.resolve(route === "/announcement-roles" ? roles : base),
        );
        const details = [...host.querySelectorAll("details")].find((item) =>
          item.textContent?.startsWith("FWA Rep odds settings"),
        )!;
        await act(async () => {
          details.open = true;
          details.dispatchEvent(new Event("toggle"));
        });
        await pickOption(pickerByLabel(host, "Representative role"), "Rep");
      },
    ],
    [
      "unsaved account review",
      async () => {
        Element.prototype.scrollIntoView ||= () => {};
        await mount();
        await act(async () => button("Review Alpha").click());
        await act(async () =>
          host
            .querySelector<HTMLInputElement>(
              '.bonus-review-editor input[type="checkbox"]',
            )!
            .click(),
        );
      },
    ],
  ] as const)("%s disables Refresh attacks from Clash", async (name, setup) => {
    await setup();
    expect(await menuItems()).toEqual({
      Refresh: name === "player lookup running" || name === "request running",
      "Refresh attacks from Clash": true,
    });
  });
  it("a player lookup still running after the editor closes disables Refresh attacks from Clash", async () => {
    await mount();
    await act(async () => button("Add player by tag").click());
    await type(
      host.querySelector<HTMLInputElement>('input[name="player-tag"]')!,
      "#P9",
    );
    api.mockImplementation(never);
    await act(async () => button("Find player").click());
    // The toggle closes the editor; the lookup keeps running.
    await act(async () => button("Add player by tag").click());
    expect(host.querySelector(".bonus-add-candidate")).toBeNull();
    expect(await menuItems()).toEqual({
      Refresh: true,
      "Refresh attacks from Clash": true,
    });
  });
  it("Refresh attacks from Clash posts the existing check", async () => {
    await mount();
    await select("Refresh attacks from Clash");
    expect(writes()).toEqual([
      ["/seasons/1/bonus-raffle/refresh-results", "POST", {}],
    ]);
  });
  it("Refresh rereads once, behind the unsaved-change guard", async () => {
    await mount();
    const before = reads();
    await select("Refresh");
    expect(reads()).toBe(before + 1);
    await typeCount("4");
    await select("Refresh");
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog).not.toBeNull();
    await act(async () => button("Cancel", dialog).click());
    expect(reads()).toBe(before + 1);
    expect(
      host.querySelector<HTMLInputElement>(".bonus-inline-count input")!.value,
    ).toBe("4");
    await select("Refresh");
    await act(async () =>
      button(
        "Discard bonus edits",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    expect(reads()).toBe(before + 2);
    expect(writes()).toHaveLength(0);
  });
  it("orders the clan: notice, stats, list, review, rules, count, add, odds", async () => {
    await mount({
      ...base,
      accounts: [
        account("#P1", "Alpha", "#2YQ", {
          representative_status: "unavailable",
        }),
      ],
    });
    const flow = host.querySelector(".bonus-flow")!;
    const summary = (text: string) =>
      [...flow.querySelectorAll("summary")].find(
        (item) => item.textContent === text,
      )!;
    const sequence = [
      flow.querySelector(".bonus-clan-notice")!,
      flow.querySelector(".bonus-stats")!,
      flow.querySelector(".bonus-account-list")!,
      button("Review eligibility", flow),
      flow.querySelector(".bonus-blockers")!,
      [...flow.querySelectorAll(".bonus-support")].find((item) =>
        item.textContent?.startsWith("Bonus rules"),
      )!,
      summary("Bonus count and source"),
      button("Add player by tag", flow),
      summary("FWA Rep odds settings"),
    ];
    expect(sequence.every(Boolean)).toBe(true);
    for (let index = 1; index < sequence.length; index += 1)
      expect(
        sequence[index - 1].compareDocumentPosition(sequence[index]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
        String(index),
      ).toBeTruthy();
    expect(
      flow.querySelector(".bonus-clan-notice svg")?.getAttribute("aria-hidden"),
    ).toBe("true");
    expect(flow.querySelector(".bonus-clan-notice")?.textContent).toBe(
      "Discord roles unavailable · Retry",
    );
    // The shared amber notice, not a one-off colour.
    expect(flow.querySelector(".bonus-clan-notice")!.classList).toContain(
      "notice",
    );
  });
  it("reveals the selected card nearest in the clan strip", async () => {
    // A 300 px strip at 16 px; cards are 260 px wide and 280 px apart.
    const size = (name: string, value: number) =>
      Object.defineProperty(HTMLElement.prototype, name, {
        configurable: true,
        get(this: HTMLElement) {
          return this.classList.contains("bonus-clan-cards") ? value : 0;
        },
      });
    size("clientWidth", 300);
    size("scrollWidth", 820);
    const rect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        const strip = this.closest<HTMLElement>(".bonus-clan-cards");
        const left = this.classList.contains("bonus-clan-card")
          ? 16 + [...strip!.children].indexOf(this) * 280 - strip!.scrollLeft
          : 16;
        return { left, right: left + 260, top: 0, bottom: 0 } as DOMRect;
      });
    try {
      await mount(base, "pool=lazy&clan=%238QQ");
      expect(cards()[1].getAttribute("aria-pressed")).toBe("true");
      // Right edge aligned: the previous card keeps peeking at the left.
      expect(host.querySelector(".bonus-clan-cards")!.scrollLeft).toBe(240);
      await act(async () => cards()[0].click());
      expect(host.querySelector(".bonus-clan-cards")!.scrollLeft).toBe(0);
    } finally {
      rect.mockRestore();
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
      delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
    }
  });
});
