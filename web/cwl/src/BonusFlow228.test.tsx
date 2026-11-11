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
import {
  bonusStepBlockers,
  reviewBlocked,
  type BonusBlockerLine,
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
const previewData = {
  allowance_source: "staff",
  cycle: "2026-11",
  pool: "lazy",
  clan_tag: "#2YQ",
  clan_name: "Lazy One",
  minimum: null,
  slots: 5,
  available: 5,
  confirmed: 0,
  eligible: [account("#P1", "Alpha", "#2YQ")],
  excluded: [],
  blocking_reasons: [],
  fingerprint: "fp",
};
const allowance = {
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
};
const savedDraw = (patch = {}) => ({
  id: 7,
  pool: "lazy",
  clan_tag: "#8QQ",
  cycle: "2026-11",
  created_at: "2026-11-11T10:00:00Z",
  approved_at: null,
  cancelled_at: null,
  cancel_reason: null,
  snapshot: {
    ...previewData,
    clan_tag: "#8QQ",
    clan_name: "Lazy Two",
    slots: 2,
    eligible: [account("#P3", "Charlie", "#8QQ")],
    winners: [account("#P3", "Charlie", "#8QQ")],
  },
  messages: ["Winners"],
  delivery: null,
  ...patch,
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const urlState = vi.fn();
const results = vi.fn();
// The Draw preview is a read; every other non-GET call is a write.
const isPreview = (call: unknown[]) => String(call[0]).endsWith("/preview");
const writes = () =>
  api.mock.calls.filter(
    (call) => call[1] && call[1] !== "GET" && !isPreview(call),
  );
const previews = () => api.mock.calls.filter(isPreview);
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
async function mount(data: object = base, state = "pool=lazy&clan=%232YQ") {
  api
    .mockReset()
    .mockImplementation((route: string) =>
      Promise.resolve(
        route.endsWith("/bonus-status")
          ? status
          : route.endsWith("/preview")
            ? previewData
            : route === "/announcement-channels"
              ? { channels: [] }
              : route === "/announcement-roles"
                ? { roles: [] }
                : data,
      ),
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
// The All clans card is tested on its own.
const cards = () => [
  ...host.querySelectorAll<HTMLButtonElement>(
    ".bonus-clan-card:not(.bonus-clan-all)",
  ),
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
const blockerText = () =>
  [...host.querySelectorAll(".bonus-blockers li")].map(
    (item) => item.textContent,
  );
const panels = () => [
  ...host.querySelectorAll<HTMLElement>("section[data-step-panel]"),
];
const openPanel = () => panels()[0]?.getAttribute("data-step-panel");
const stepLink = (id: string) =>
  host.querySelector<HTMLAnchorElement>(`.bonus-step[data-step="${id}"] a`)!;

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
          urlState="pool=lazy&clan=%232YQ"
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

describe("Bonus candidate cards", () => {
  it("use the shared card, and staff without bonus access cannot open Review", async () => {
    permission.value = false;
    await mount();
    const alpha = host.querySelector<HTMLButtonElement>(
      '.bonus-account-list [aria-label="Review Alpha"]',
    )!;
    expect(alpha.closest("article")!.classList).toContain(
      "shared-account-card",
    );
    expect(alpha.disabled).toBe(true);
    await act(async () => alpha.click());
    expect(document.querySelector(".bonus-review-editor")).toBeNull();
    expect(writes()).toHaveLength(0);
  });
});

describe("Bonus clan cards", () => {
  it("show name, meet count and state from the status read", async () => {
    await mount();
    expect(cards().map((card) => card.textContent)).toEqual([
      "Lazy One5 of 8 meet · Draft",
      // A saved draw replaces the meet count.
      "Lazy TwoDraw saved",
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
    // The marker is pushed; the page data then names the step in place.
    expect(urlState.mock.calls[0]).toEqual([
      "pool=lazy&clan=%238QQ&open=steps",
      true,
    ]);
    expect(urlState).toHaveBeenLastCalledWith(
      "pool=lazy&clan=%238QQ&step=rules",
      false,
    );
    expect(openPanel()).toBe("rules");
    expect(writes()).toHaveLength(0);
  });
  it("restores the clan from the URL", async () => {
    await mount(base, "pool=lazy&clan=%238QQ&step=draw");
    expect(cards()[1].getAttribute("aria-pressed")).toBe("true");
  });
  it("without a status read, a card pushes the steps marker and the page data replaces it with the step", async () => {
    const data = { ...base, draws: [savedDraw()] };
    // The status read never answers, as on a first open that is still waiting.
    api
      .mockReset()
      .mockImplementation((route: string) =>
        route.endsWith("/bonus-status")
          ? new Promise(() => {})
          : Promise.resolve(data),
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
    await act(async () => cards()[1].click());
    expect(urlState.mock.calls[0]).toEqual([
      expect.stringContaining("open=steps"),
      true,
    ]);
    expect(urlState.mock.calls.at(-1)).toEqual([
      "pool=lazy&clan=%238QQ&step=approve",
      false,
    ]);
    expect(openPanel()).toBe("approve");
    expect(
      urlState.mock.calls.filter(([query]) => /open=/.test(query)),
    ).toHaveLength(1);
  });
  it("with the status read loaded, a card pushes the steps marker and the page data picks the step", async () => {
    // Status says Results is partial; the page counts a saved reason as checked.
    const lazyStatus = {
      ...status,
      pools: {
        ...status.pools,
        lazy: [
          { ...status.pools.lazy[0], results_state: "partial" },
          status.pools.lazy[1],
        ],
      },
    };
    const data = {
      ...base,
      accounts: [
        account("#P1", "Alpha", "#2YQ"),
        account("#P2", "Bravo", "#2YQ", {
          attacks: null,
          stars: null,
          source_complete: false,
          bonus_review: {
            flags: [],
            override_reason: "Played, Clash was down",
          },
        }),
        account("#P3", "Charlie", "#8QQ"),
      ],
    };
    api
      .mockReset()
      .mockImplementation((route: string) =>
        Promise.resolve(route.endsWith("/bonus-status") ? lazyStatus : data),
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
          urlState="pool=lazy&clan=%238QQ&step=draw"
          onUrlState={urlState}
          onResults={results}
        />,
      ),
    );
    await act(async () => cards()[0].click());
    expect(urlState.mock.calls[0]).toEqual([
      expect.stringContaining("open=steps"),
      true,
    ]);
    expect(urlState.mock.calls[0][0]).not.toContain("step=");
    expect(urlState.mock.calls.at(-1)).toEqual([
      "pool=lazy&clan=%232YQ&step=rules",
      false,
    ]);
    expect(openPanel()).toBe("rules");
  });
  it("an address with the steps marker is replaced by the step and never keeps the marker", async () => {
    await mount(
      { ...base, draws: [savedDraw()] },
      "pool=lazy&clan=%238QQ&open=steps",
    );
    expect(urlState).toHaveBeenCalledTimes(1);
    expect(urlState).toHaveBeenLastCalledWith(
      "pool=lazy&clan=%238QQ&step=approve",
      false,
    );
    expect(openPanel()).toBe("approve");
  });
  it("an old address without the marker or a step still opens and writes nothing to the history", async () => {
    await mount(base, "pool=lazy&clan=%232YQ");
    expect(cards()[0].getAttribute("aria-pressed")).toBe("true");
    expect(urlState).not.toHaveBeenCalled();
  });
});

describe("Step blockers", () => {
  const ready: BonusReviewGuard = {
    canManage: true,
    archived: false,
    policyDirty: false,
    reviewDirty: false,
    candidateOpen: false,
    countReady: true,
    needsMinimum: false,
    rolesUnavailable: false,
    resultsMissing: false,
    uncheckedCount: 0,
    canReviewUnchecked: true,
    cycleMissing: false,
    hostInactive: false,
  };
  const everyLine = (guard: BonusReviewGuard) =>
    Object.values(bonusStepBlockers(guard)).flat();
  it("has one line for every disabled condition and none when ready", () => {
    expect(everyLine(ready)).toEqual([]);
    const lines: Record<string, string> = {};
    const blocking: Record<string, boolean> = {};
    for (const key of Object.keys(ready).filter(
      (item) => item !== "canReviewUnchecked",
    ) as (keyof BonusReviewGuard)[]) {
      const value =
        key === "canManage" || key === "countReady"
          ? false
          : key === "uncheckedCount"
            ? 3
            : true;
      const all = everyLine({ ...ready, [key]: value });
      // The same condition may guard Rules and Draw; it is one blocker.
      const unique = new Map<string, BonusBlockerLine>(
        all.map((line) => [line.id, line]),
      );
      expect(unique.size, key).toBe(1);
      lines[key] = all[0].text;
      blocking[key] = reviewBlocked(all);
    }
    // Only today's disabled conditions block; the others inform.
    expect(blocking).toEqual({
      canManage: true,
      archived: true,
      policyDirty: true,
      reviewDirty: true,
      candidateOpen: true,
      countReady: true,
      needsMinimum: true,
      rolesUnavailable: false,
      resultsMissing: false,
      uncheckedCount: false,
      cycleMissing: false,
      hostInactive: false,
    });
    expect(lines).toEqual({
      canManage: "Bonus access needed",
      archived: "Archived season · read only",
      policyDirty: "Save the minimum",
      reviewDirty: "Save the open review",
      candidateOpen: "Save the open review",
      countReady: "Enter the bonus count",
      needsMinimum: "Set the Main minimum",
      rolesUnavailable: "Discord roles unavailable · Retry",
      resultsMissing: "Results not captured",
      uncheckedCount: "3 not checked · Review",
      cycleMissing: "CWL month not set",
      hostInactive: "Hosting clan is not an active Lazy clan this season",
    });
  });
  it("puts each blocker on the step that fixes it", () => {
    const steps = (patch: Partial<BonusReviewGuard>) =>
      Object.fromEntries(
        Object.entries(bonusStepBlockers({ ...ready, ...patch }))
          .filter(([, items]) => items.length)
          .map(([step, items]) => [step, items.map((item) => item.id)]),
      );
    expect(steps({ countReady: false })).toEqual({ rules: ["count"] });
    expect(steps({ uncheckedCount: 2 })).toEqual({ results: ["partial"] });
    expect(steps({ uncheckedCount: 2, resultsMissing: true })).toEqual({
      results: ["results"],
    });
    expect(steps({ policyDirty: true, needsMinimum: true })).toEqual({
      rules: ["minimum-dirty"],
      draw: ["minimum-dirty"],
    });
    expect(steps({ archived: true })).toEqual({
      rules: ["archived"],
      draw: ["archived"],
      approve: ["archived"],
      announce: ["archived"],
    });
  });
  it("shows the count blocker once, beside the count, and clears it with a typed count", async () => {
    await mount();
    expect(openPanel()).toBe("rules");
    expect(blockerText()).toEqual(["Enter the bonus count"]);
    const stats = host.querySelector(".bonus-stats")!;
    expect(stats.querySelector(".bonus-inline-count")).not.toBeNull();
    // The count blocker follows the count box; the bar says the same.
    expect(
      stats.compareDocumentPosition(host.querySelector(".bonus-blockers")!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      host.querySelector(".bonus-step.is-blocked .bonus-step-reason")
        ?.textContent,
    ).toBe("Enter the bonus count");
    expect(
      (host.textContent || "").split("Enter the bonus count").length - 1,
    ).toBe(2);
    await typeCount("51");
    expect(blockerText()).toEqual(["Enter the bonus count"]);
    // A typed count counts: the bar and the panel agree at once.
    await typeCount("5");
    expect(blockerText()).toEqual([]);
    expect(host.querySelector(".bonus-step.is-blocked")).toBeNull();
    expect(stepLink("rules").textContent).toContain("Done");
    expect(writes()).toHaveLength(0);
    expect(previews()).toHaveLength(0);
  });
  it("shows Results, Discord and open-review blockers once, each with its fix", async () => {
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
    expect(openPanel()).toBe("results");
    expect(blockerText()).toEqual(["Results not captured · Check Clash now"]);
    expect(
      (host.textContent || "").split("Results not captured").length - 1,
    ).toBe(2);
    await act(async () => stepLink("rules").click());
    // The count line sits with the count box, after the other lines.
    expect(blockerText()).toEqual([
      "Discord roles unavailable · Retry",
      "Enter the bonus count",
    ]);
    // The Discord notice shows once on the page.
    expect(
      (host.textContent || "").split("Discord roles unavailable").length - 1,
    ).toBe(1);
    await typeCount("5");
    expect(blockerText()).toEqual(["Discord roles unavailable · Retry"]);
    expect(writes()).toHaveLength(0);
    await act(async () => button("Add player by tag").click());
    expect(blockerText()).toContain("Save the open review");
  });
  it("shows Set the Main minimum on Main and previews a typed minimum", async () => {
    await mount(
      {
        ...base,
        policies: { main: null, lazy: null },
        accounts: [account("#P9", "Main player", "#2YQ", { pool: "main" })],
        allowances: { "#2YQ": allowance },
      },
      "pool=main&clan=%232YQ",
    );
    expect(openPanel()).toBe("rules");
    expect(blockerText()).toEqual(["Set the Main minimum"]);
    // The player list shows before any draw, with no chips and no Review.
    const list = host.querySelector(".bonus-account-list")!;
    expect(list.textContent).toContain("Main player");
    expect(list.querySelector(".roster-ui-status")).toBeNull();
    expect(list.querySelector(".account-card-open")).toBeNull();
    expect(host.querySelector(".bonus-preview-note")).toBeNull();
    const input = host.querySelector<HTMLInputElement>(
      'input[name="minimum-attacks"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "3");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(host.querySelector(".bonus-preview-note")?.textContent).toBe(
      "Preview · not saved",
    );
    expect(list.querySelector(".roster-ui-status")?.textContent).toBe(
      "Meets rule",
    );
    expect(blockerText()).toEqual(["Save the minimum"]);
    expect(writes()).toHaveLength(0);
    await act(async () => button("Save minimum").click());
    expect(writes()).toEqual([
      [
        "/seasons/1/bonus-raffle/policy",
        "PATCH",
        { pool: "main", minimum: 3, revision: 1 },
      ],
    ]);
  });
  it("shows the inline count field only when the league was not captured", async () => {
    await mount({ ...base, allowances: { "#2YQ": allowance } });
    expect(host.querySelector(".bonus-inline-count")).toBeNull();
    expect(blockerText()).toEqual([]);
    // Results and Rules are done, so the page opens the Draw step.
    expect(openPanel()).toBe("draw");
  });
});

describe("Bonus steps", () => {
  const withAllowance = { ...base, allowances: { "#2YQ": allowance } };
  const stepLabels = () =>
    [...host.querySelectorAll(".bonus-step-done")].map((item) =>
      item.textContent?.replace(/\s+/g, " ").trim(),
    );
  it("opens the first step that is not done and shows done steps as one line", async () => {
    await mount();
    expect(panels()).toHaveLength(1);
    expect(openPanel()).toBe("rules");
    expect(stepLabels()).toEqual(["✓ Results · 2 players, 1 meet ruleChange"]);
  });
  it("restores the open step from the URL, including old step names", async () => {
    await mount(base, "pool=lazy&clan=%232YQ&step=results");
    expect(openPanel()).toBe("results");
    await act(async () => root.unmount());
    host.remove();
    await mount(base, "pool=lazy&clan=%232YQ&step=eligibility");
    expect(openPanel()).toBe("rules");
    expect(host.querySelector('[aria-current="step"]')?.textContent).toContain(
      "Rules & count",
    );
  });
  it("opens a done step again with Change and keeps it in the URL", async () => {
    await mount(base, "pool=lazy&clan=%238QQ");
    api.mockClear();
    expect(openPanel()).toBe("rules");
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>('[aria-label="Change Results"]')!
        .click(),
    );
    expect(openPanel()).toBe("results");
    expect(urlState).toHaveBeenLastCalledWith(
      "pool=lazy&clan=%238QQ&step=results",
      true,
    );
    expect(writes()).toHaveLength(0);
  });
  it("hides Draw, Approve and Announce actions until the earlier steps are done", async () => {
    await mount(base, "pool=lazy&clan=%232YQ&step=draw");
    expect(openPanel()).toBe("draw");
    expect(host.textContent).toContain("Finish Rules & count first.");
    expect(button("Draw and save winners")).toBeUndefined();
    expect(button("Save all winners")).toBeUndefined();
    expect(previews()).toHaveLength(0);
    for (const [id, text, action] of [
      ["approve", "Finish Rules & count first.", "Approve winners"],
      ["announce", "Finish Rules & count first.", "Send announcement"],
    ] as const) {
      await act(async () => stepLink(id).click());
      expect(openPanel()).toBe(id);
      expect(host.textContent).toContain(text);
      expect(button(action)).toBeUndefined();
    }
    expect(writes()).toHaveLength(0);
  });
  it("loads the draw preview once when Draw opens, with no Review eligibility button", async () => {
    await mount(withAllowance, "pool=lazy&clan=%232YQ&step=draw");
    expect(previews()).toHaveLength(1);
    expect(previews()[0]).toEqual([
      "/seasons/1/bonus-raffle/preview",
      "POST",
      { pool: "lazy", clan_tag: "#2YQ", slots: null },
    ]);
    expect(host.textContent).not.toContain("Review eligibility");
    expect(button("Draw and save winners")).toBeUndefined();
    // One eligible account fills the 5 open slots, so the button says so.
    expect(button("Save all winners")).toBeDefined();
    expect(host.textContent).toContain("1 eligible");
    expect(writes()).toHaveLength(0);
  });
  it("clears the preview when the count changes and loads it again for the new count", async () => {
    await mount(withAllowance, "pool=lazy&clan=%232YQ&step=draw");
    expect(previews()).toHaveLength(1);
    await act(async () => stepLink("rules").click());
    await act(async () =>
      host
        .querySelector<HTMLInputElement>('input[name="manual-count"]')!
        .click(),
    );
    expect(host.querySelector(".bonus-preview")).toBeNull();
    const field = host.querySelector<HTMLInputElement>(
      '.bonus-count-field input[name="bonus-count"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(field, "4");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => stepLink("draw").click());
    expect(previews()).toHaveLength(2);
    expect(previews()[1][2]).toEqual({
      pool: "lazy",
      clan_tag: "#2YQ",
      slots: 4,
    });
    expect(writes()).toHaveLength(0);
  });
  it("saves winners only from the button, then moves to Approve", async () => {
    await mount(withAllowance, "pool=lazy&clan=%232YQ&step=draw");
    const saved = savedDraw({ clan_tag: "#2YQ" });
    api.mockImplementation((route: string, method?: string) =>
      Promise.resolve(
        route.endsWith("/bonus-status")
          ? status
          : method === "POST" && route.endsWith("/draw")
            ? { ...withAllowance, draws: [{ ...saved, clan_tag: "#2YQ" }] }
            : previewData,
      ),
    );
    await act(async () => button("Save all winners").click());
    expect(writes()).toHaveLength(1);
    expect(writes()[0][0]).toBe("/seasons/1/bonus-raffle/draw");
    expect(openPanel()).toBe("approve");
    // The replaced entry always carries the step, so Forward restores the steps view.
    expect(urlState).toHaveBeenLastCalledWith(
      "pool=lazy&clan=%232YQ&step=approve",
      false,
    );
    expect(button("Approve winners")).toBeDefined();
  });
  it("shows Approve, Cancel this draw and the Announce step for a saved draw", async () => {
    await mount({ ...base, draws: [savedDraw()] }, "pool=lazy&clan=%238QQ");
    expect(openPanel()).toBe("approve");
    expect(button("Approve winners")).toBeDefined();
    expect(host.textContent).toContain("Cancel this draw");
    expect(stepLabels().join("|")).toContain("Draw · 1 winner saved");
    expect(stepLabels().join("|")).not.toContain("1 winners");
    await act(async () => stepLink("announce").click());
    expect(host.textContent).toContain("Finish Approve first.");
    expect(writes()).toHaveLength(0);
    await act(async () => root.unmount());
    host.remove();
    await mount(
      { ...base, draws: [savedDraw({ approved_at: "2026-11-11T11:00:00Z" })] },
      "pool=lazy&clan=%238QQ",
    );
    expect(openPanel()).toBe("announce");
    expect(host.textContent).toContain("Give the medals in Clash.");
    expect(button("Send announcement")).toBeDefined();
  });
  it("counts Not checked players: a partial list is red, a staff reason makes Results done", async () => {
    const half = (patch = {}) => ({
      ...base,
      accounts: [
        account("#P1", "Alpha", "#2YQ"),
        account("#P2", "Bravo", "#2YQ", {
          attacks: null,
          stars: null,
          source_complete: false,
          ...patch,
        }),
      ],
    });
    await mount(half());
    expect(openPanel()).toBe("results");
    expect(blockerText()).toEqual(["1 not checked · Review"]);
    expect(
      host.querySelector(".bonus-step.is-blocked .bonus-step-reason")
        ?.textContent,
    ).toBe("1 not checked · Review");
    expect(host.querySelector(".bonus-blockers li")!.classList).toContain(
      "is-alert",
    );
    // Review opens the first player who needs it.
    await act(async () =>
      button("Review", host.querySelector(".bonus-blockers")!).click(),
    );
    expect(
      document.querySelector(".bonus-review-editor")?.textContent,
    ).toContain("Bravo");
    await act(async () => root.unmount());
    host.remove();
    await mount(
      half({
        bonus_review: { flags: [], override_reason: "Played, Clash was down" },
      }),
    );
    expect(
      host.querySelector('.bonus-step[data-step="results"].is-blocked'),
    ).toBeNull();
    expect(openPanel()).toBe("rules");
    expect(stepLink("results").textContent).toContain("Done");
  });
  it("keeps removed names out of the page", async () => {
    await mount(
      { ...base, allowances: { "#2YQ": allowance } },
      "pool=lazy&clan=%232YQ&step=rules",
    );
    expect(openPanel()).toBe("rules");
    const text = host.textContent || "";
    for (const removed of [
      "Meets rules now",
      "Qualifying",
      "Verified eligible",
      "Refresh attacks from Clash",
      "Refresh list",
      "Candidate review",
      "Review eligibility",
    ])
      expect(text, removed).not.toContain(removed);
    expect(text).toContain("meet rule");
    expect(
      host.querySelector(".bonus-candidates-heading h3")?.textContent,
    ).toBe("Players");
  });
  it("labels the phone step toggle and search placeholders", async () => {
    await mount();
    const toggle = host.querySelector(".bonus-step-compact")!;
    expect(
      document.getElementById(toggle.getAttribute("aria-controls")!),
    ).not.toBeNull();
    expect(
      host.querySelector<HTMLInputElement>('input[name="account-search"]')!
        .placeholder,
    ).toBe("Name or #TAG…");
    expect(host.querySelector(".bonus-field-hint")?.textContent).toBe(
      "Number in Clash · 1–50",
    );
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

it("the step bar opens Results in the page with the pool and clan", async () => {
  await mount();
  const link = host.querySelector<HTMLAnchorElement>(".bonus-step-list a")!;
  expect(link.getAttribute("href")).toBe(
    "/cwl/results?season=1&pool=lazy&clan=%232YQ&step=results",
  );
  await act(async () => link.click());
  // Results is step 1 of this page; the other page is not opened.
  expect(results).not.toHaveBeenCalled();
  expect(urlState).toHaveBeenLastCalledWith(
    "pool=lazy&clan=%232YQ&step=results",
    true,
  );
  expect(openPanel()).toBe("results");
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
    expect(button("Check Clash now", host)).toBeUndefined();
    expect(await menuItems()).toEqual({
      Refresh: false,
      "Check Clash now": false,
      Settings: false,
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
        await select("Check Clash now");
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
          "pool=main&clan=%232YQ",
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
      "unsaved account review",
      async () => {
        Element.prototype.scrollIntoView ||= () => {};
        await mount();
        await act(async () =>
          host
            .querySelector<HTMLButtonElement>('[aria-label="Review Alpha"]')!
            .click(),
        );
        await act(async () =>
          document
            .querySelector<HTMLInputElement>(
              '.bonus-review-editor input[type="checkbox"]',
            )!
            .click(),
        );
      },
    ],
  ] as const)("%s disables Check Clash now", async (name, setup) => {
    await setup();
    expect(await menuItems()).toEqual({
      Refresh: name === "player lookup running" || name === "request running",
      "Check Clash now": true,
      Settings: name === "player lookup running" || name === "request running",
    });
  });
  it("a player lookup still running after the editor closes disables Check Clash now", async () => {
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
      "Check Clash now": true,
      Settings: true,
    });
  });
  it("Check Clash now posts the existing check", async () => {
    await mount();
    await select("Check Clash now");
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
  it("orders Rules & count: notice, stats, count line, rules, source, players, add", async () => {
    await mount({
      ...base,
      accounts: [
        account("#P1", "Alpha", "#2YQ", {
          representative_status: "unavailable",
        }),
      ],
    });
    const flow = host.querySelector(".bonus-step-panel")!;
    expect(flow.getAttribute("data-step-panel")).toBe("rules");
    const summary = (text: string) =>
      [...host.querySelectorAll("summary")].find(
        (item) => item.textContent === text,
      )!;
    const sequence = [
      flow.querySelector(".bonus-blockers")!,
      flow.querySelector(".bonus-stats")!,
      [...flow.querySelectorAll(".bonus-blockers")][1],
      flow.querySelector(".bonus-rules-line")!,
      flow.querySelector(".bonus-candidates-heading h3")!,
      flow.querySelector(".bonus-account-list")!,
      button("Add player by tag", flow),
      summary("Bonus count and source"),
    ];
    expect(sequence.every(Boolean)).toBe(true);
    for (let index = 1; index < sequence.length; index += 1)
      expect(
        sequence[index - 1].compareDocumentPosition(sequence[index]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
        String(index),
      ).toBeTruthy();
    expect(flow.querySelector(".bonus-blockers")?.textContent).toBe(
      "Discord roles unavailable · Retry",
    );
    expect(flow.querySelector(".bonus-rules-line")?.textContent).toContain(
      "4+ attacks, or 3 attacks and 8+ stars",
    );
    // Draw odds moved to the Settings sheet; no disclosure is left on the page.
    expect(summary("FWA Rep odds settings")).toBeUndefined();
    expect(summary("Capture settings")).toBeUndefined();
    expect(summary("Saved bonus history")).toBeUndefined();
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
      // The All clans card comes first, so the strip is one card longer.
      expect(host.querySelector(".bonus-clan-cards")!.scrollLeft).toBe(520);
      await act(async () => cards()[0].click());
      expect(host.querySelector(".bonus-clan-cards")!.scrollLeft).toBe(280);
    } finally {
      rect.mockRestore();
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
      delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
    }
  });
});

describe("Results & bonuses page: clan steps half", () => {
  const poolTab = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>(".cwl-pool-tabs button")].find(
      (tab) => tab.textContent?.trim() === label,
    )!;
  const renderBonusOnly = async (state: string, data: object = base) => {
    api
      .mockReset()
      .mockImplementation((route: string) =>
        Promise.resolve(
          route.endsWith("/bonus-status")
            ? status
            : route === "/announcement-roles"
              ? { roles: [] }
              : data,
        ),
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
        />,
      ),
    );
  };
  it("shows the clan cards only when no clan is selected", async () => {
    await mount(base, "pool=lazy");
    expect(openPanel()).toBeUndefined();
    expect(host.querySelector(".bonus-step-bar")).toBeNull();
    expect(host.querySelector(".bonus-account-list")).toBeNull();
    expect(cards().map((card) => card.textContent)).toEqual([
      "Lazy One5 of 8 meet · Draft",
      "Lazy TwoDraw saved",
    ]);
    expect(
      host.querySelector(".bonus-clan-all")!.getAttribute("aria-pressed"),
    ).toBe("true");
  });
  it("names the page Results & bonuses and leaves no settings or history disclosure", async () => {
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("Results & bonuses");
    expect(host.querySelector("details summary")?.textContent).not.toMatch(
      /FWA Rep odds|Saved bonus history|Capture settings/,
    );
    const text = host.textContent || "";
    for (const removed of [
      "FWA Rep odds settings",
      "Saved bonus history",
      "Saved results history",
      "Capture settings",
    ])
      expect(text).not.toContain(removed);
    expect(
      [...host.querySelectorAll("details")].filter((node) =>
        /history|odds|capture/i.test(node.textContent || ""),
      ),
    ).toHaveLength(0);
  });
  it("All clans goes to the player list through the unsaved-change guard", async () => {
    await mount();
    const all = host.querySelector<HTMLButtonElement>(".bonus-clan-all")!;
    await typeCount("4");
    await act(async () => all.click());
    expect(results).not.toHaveBeenCalled();
    await act(async () =>
      button("Cancel", document.querySelector(".confirm-dialog")!).click(),
    );
    expect(results).not.toHaveBeenCalled();
    expect(
      host.querySelector<HTMLInputElement>(".bonus-inline-count input")!.value,
    ).toBe("4");
    await act(async () => all.click());
    await act(async () =>
      button(
        "Discard bonus edits",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    expect(results).toHaveBeenCalledExactlyOnceWith("pool=lazy");
    expect(writes()).toHaveLength(0);
  });
  it("without Results access All clans clears the clan and shows the cards only", async () => {
    await renderBonusOnly("pool=lazy&clan=%232YQ&step=rules");
    expect(openPanel()).toBe("rules");
    await act(async () =>
      host.querySelector<HTMLButtonElement>(".bonus-clan-all")!.click(),
    );
    expect(urlState).toHaveBeenLastCalledWith("pool=lazy", true);
    expect(openPanel()).toBeUndefined();
    expect(host.querySelector(".bonus-step-bar")).toBeNull();
    expect(cards()).toHaveLength(2);
    expect(writes()).toHaveLength(0);
  });
  it("changing the pool asks first when the page has an unsaved count", async () => {
    await mount();
    await typeCount("4");
    await act(async () => poolTab("Main CWL").click());
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog).not.toBeNull();
    await act(async () => button("Cancel", dialog).click());
    expect(poolTab("Lazy CWL").getAttribute("aria-pressed")).toBe("true");
    expect(urlState).not.toHaveBeenCalled();
    expect(writes()).toHaveLength(0);
  });
  it("changing the step keeps the typed count in place", async () => {
    await mount();
    await typeCount("4");
    await act(async () => stepLink("results").click());
    expect(openPanel()).toBe("results");
    await act(async () => stepLink("rules").click());
    expect(
      host.querySelector<HTMLInputElement>(".bonus-inline-count input")!.value,
    ).toBe("4");
    expect(writes()).toHaveLength(0);
  });
  it("CWL month not set: the Results blocker opens Settings, with no write", async () => {
    await mount({ ...base, cycle: null }, "pool=lazy&clan=%232YQ&step=results");
    const open = host.querySelector<HTMLButtonElement>(
      ".bonus-blockers .bonus-inline-action",
    )!;
    expect(open.textContent).toBe("Open Settings");
    await act(async () => open.click());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(document.querySelector("dialog.results-settings")).not.toBeNull();
    expect(
      [...document.querySelectorAll(".results-settings-section h3")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["CWL capture", "Lazy draw odds"]);
    expect(writes()).toHaveLength(0);
  });
  it("without Results access the month blocker is plain text and Settings holds the odds only", async () => {
    await renderBonusOnly("pool=lazy&clan=%232YQ&step=results", {
      ...base,
      cycle: null,
    });
    expect(
      host.querySelector(".bonus-blockers .bonus-inline-action"),
    ).toBeNull();
  });
});

describe("Results & bonuses page: rework round", () => {
  const seasons = [
    { id: 1, label: "November", status: "draft", signup_open: true },
  ];
  const view = (state: string, withResults: boolean) => (
    <BonusWorkspace
      seasonId="1"
      seasons={seasons}
      onSeasonChange={() => {}}
      urlState={state}
      onUrlState={urlState}
      onResults={withResults ? results : undefined}
    />
  );
  const render = async (
    state: string,
    impl: (route: string, method?: string) => Promise<object>,
    withResults = false,
  ) => {
    api.mockReset().mockImplementation(impl);
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => root.render(view(state, withResults)));
  };
  const reply =
    (data: object, preview: () => Promise<object> = async () => previewData) =>
    (route: string) =>
      route.endsWith("/bonus-status")
        ? Promise.resolve(status)
        : route.endsWith("/preview")
          ? preview()
          : route === "/announcement-channels"
            ? Promise.resolve({ channels: [] })
            : Promise.resolve(data);
  const count = (text: string, part: string) => text.split(part).length - 1;

  it("Back to an address with no clan clears the clan and shows the cards only", async () => {
    await render("pool=lazy&clan=%232YQ&step=rules", reply(base));
    expect(openPanel()).toBe("rules");
    await act(async () => root.render(view("pool=lazy", false)));
    expect(openPanel()).toBeUndefined();
    expect(host.querySelector(".bonus-step-bar")).toBeNull();
    expect(host.querySelector(".bonus-account-list")).toBeNull();
    expect(cards()).toHaveLength(2);
    expect(
      host.querySelector(".bonus-clan-all")!.getAttribute("aria-pressed"),
    ).toBe("true");
    expect(writes()).toHaveLength(0);
  });
  it("drops a preview that arrives after the clan changed", async () => {
    let release!: (value: object) => void;
    const held = new Promise<object>((resolve) => (release = resolve));
    const charlie = {
      ...previewData,
      clan_tag: "#8QQ",
      clan_name: "Lazy Two",
      eligible: [account("#P3", "Charlie", "#8QQ")],
    };
    let calls = 0;
    await render(
      "pool=lazy&clan=%232YQ&step=draw",
      reply(
        {
          ...base,
          allowances: { "#2YQ": allowance, "#8QQ": allowance },
        },
        // The first preview is still loading when the clan changes.
        () => (++calls === 1 ? held : Promise.resolve(charlie)),
      ),
    );
    expect(previews()).toHaveLength(1);
    // Back to another clan's Draw step while the first preview is loading.
    await act(async () =>
      root.render(view("pool=lazy&clan=%238QQ&step=draw", false)),
    );
    await act(async () => release(previewData));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // Only the clan on screen has a preview; the late one for Lazy One is dropped.
    expect(
      previews().map((call) => (call[2] as { clan_tag: string }).clan_tag),
    ).toEqual(["#2YQ", "#8QQ"]);
    expect(host.textContent).not.toContain("Alpha");
    expect(host.textContent).toContain("Charlie");
    expect(host.querySelector(".working-status")).toBeNull();
    expect(writes()).toHaveLength(0);
  });
  it("shows Archived season and CWL month not set once each", async () => {
    await render(
      "pool=lazy&clan=%232YQ&step=rules",
      reply({ ...base, season_status: "archived" }),
    );
    expect(count(host.textContent || "", "Archived season")).toBe(1);
    await act(async () => root.unmount());
    host.remove();
    await render(
      "pool=lazy&clan=%232YQ&step=results",
      reply({ ...base, cycle: null }),
    );
    expect(count(host.textContent || "", "CWL month not set")).toBe(1);
    expect(host.querySelector(".bonus-context p")?.textContent).toBe(
      "Clash not checked yet",
    );
  });
  it("says once that the medals are given in Clash", async () => {
    await render(
      "pool=lazy&clan=%238QQ&step=announce",
      reply({
        ...base,
        draws: [savedDraw({ approved_at: "2026-11-11T11:00:00Z" })],
      }),
    );
    const text = host.textContent || "";
    expect(count(text, "Give the medals in Clash.")).toBe(1);
    expect(text).toContain("The announcement does not award them.");
    expect(count(text, "does not award")).toBe(1);
    expect(text).not.toContain("Staff must award");
  });
  it("without Results access the page keeps Saved bonus history, read only when opened", async () => {
    await render("pool=lazy&clan=%232YQ&step=rules", reply(base));
    const summary = host.querySelector(".bonus-history summary")!;
    expect(summary.textContent).toContain("Saved bonus history");
    const reads = () =>
      api.mock.calls.filter((call) => call[0] === "/seasons/1/bonus-raffle");
    expect(reads()).toHaveLength(1);
    await act(async () => {
      const details = host.querySelector<HTMLDetailsElement>(".bonus-history")!;
      details.open = true;
      details.dispatchEvent(new Event("toggle", { bubbles: true }));
    });
    expect(reads()).toHaveLength(2);
    expect(writes()).toHaveLength(0);
  });
  it("with Results access the history stays in Exports only", async () => {
    await render("pool=lazy&clan=%232YQ&step=rules", reply(base), true);
    expect(host.querySelector(".bonus-history")).toBeNull();
    expect(host.textContent).not.toContain("Saved bonus history");
  });
});
