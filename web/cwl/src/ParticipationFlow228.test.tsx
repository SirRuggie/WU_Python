// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { pickerByLabel } from "./searchPickerTestUtils";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import ParticipationWorkspace from "./ParticipationWorkspace";

const row = (
  tag: string,
  name: string,
  pool: "main" | "lazy",
  clan: [string, string],
  attacks: number | null,
  stars: number | null,
) => ({
  tag,
  player_name: name,
  town_hall: 16,
  pool,
  assigned_clan_tag: clan[0],
  assigned_clan_name: clan[1],
  attacks,
  stars,
  notes: "",
  revision: 1,
  updated_by: null,
  updated_at: null,
  in_latest_publication: true,
  source_status: attacks === null ? "never" : "complete",
  source_complete: attacks !== null,
});
const lazyOne: [string, string] = ["#2YQ", "Lazy One"];
const lazyTwo: [string, string] = ["#8QQ", "Lazy Two"];
const accounts = [
  row("#P1", "Alpha", "lazy", lazyOne, 4, 9),
  row("#P2", "Bravo", "lazy", lazyOne, 3, 7),
  row("#P3", "Charlie", "lazy", lazyTwo, null, null),
  row("#P4", "Delta", "main", ["#9PP", "Main One"], 2, 6),
];
const participation = {
  publication_version: 1,
  accounts,
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
const status = (mainMinimum: number | null) => ({
  season_id: 1,
  cycle: "2026-11",
  archived: false,
  main_minimum: mainMinimum,
  pools: {
    main: [
      {
        tag: "#9PP",
        name: "Main One",
        active: true,
        candidates: 1,
        meets_rule: 0,
        results_state: "captured",
        allowance_ready: true,
        draw_state: "none",
      },
    ],
    lazy: [
      {
        tag: "#2YQ",
        name: "Lazy One",
        active: true,
        candidates: 2,
        meets_rule: 1,
        results_state: "captured",
        allowance_ready: true,
        draw_state: "saved",
      },
    ],
  },
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
let partC: {
  resolve: (value: unknown) => void;
  reject: (cause: unknown) => void;
};
const urlState = vi.fn();
const bonus = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  urlState.mockReset();
  bonus.mockReset();
  api.mockReset().mockImplementation((route: string) =>
    route.endsWith("/bonus-status")
      ? new Promise((resolve, reject) => {
          partC = { resolve, reject };
        })
      : Promise.resolve(participation),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function mount(state = "pool=lazy") {
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
        onBonus={bonus}
        urlState={state}
        onUrlState={urlState}
      />,
    ),
  );
}
const names = () =>
  [
    ...host.querySelectorAll<HTMLLIElement>(
      ".participation-list > li:not([hidden])",
    ),
  ].map((item) => item.querySelector(".player-card-name-text")?.textContent);
const chip = (label: string) =>
  [
    ...host.querySelectorAll<HTMLButtonElement>(
      ".participation-outcomes button",
    ),
  ].find((button) => button.textContent?.startsWith(label))!;

it("hides the step bar until one hosting clan is selected", async () => {
  await mount();
  await act(async () => partC.resolve(status(3)));
  expect(names()).toEqual(["Alpha", "Bravo", "Charlie"]);
  expect(host.querySelector(".bonus-step-bar")).toBeNull();
  const select = host.querySelector<HTMLSelectElement>(
    '.participation-toolbar select[name="clan"]',
  )!;
  expect(select.options[0].textContent).toBe("All clans");
  await act(async () => {
    select.value = "#2YQ";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.querySelectorAll(".bonus-step-bar")).toHaveLength(1);
});

it("renders the list before the status read resolves and never calls the full bonus read", async () => {
  await mount("pool=lazy&clan=%232YQ");
  expect(names()).toEqual(["Alpha", "Bravo"]);
  expect(host.querySelector(".bonus-step-mark")?.textContent).toBe("…");
  const routes = api.mock.calls.map((call) => call[0] as string);
  expect(routes[0]).toBe("/seasons/1/participation");
  expect(routes).toContain("/seasons/1/bonus-status");
  expect(routes.some((route) => route.includes("bonus-raffle"))).toBe(false);
  await act(async () => partC.resolve(status(3)));
  expect(host.querySelector(".bonus-step-mark")?.textContent).not.toBe("…");
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
});

it("a status read failure keeps the list and shows one muted retry line", async () => {
  await mount("pool=lazy&clan=%232YQ");
  await act(async () => partC.reject(new Error("down")));
  expect(names()).toEqual(["Alpha", "Bravo"]);
  expect(host.querySelectorAll(".bonus-step-unavailable")).toHaveLength(1);
  expect(host.querySelector(".bonus-step-unavailable")?.textContent).toBe(
    "Status unavailable · Retry",
  );
  const before = api.mock.calls.length;
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(".bonus-step-unavailable button")!
      .click(),
  );
  expect(api.mock.calls.slice(before).map((call) => call[0])).toEqual([
    "/seasons/1/bonus-status",
  ]);
});

it("outcome chips count and filter, and the count line uses the selected pool", async () => {
  await mount();
  expect(
    [...host.querySelectorAll(".participation-outcomes button")].map(
      (button) => button.textContent,
    ),
  ).toEqual(["All 3", "Meets rule 1", "Below rule 1", "Not checked 1"]);
  expect(
    host.querySelector(".participation-list-heading span")?.textContent,
  ).toBe("3 players · Lazy CWL");
  await act(async () => chip("Below rule").click());
  expect(names()).toEqual(["Bravo"]);
  expect(chip("Below rule").getAttribute("aria-pressed")).toBe("true");
  expect(
    host.querySelector(".participation-list-heading span")?.textContent,
  ).toBe("1 of 3 players · Lazy CWL");
  expect(urlState).toHaveBeenLastCalledWith("pool=lazy&outcome=below", true);
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
});

it("Sort has three options", async () => {
  await mount();
  const sort = host.querySelector<HTMLSelectElement>('select[name="sort"]')!;
  expect([...sort.options].map((option) => option.textContent)).toEqual([
    "Name A–Z",
    "Attacks high to low",
    "Stars high to low",
  ]);
  await act(async () => {
    sort.value = "stars-desc";
    sort.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(names()).toEqual(["Alpha", "Bravo", "Charlie"]);
  expect(urlState).toHaveBeenLastCalledWith("pool=lazy&sort=stars-desc", true);
});

it("URL keys restore pool, clan, outcome and sort, also after Back", async () => {
  await mount("pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc");
  expect(
    host.querySelector('.cwl-pool-tabs [aria-pressed="true"]')?.textContent,
  ).toBe("Lazy CWL");
  expect(
    host.querySelector<HTMLSelectElement>('select[name="clan"]')!.value,
  ).toBe("#2YQ");
  expect(
    host.querySelector<HTMLSelectElement>('select[name="sort"]')!.value,
  ).toBe("attacks-desc");
  expect(chip("Meets rule").getAttribute("aria-pressed")).toBe("true");
  expect(names()).toEqual(["Alpha"]);
  expect(urlState).not.toHaveBeenCalled();
  await act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
        onBonus={bonus}
        urlState="pool=main"
        onUrlState={urlState}
      />,
    ),
  );
  expect(
    host.querySelector('.cwl-pool-tabs [aria-pressed="true"]')?.textContent,
  ).toBe("Main CWL");
  expect(
    host.querySelector<HTMLSelectElement>('select[name="clan"]')!.value,
  ).toBe("all");
  expect(names()).toEqual(["Delta"]);
});

it("cards get an outcome chip and tinted numbers but no card tone", async () => {
  await mount();
  const card = (name: string) =>
    [...host.querySelectorAll<HTMLElement>(".participation-list > li")].find(
      (item) =>
        item.querySelector(".player-card-name-text")?.textContent === name,
    )!;
  const expectChip = (name: string, text: string, tone: string) => {
    const pill = card(name).querySelector(".roster-ui-status")!;
    expect(pill.textContent).toBe(text);
    expect(pill.classList).toContain(`is-${tone}`);
    expect(card(name).querySelector(".player-card")!.className).toBe(
      "player-card",
    );
    const root = card(name).querySelector("article.shared-account-card")!;
    expect(root.className).not.toMatch(
      /is-assigned|compare-account-missing|\b(good|bad)\b|is-(good|bad|success|danger)/,
    );
    for (const value of card(name).querySelectorAll(
      ".participation-values strong",
    ))
      expect(value.classList).toContain(`is-${tone}`);
  };
  expectChip("Alpha", "Meets rule", "success");
  expectChip("Bravo", "Below rule", "danger");
  expectChip("Charlie", "Not checked", "warning");
  for (const line of host.querySelectorAll(
    ".participation-list .account-card-status",
  ))
    expect(line.textContent).not.toContain("Complete");
  expect(host.querySelector(".participation-list")?.tagName).toBe("UL");
});

it("Main shows no chip without a saved minimum and the rule chip with one", async () => {
  await mount("pool=main");
  const shown = ".participation-list > li:not([hidden]) .roster-ui-status";
  expect(names()).toEqual(["Delta"]);
  expect(host.querySelector(shown)).toBeNull();
  expect(host.querySelector(".participation-outcomes")).toBeNull();
  await act(async () => partC.resolve(status(3)));
  expect(host.querySelector(shown)?.textContent).toBe("Below rule");
});

it("step links carry pool and clan to Bonus medals", async () => {
  await mount("pool=lazy&clan=%232YQ");
  await act(async () => partC.resolve(status(3)));
  expect(host.querySelector(".bonus-step.is-current")?.textContent).toContain(
    "Approval",
  );
  const draw = [
    ...host.querySelectorAll<HTMLAnchorElement>(".bonus-step-list a"),
  ].find((link) => link.textContent?.includes("Draw"))!;
  expect(draw.getAttribute("href")).toBe(
    "/cwl/bonuses?season=1&pool=lazy&clan=%232YQ&step=draw",
  );
  await act(async () => draw.click());
  expect(bonus).toHaveBeenCalledExactlyOnceWith(
    "pool=lazy&clan=%232YQ&step=draw",
  );
  expect(host.querySelector(".cwl-next-cue")).toBeNull();
});

it("uses the search picker for the clan filter over 20 clans", async () => {
  api.mockImplementation((route: string) =>
    route.endsWith("/bonus-status")
      ? new Promise(() => {})
      : Promise.resolve({
          ...participation,
          accounts: Array.from({ length: 21 }, (_, index) =>
            row(
              `#Q${index}`,
              `Player ${index}`,
              "lazy",
              [`#C${index}`, `Clan ${index}`],
              4,
              9,
            ),
          ),
        }),
  );
  await mount();
  expect(host.querySelector('select[name="clan"]')).toBeNull();
  expect(pickerByLabel(host, "Hosting clan")).toBeTruthy();
});
