// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
// A retained result edit is the unsaved work the guards protect (not a live editor).
vi.mock("./ParticipationRecord", () => ({
  default: ({
    account,
    onDirty,
  }: {
    account: { tag: string; player_name: string };
    onDirty: (tag: string, dirty: boolean) => void;
  }) => (
    <>
      <span className="player-card-name-text">{account.player_name}</span>
      <button onClick={() => onDirty(account.tag, true)}>
        Retain local result edit {account.tag}
      </button>
    </>
  ),
}));
import ParticipationWorkspace from "./ParticipationWorkspace";

const row = (tag: string, name: string, clan: [string, string]) => ({
  tag,
  player_name: name,
  town_hall: 16,
  pool: "lazy",
  assigned_clan_tag: clan[0],
  assigned_clan_name: clan[1],
  attacks: 4,
  stars: 9,
  notes: "",
  revision: 1,
  in_latest_publication: true,
  source_status: "complete",
  source_complete: true,
});
const participation = {
  publication_version: 1,
  accounts: [
    row("#P1", "Alpha", ["#2YQ", "Lazy One"]),
    row("#P2", "Bravo", ["#8QQ", "Lazy Two"]),
  ],
  sync: {
    cycle: "2026-11",
    cycle_source: "settings",
    enabled: true,
    status: "complete",
    warning: null,
    last_checked_at: "2026-11-01T12:00:00Z",
    last_success_at: "2026-11-01T12:00:00Z",
    updated_at: "2026-11-01T12:00:00Z",
  },
};
const hosting = (tag: string, name: string, patch = {}) => ({
  tag,
  name,
  active: true,
  candidates: 8,
  meets_rule: 5,
  results_state: "captured",
  allowance_ready: true,
  draw_state: "none",
  ...patch,
});
const status = {
  season_id: 1,
  cycle: "2026-11",
  archived: false,
  main_minimum: 3,
  pools: {
    main: [],
    lazy: [
      hosting("#2YQ", "Lazy One"),
      hosting("#8QQ", "Lazy Two", { draw_state: "approved" }),
    ],
  },
};
let host: HTMLDivElement;
let root: Root;
const bonus = vi.fn();
const urlState = vi.fn();
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent?.trim() === name,
  )!;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
