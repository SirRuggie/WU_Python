// @vitest-environment happy-dom
import { act, Suspense } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
const permission = vi.hoisted(() => ({ value: true }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => permission.value,
}));
import BonusWorkspace from "./BonusWorkspace";
import ParticipationWorkspace from "./ParticipationWorkspace";
import ResultsBonusesWorkspace from "./ResultsBonusesWorkspace";

const data = {
  season_status: "draft",
  cycle: "2026-11",
  revision: 1,
  policies: { main: null, lazy: null },
  policy: {},
  clans: [{ tag: "#2YQ", name: "Family", slots: null }],
  lazy_hosts: [{ tag: "#2YQ", name: "Family", slots: null }],
  accounts: [
    {
      tag: "#PYY",
      player_name: "Fixture",
      pool: "main",
      assigned_clan_tag: "#2YQ",
      assigned_clan_name: "Family",
      town_hall: 16,
      attacks: 4,
      stars: 9,
      source_status: "complete",
      source_complete: true,
    },
  ],
  draws: [],
  history: [],
  cycle_confirmed: [],
  active_other_cycles: [],
  sync: { enabled: false, warning: null, last_checked_at: null },
  publication_version: 1,
};
const status = {
  season_id: 1,
  cycle: "2026-11",
  archived: false,
  main_minimum: null,
  pools: {
    main: [
      {
        tag: "#2YQ",
        name: "Family",
        active: true,
        candidates: 1,
        meets_rule: 0,
        results_state: "captured",
        allowance_ready: false,
        draw_state: "none",
      },
    ],
    lazy: [],
  },
};
const headings = [
  "Bonus count",
  "Who qualifies",
  "Infractions (Lazy)",
  "Sit-out after a win (Lazy)",
  "Draw",
];
const paragraphs = [
  "It comes from the CWL league, plus 1 for each war win.",
  "Main: the minimum attacks in the Rules step. Lazy: 4+ attacks, or 3+ attacks and 8+ stars. One bonus per account each month.",
  "Missed sync, Lingering or Left family removes the account this month. A staff reason can put it back.",
  "A winner sits out for a set number of months. Each clan sets its number in Settings. Default 3. Example: October win, 3 months → can win again in February.",
  "Winners are drawn at random. FWA Rep accounts selected in Settings have 2× the chance in Lazy.",
];
let host: HTMLDivElement, root: Root;
const dirty = vi.fn();
const fetchMock = vi.fn();
const help = () =>
  host.querySelector<HTMLButtonElement>('[aria-label="How bonuses work"]')!;