const cards = () => [
  ...host.querySelectorAll<HTMLButtonElement>(
    ".bonus-clan-card:not(.bonus-clan-all)",
  ),
];
async function mount(withBonus = true, state = "pool=lazy") {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
        onBonus={withBonus ? bonus : undefined}
        urlState={state}
        onUrlState={urlState}
      />,
    ),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  bonus.mockReset();
  urlState.mockReset();
  api
    .mockReset()
    .mockImplementation(async (route: string) =>
      route.endsWith("/bonus-status")
        ? status
        : route === "/announcement-roles"
          ? { roles: [] }
          : route.endsWith("/bonus-raffle")
            ? { season_status: "draft", revision: 1, draws: [], history: [] }
            : participation,
    );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("season overview", () => {
  it("shows clan cards with their state above today's full player list", async () => {
    await mount();
    expect(
      host.querySelector(".bonus-clan-all")!.getAttribute("aria-pressed"),
    ).toBe("true");
    expect(cards().map((card) => card.textContent)).toEqual([
      "Lazy One5 of 8 meet · Draft",
      "Lazy TwoApproved",
    ]);
    expect(
      [...host.querySelectorAll(".participation-list > li")].map(
        (item) => item.querySelector(".player-card-name-text")?.textContent,
      ),
    ).toEqual(["Alpha", "Bravo"]);
    // One pool row, one season field.
    expect(host.querySelectorAll('select[name="season"]')).toHaveLength(1);
    expect(host.querySelectorAll(".cwl-pool-tabs").length).toBeLessThanOrEqual(
      1,
    );
  });
  it("leaves no settings or history disclosure on the page", async () => {
    await mount();
    expect(host.querySelector("details")).toBeNull();
    const text = host.textContent || "";
    for (const removed of [
      "Capture settings",
      "Saved results history",
      "Saved bonus history",
      "FWA Rep odds settings",
      "Refresh list",
    ])
      expect(text).not.toContain(removed);
  });
  it("orders the phone page: step bar, pool tabs, clan cards, then the list", async () => {
    await mount(true, "pool=lazy&clan=%232YQ&outcome=partial");
    const order = [
      ".bonus-step-bar",
      ".cwl-pool-tabs",
      ".bonus-clan-cards",
      ".participation-list",
    ].map((selector) => host.querySelector(selector));
    expect(order.every(Boolean)).toBe(true);
    for (let index = 1; index < order.length; index += 1)
      expect(
        order[index - 1]!.compareDocumentPosition(order[index]!) &
          Node.DOCUMENT_POSITION_FOLLOWING,
        String(index),
      ).toBeTruthy();
  });
  it("selecting a clan card opens that clan's steps and writes nothing", async () => {
    await mount();
    await act(async () => cards()[0].click());
    // The address names the first step that is not done, so Back and Forward return to it.
    expect(bonus).toHaveBeenCalledExactlyOnceWith(
      "pool=lazy&clan=%232YQ&step=draw",
    );
    expect(writes()).toHaveLength(0);
  });
  it("asks before leaving with an unsaved result edit", async () => {
    await mount();
    await act(async () => button("Retain local result edit #P1").click());
    await act(async () => cards()[1].click());
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog.textContent).toContain("open the bonus steps");
    expect(bonus).not.toHaveBeenCalled();
    await act(async () => button("Cancel", dialog).click());
    expect(bonus).not.toHaveBeenCalled();
    await act(async () => cards()[1].click());
    await act(async () => {
      const confirm = button(
        "Discard and continue",
        document.querySelector(".confirm-dialog")!,
      );
      confirm.click();
      confirm.click();
    });
    expect(bonus).toHaveBeenCalledExactlyOnceWith(
      "pool=lazy&clan=%238QQ&step=announce",
    );
    expect(writes()).toHaveLength(0);
  });
  it("a step in the bar asks the same question", async () => {
    await mount(true, "pool=lazy&clan=%232YQ&outcome=partial");
    await act(async () => button("Retain local result edit #P1").click());
    const draw = host.querySelector<HTMLAnchorElement>(
      '.bonus-step[data-step="draw"] a',
    )!;
    await act(async () => draw.click());
    expect(document.querySelector(".confirm-dialog")).not.toBeNull();
    expect(bonus).not.toHaveBeenCalled();
  });
  it("results-only staff see the list and a bar they cannot open past Results", async () => {
    await mount(false, "pool=lazy&clan=%232YQ&outcome=partial");
    expect(host.querySelector(".bonus-clan-cards")).toBeNull();
    // The step bar needs the bonus status; without it there is no bar.
    expect(host.querySelector(".bonus-step-bar")).toBeNull();
    expect(
      api.mock.calls.some((call) => String(call[0]).includes("bonus-status")),
    ).toBe(false);
    expect(host.querySelector(".participation-list")).not.toBeNull();
  });
});

describe("page menu", () => {
  const choose = async (label: string) => {
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>(
          ".participation-capture .roster-action-trigger",
        )!
        .click(),
    );
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
  it("holds Check Clash now, Refresh and Settings", async () => {
    await mount();
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>(
          ".participation-capture .roster-action-trigger",
        )!
        .click(),
    );
    expect(
      [...document.querySelectorAll('[role="menuitem"]')].map((node) =>
        node.textContent?.trim(),
      ),
    ).toEqual(["Check Clash now", "Refresh", "Settings"]);
  });
  it("Settings opens the sheet with both sections for staff with bonus access", async () => {
    await mount();
    await choose("Settings");
    expect(
      [...document.querySelectorAll(".results-settings-section h3")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["CWL capture", "Lazy draw odds"]);
  });
  it("Settings shows only CWL capture without bonus access", async () => {
    await mount(false);
    await choose("Settings");
    expect(
      [...document.querySelectorAll(".results-settings-section h3")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["CWL capture"]);
  });
  it("the old-results warning carries Check Clash now on the overview too", async () => {
    const old = {
      code: "not_recent",
      label: "Results need a check",
      warning: "These results have not been checked recently.",
      failed_clan: false,
      round: null,
      last_check_failed: false,
    };
    api.mockImplementation(async (route: string) =>
      route.endsWith("/bonus-status")
        ? status
        : route === "/announcement-roles"
          ? { roles: [] }
          : {
              ...participation,
              accounts: participation.accounts.map((item) => ({
                ...item,
                display_status: old,
              })),
            },
    );
    await mount();
    const warning = host.querySelector(".participation-capture-warning")!;
    expect(warning.textContent).toContain(
      "These results have not been checked recently.",
    );
    expect(button("Check Clash now", warning)).toBeDefined();
    expect(writes()).toHaveLength(0);
  });
});