const panel = () =>
  document.querySelector<HTMLDialogElement>("dialog.bonus-help-panel");
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 15));
  });
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
  permission.value = true;
  dirty.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) =>
    setTimeout(() => fn(0), 0),
  );
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(
    () => [{ width: 44, height: 44 }] as unknown as DOMRectList,
  );
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  history.replaceState({}, "", "/cwl/results?season=1");
  api
    .mockReset()
    .mockImplementation((route: string) =>
      Promise.resolve(route.endsWith("/bonus-status") ? status : data),
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  await settle();
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function mount(seasonId = "1", step = "results") {
  await act(async () =>
    root.render(
      <BonusWorkspace
        seasonId={seasonId}
        seasons={[
          { id: 1, label: "2026-11", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
        onDirty={dirty}
        onResults={() => {}}
        urlState={`pool=main&clan=%232YQ&step=${step}`}
      />,
    ),
  );
}
it.each(["results", "rules", "draw", "approve", "announce"])(
  "keeps exactly one header help trigger on the %s step",
  async (step) => {
    await mount("1", step);
    expect(
      host.querySelectorAll('[aria-label="How bonuses work"]'),
    ).toHaveLength(1);
    const title = host.querySelector("h1")!;
    expect(
      title.parentElement?.classList.contains("cwl-page-header-title"),
    ).toBe(true);
    expect(title.nextElementSibling).toBe(help());
    expect(help().title).toBe("How bonuses work");
    expect(help().type).toBe("button");
    expect(
      host.querySelector<HTMLSelectElement>('select[name="season"]')?.value,
    ).toBe("1");
  },
);
it("is available with no season and without the Bonuses grant, with no reads or writes", async () => {
  permission.value = false;
  await mount("");
  const before = api.mock.calls.length;
  await act(async () => help().click());
  expect(panel()?.open).toBe(true);
  expect(api.mock.calls).toHaveLength(before);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("opens the shared side dialog with exactly the approved five headings and paragraphs and no footer", async () => {
  await mount();
  const before = api.mock.calls.length;
  await act(async () => {
    help().click();
    help().click();
  });
  const dialog = panel()!;
  expect(document.querySelectorAll("dialog.bonus-help-panel")).toHaveLength(1);
  expect(dialog.classList.contains("action-panel-side")).toBe(true);
  expect(
    document.getElementById(dialog.getAttribute("aria-labelledby")!)
      ?.textContent,
  ).toBe("How bonuses work");
  expect(
    [...dialog.querySelectorAll("h3")].map((el) => el.textContent),
  ).toEqual(headings);
  expect(
    [...dialog.querySelectorAll("p")].map((el) =>
      el.textContent?.replace(/\s+/g, " ").trim(),
    ),
  ).toEqual(paragraphs);
  expect(dialog.querySelector("footer")).toBeNull();
  expect(dialog.querySelectorAll("button")).toHaveLength(1);
  expect(dialog.textContent).not.toMatch(
    /\b(the bot|choose|pick|click|tap)\b/i,
  );
  expect(api.mock.calls).toHaveLength(before);
  expect(fetchMock).not.toHaveBeenCalled();
});
it.each(["Close", "Escape", "Back"])(
  "%s closes without a request and restores trigger focus",
  async (method) => {
    await mount();
    const before = api.mock.calls.length;
    await act(async () => {
      help().focus();
      help().click();
    });
    await act(async () => {
      if (method === "Close")
        panel()!
          .querySelector<HTMLButtonElement>(".action-panel-close")!
          .click();
      else if (method === "Escape")
        panel()!.dispatchEvent(new Event("cancel", { cancelable: true }));
      else {
        history.replaceState({}, "", location.href);
        window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
      }
    });
    await settle();
    expect(panel()).toBeNull();
    expect(document.activeElement).toBe(help());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(api.mock.calls).toHaveLength(before);
    expect(fetchMock).not.toHaveBeenCalled();
  },
);
it("retains an unsaved Rules minimum and dirty ownership without a discard prompt or API request", async () => {
  await mount("1", "rules");
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
  expect(dirty).toHaveBeenLastCalledWith(true);
  const before = api.mock.calls.length;
  const dirtyBefore = dirty.mock.calls.length;
  await act(async () => help().click());
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  await act(async () =>
    panel()!.querySelector<HTMLButtonElement>(".action-panel-close")!.click(),
  );
  await settle();
  expect(input.value).toBe("3");
  expect(dirty.mock.calls).toHaveLength(dirtyBefore);
  expect(host.textContent).toContain("Save the minimum");
  expect(api.mock.calls).toHaveLength(before);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("programmatic-only: retains a dirty Settings draft when help is invoked behind the modal (not native reachability proof)", async () => {
  await mount();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        ".bonus-context .roster-action-trigger",
      )!
      .click(),
  );
  await act(async () =>
    [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')]
      .find((node) => node.textContent?.trim() === "Settings")!
      .click(),
  );
  const settings = document.querySelector<HTMLDialogElement>(
    "dialog.results-settings",
  )!;
  const month = settings.querySelector<HTMLInputElement>(
    'input[name="cwl-month"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(month, "2026-12");
    month.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(dirty).toHaveBeenLastCalledWith(true);
  const before = api.mock.calls.length;
  // happy-dom does not enforce native inertness.1044 accepts one header trigger;
  // a real user opens help before/after Settings, not through its native modal.
  await act(async () => help().click());
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  await act(async () =>
    panel()!.querySelector<HTMLButtonElement>(".action-panel-close")!.click(),
  );
  await settle();
  expect(settings.open).toBe(true);
  expect(month.value).toBe("2026-12");
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(api.mock.calls).toHaveLength(before);
  expect(fetchMock).not.toHaveBeenCalled();
});
it.each([
  { seasonId: "1", bonuses: true },
  { seasonId: "", bonuses: true },
  { seasonId: "1", bonuses: false },
])(
  "real Results list exposes one read-only help trigger (season=$seasonId, bonuses=$bonuses)",
  async ({ seasonId, bonuses }) => {
    permission.value = bonuses;
    await act(async () =>
      root.render(
        <ParticipationWorkspace
          seasonId={seasonId}
          seasons={[
            { id: 1, label: "2026-11", status: "draft", signup_open: true },
          ]}
          onSeasonChange={() => {}}
          onBonus={bonuses ? () => {} : undefined}
        />,
      ),
    );
    expect(host.querySelector(".participation-page-head h1")?.textContent).toBe(
      "Results & bonuses",
    );
    expect(
      host.querySelectorAll('[aria-label="How bonuses work"]'),
    ).toHaveLength(1);
    expect(host.querySelector("h1")?.nextElementSibling).toBe(help());
    const season = host.querySelector<HTMLSelectElement>(
      ".participation-season select",
    )!;
    expect(season.value).toBe(seasonId);
    const before = api.mock.calls.length;
    await act(async () => help().click());
    expect(panel()?.open).toBe(true);
    expect(panel()?.querySelectorAll("h3")).toHaveLength(5);
    await act(async () =>
      panel()!.querySelector<HTMLButtonElement>(".action-panel-close")!.click(),
    );
    await settle();
    expect(panel()).toBeNull();
    expect(document.activeElement).toBe(help());
    expect(season.value).toBe(seasonId);
    expect(api.mock.calls).toHaveLength(before);
    expect(fetchMock).not.toHaveBeenCalled();
  },
);
it.each([
  { query: "", header: ".participation-page-head" },
  { query: "pool=main&clan=%232YQ&step=rules", header: ".bonus-page-head" },
])(
  "real routed Results context $header has exactly one help trigger",
  async ({ query, header }) => {
    await act(async () =>
      root.render(
        <Suspense fallback={null}>
          <ResultsBonusesWorkspace
            grants={{ results: true, bonuses: true }}
            seasonId="1"
            seasons={[
              { id: 1, label: "2026-11", status: "draft", signup_open: true },
            ]}
            onSeasonChange={() => {}}
            onDirty={() => {}}
            urlState={query}
            onUrlState={() => {}}
          />
        </Suspense>,
      ),
    );
    for (let i = 0; i < 3; i++) await settle();
    expect(host.querySelector(header)).not.toBeNull();
    expect(
      host.querySelectorAll('[aria-label="How bonuses work"]'),
    ).toHaveLength(1);
    const before = api.mock.calls.length;
    await act(async () => help().click());
    expect(panel()?.open).toBe(true);
    expect(document.querySelectorAll("dialog.bonus-help-panel")).toHaveLength(
      1,
    );
    await act(async () =>
      panel()!.dispatchEvent(new Event("cancel", { cancelable: true })),
    );
    await settle();
    expect(panel()).toBeNull();
    expect(api.mock.calls).toHaveLength(before);
    expect(fetchMock).not.toHaveBeenCalled();
  },
);
