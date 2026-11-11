// @vitest-environment happy-dom
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import type { ActivityAccount } from "./strikeActivityView";
import FindSlots from "./FindSlots";
import { pickOption, pickerByLabel } from "./searchPickerTestUtils";
import { parseActivityFilters } from "./strikeActivityFilters";
const viewport = vi.hoisted(() => ({ compact: false }));
vi.mock("./useCompactPreview", () => ({ default: () => viewport.compact }));
const base: ActivityAccount = {
  player_tag: "#PYY",
  player_name: "Filler one",
  current_clan_tag: "#PQQ",
  current_clan_name: "Family",
  town_hall: 14,
  weight: 143000,
  active_strikes: 3,
  total_strikes: 3,
  marked_for_replacement: true,
  status: "risk",
  quiet_days: 2,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  observed_wars: 3,
  attacked_wars: 3,
  skipped_raid_weekends: 0,
  discord_id: "100000000000000001",
  discord_name: "slayer",
};
const accounts = [
  base,
  { ...base, player_tag: "#P22", player_name: "Filler two", weight: 173000 },
];
const clans = [
  { tag: "#PQQ", name: "Family", is_fwa: true },
  { tag: "#PRR", name: "Second FWA", is_fwa: true },
  { tag: "#PGG", name: "North", is_fwa: false },
];
const candidate = (account: ActivityAccount, gap: number) => ({
  player_tag: account.player_tag,
  player_name: account.player_name,
  clan_name: "Family",
  weight: account.weight,
  weight_difference: gap,
  town_hall: 14,
  priority: "replace_first",
  active_strikes: 3,
  discord_id: account.discord_id,
  discord_name: account.discord_name,
});
const slotsFor = (url: string) =>
  new URL(url, "http://x").searchParams.getAll("weight").map((value) => ({
    weight: Number(value),
    weight_label: `${Number(value) / 1000}k`,
    candidates:
      Number(value) === 143000
        ? [{ ...candidate(accounts[0], 0), link_disputed: disputedMember }]
        : Number(value) === 999000
          ? []
          : [candidate(accounts[1], 0)],
  }));
let host: HTMLDivElement, root: Root;
let partialMember = false;
let disputedMember = false;
const replacementCalls = () =>
  vi
    .mocked(fetch)
    .mock.calls.map((call) => String(call[0]))
    .filter((url) => url.includes("/strikes/replacements"));
async function mount(url: string, choose = vi.fn()) {
  history.replaceState({}, "", url);
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={choose} />),
  );
  return choose;
}
const panelRoot = () =>
  document.querySelector<HTMLElement>(".strike-find-slots");
const field = (selector: string) =>
  document.querySelector<HTMLInputElement>(`.strike-find-slots ${selector}`)!;
const opener = () =>
  host.querySelector<HTMLButtonElement>(".strike-find-slots-open")!;
const panelOpen = () => !!document.querySelector("dialog.action-panel");
const closeTopPanel = async () =>
  act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("dialog button")]
      .filter((node) => node.getAttribute("aria-label") === "Close panel")
      .at(-1)!
      .click(),
  );
const button = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      node.textContent === label || node.getAttribute("aria-label") === label,
  )!;
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  viewport.compact = false;
  partialMember = false;
  disputedMember = false;
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) =>
    setTimeout(() => fn(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(
        JSON.stringify(
          url.includes("/strikes/replacements")
            ? {
                slots: slotsFor(url),
                member_partial: url.includes("member=") && partialMember,
              }
            : { accounts, clans },
        ),
      );
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("restores slot parameters from the link, opens the panel and runs the search once", async () => {
  await mount(
    "/strikes?view=replacements&slot_weight=143000&slot_weight=173000&slot_clan=%23PQQ&slot_member=100000000000000001",
  );
  expect(panelOpen()).toBe(true);
  expect(replacementCalls()).toHaveLength(1);
  const url = new URL(replacementCalls()[0], "http://x");
  expect(url.searchParams.getAll("weight")).toEqual(["143000", "173000"]);
  expect(url.searchParams.getAll("clan")).toEqual(["#PQQ"]);
  expect(url.searchParams.get("member")).toBe("100000000000000001");
  expect(field("input").value).toBe("143, 173");
  expect(
    [...document.querySelectorAll(".strike-slot-group h3")].map(
      (n) => n.textContent,
    ),
  ).toEqual(["143k", "173k"]);
  const first = document.querySelector(".strike-slot-group")!;
  expect(first.textContent).toContain("Filler one");
  expect(first.textContent).toContain("Chopping Block");
  expect(first.textContent).toContain("@slayer");
  expect(
    host.querySelector(".strike-activity-tabs [aria-pressed=true]")!
      .textContent,
  ).toContain("Replacements");
});

it("notes when some of the member's linked accounts were left out", async () => {
  const link =
    "/strikes?view=replacements&slot_weight=143000&slot_member=100000000000000001";
  await mount(link);
  expect(document.body.textContent).not.toContain(
    "Some linked accounts were left out.",
  );
  await act(async () => root.render(<></>));
  partialMember = true;
  await mount(link);
  expect(document.body.textContent).toContain(
    "Some linked accounts were left out.",
  );
});

it("labels a result whose tag is linked to two Discord users", async () => {
  const link = "/strikes?view=replacements&slot_weight=143000";
  await mount(link);
  expect(document.body.textContent).not.toContain(
    "Linked to two Discord users",
  );
  await act(async () => root.render(<></>));
  disputedMember = true;
  await mount(link);
  expect(document.querySelector(".strike-slot-group")!.textContent).toContain(
    "Linked to two Discord users",
  );
});

it("makes no request while typing and keeps the weights when clans change", async () => {
  await mount("/strikes?activity_view=replacements");
  await act(async () => opener().click());
  const input = field("input");
  await type(input, "143, 173k");
  await type(input, "143, 173k, 150000");
  expect(replacementCalls()).toHaveLength(0);
  await act(async () => button("Find").click());
  expect(
    new URL(replacementCalls()[0], "http://x").searchParams.getAll("weight"),
  ).toEqual(["143000", "173000", "150000"]);
  expect(location.search).toContain("slot_weight=143000");
  // Only FWA clans are offered.
  await act(async () => button("Clans: All FWA clans").click());
  const names = [...document.querySelectorAll("dialog label span")].map(
    (node) => node.textContent,
  );
  expect(names).toContain("Second FWA");
  expect(names).not.toContain("North");
  await act(async () =>
    [
      ...document.querySelectorAll<HTMLInputElement>(
        "dialog input[type=checkbox]",
      ),
    ]
      .find((box) => box.parentElement!.textContent!.startsWith("Second FWA"))!
      .click(),
  );
  await closeTopPanel();
  expect(input.value).toBe("143, 173, 150");
  await act(async () => button("Find").click());
  expect(replacementCalls()).toHaveLength(2);
  const second = new URL(replacementCalls()[1], "http://x").searchParams;
  expect(second.getAll("clan")).toEqual(["#PRR"]);
  expect(second.getAll("weight")).toEqual(["143000", "173000", "150000"]);
});

it("names an invalid value, limits to five weights and does not search", async () => {
  await mount("/strikes?activity_view=replacements");
  await act(async () => opener().click());
  const input = field("input");
  await type(input, "143, abc");
  await act(async () => button("Find").click());
  expect(field("[role=alert]").textContent).toContain("“abc”");
  await type(input, "1,2,3,4,5,6");
  await act(async () => button("Find").click());
  expect(field("[role=alert]").textContent).toBe("Enter up to 5 weights.");
  expect(replacementCalls()).toHaveLength(0);
});

it("shows an empty group message, then closes the panel and opens the selected result", async () => {
  const choose = await mount(
    "/strikes?activity_view=replacements&slot_weight=143000&slot_weight=999000",
  );
  const groups = [...document.querySelectorAll(".strike-slot-group")];
  expect(groups[1].textContent).toContain("No slot in these clans.");
  await act(async () =>
    groups[0].querySelector<HTMLButtonElement>("li button")!.click(),
  );
  expect(choose).toHaveBeenCalledOnce();
  expect(choose.mock.calls[0][0].player_tag).toBe("#PYY");
  expect(panelOpen()).toBe(false);
});

it("keeps an FWA clan prefilled by Find a fill for this slot and drops a non-FWA one", async () => {
  // The same query App builds in onFindReplacement, against the backend clan shape.
  const prefill = new URLSearchParams({ activity_view: "replacements" });
  prefill.append("slot_weight", "143000");
  prefill.append("slot_clan", "#PQQ");
  prefill.append("slot_clan", "#PGG");
  await mount(`/strikes?${prefill}`);
  expect(replacementCalls()).toHaveLength(1);
  expect(
    new URL(replacementCalls()[0], "http://x").searchParams.getAll("clan"),
  ).toEqual(["#PQQ"]);
  expect(panelRoot()!.textContent).toContain("Family");
});

it("opens Replacements with the button, a closed panel and no search when a link has no weights", async () => {
  await mount("/strikes?view=replacements&slot_clan=%23PQQ");
  expect(
    host.querySelector(".strike-activity-tabs [aria-pressed=true]")!
      .textContent,
  ).toContain("Replacements");
  expect(opener()).not.toBeNull();
  expect(panelOpen()).toBe(false);
  expect(replacementCalls()).toHaveLength(0);
  await act(async () => opener().click());
  expect(panelRoot()!.textContent).toContain("Family");
  expect(replacementCalls()).toHaveLength(0);
});

it("shows the button only on the Replacements tab", async () => {
  await mount("/strikes?activity_view=all");
  expect(opener()).toBeNull();
  expect(panelOpen()).toBe(false);
  expect(host.textContent).not.toContain("Find slots");
  await act(async () => root.render(<></>));
  await mount("/strikes?activity_view=replacements");
  expect(opener().textContent).toBe("Find slots");
});

it("lays Find slots out as weights plus Find, then clan and member halves", async () => {
  await mount("/strikes?view=replacements");
  await act(async () => opener().click());
  const top = document.querySelector(".strike-find-slots-top")!;
  expect(top.querySelector("input")).not.toBeNull();
  expect(top.querySelector("button")!.textContent).toBe("Find");
  const row = document.querySelector(".strike-find-slots-row")!;
  expect(
    [...row.children].map((node) => node.getAttribute("aria-label")),
  ).toEqual(["Clans: All FWA clans", "Member: any"]);
});

it("names a result from the account row when the endpoint has no name, never an ID", async () => {
  const bare = (account: ActivityAccount) => ({
    ...candidate(account, 0),
    discord_name: null,
  });
  const rows = [
    accounts[0],
    { ...accounts[1], discord_id: "100000000000000002", discord_name: null },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(
        JSON.stringify(
          url.includes("/strikes/replacements")
            ? {
                slots: [
                  {
                    weight: 143000,
                    weight_label: "143k",
                    candidates: [bare(rows[0]), bare(rows[1])],
                  },
                ],
              }
            : { accounts: rows, clans },
        ),
      );
    }),
  );
  await mount("/strikes?view=replacements&slot_weight=143000");
  const items = [...document.querySelectorAll(".strike-slot-group li")].map(
    (node) => node.textContent!,
  );
  expect(items[0]).toContain("@slayer");
  expect(items[1]).not.toContain("@");
  expect(items[1]).not.toMatch(/\d{15}/);
});

it("opens from the gold button on phones and desktop with no request on open or close", async () => {
  for (const compact of [true, false]) {
    viewport.compact = compact;
    await mount("/strikes?activity_view=replacements");
    expect(opener().classList.contains("primary")).toBe(true);
    expect(opener().textContent).toBe("Find slots");
    expect(panelOpen()).toBe(false);
    const calls = vi.mocked(fetch).mock.calls.length;
    const url = location.href;
    await act(async () => opener().click());
    expect(panelOpen()).toBe(true);
    expect(
      document.querySelector("dialog .action-panel-heading h2")!.textContent,
    ).toBe("Find slots");
    expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
    // The Weights field is never focused: no keyboard on phones.
    expect(document.activeElement).not.toBe(field("input"));
    await closeTopPanel();
    expect(panelOpen()).toBe(false);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
    expect(location.href).toBe(url);
    await act(async () => root.render(<></>));
  }
});

it("keeps the last weights and results across close and reopen without a new search", async () => {
  await mount("/strikes?activity_view=replacements");
  await act(async () => opener().click());
  await type(field("input"), "143, 173k");
  await act(async () => button("Find").click());
  expect(replacementCalls()).toHaveLength(1);
  const result = document.querySelector(".strike-slot-group")!.textContent;
  await closeTopPanel();
  expect(panelOpen()).toBe(false);
  await act(async () => opener().click());
  expect(field("input").value).toBe("143, 173");
  expect(document.querySelector(".strike-slot-group")!.textContent).toBe(
    result,
  );
  expect(replacementCalls()).toHaveLength(1);
});

it("opens a URL search once without moving focus to Weights and does not reopen after close", async () => {
  const outside = document.createElement("button");
  document.body.append(outside);
  outside.focus();
  await mount(
    "/strikes?view=replacements&slot_weight=143000&slot_weight=173000&slot_weight=150000",
  );
  expect(panelOpen()).toBe(true);
  expect(document.activeElement).not.toBe(field("input"));
  expect(replacementCalls()).toHaveLength(1);
  await closeTopPanel();
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  expect(panelOpen()).toBe(false);
  expect(replacementCalls()).toHaveLength(1);
  outside.remove();
});

it("keeps unsaved weights, clan and member selections while the panel is closed", async () => {
  await mount("/strikes?view=replacements");
  await act(async () => opener().click());
  await type(field("input"), "143, 173k");
  await act(async () => button("Clans: All FWA clans").click());
  await act(async () =>
    [
      ...document.querySelectorAll<HTMLInputElement>(
        "dialog input[type=checkbox]",
      ),
    ]
      .find((box) => box.parentElement!.textContent!.startsWith("Second FWA"))!
      .click(),
  );
  await closeTopPanel();
  await act(async () => button("Member: any").click());
  await pickOption(pickerByLabel(document, "Discord member"), "slayer", "slay");
  await closeTopPanel();
  expect(panelOpen()).toBe(false);
  await act(async () => opener().click());
  expect(field("input").value).toBe("143, 173k");
  expect(button("Clans: Second FWA")).toBeDefined();
  expect(button("Member: @slayer")).toBeDefined();
  expect(replacementCalls()).toHaveLength(0);
});

it("retains a search error received while the panel is closed and shows it on reopen without retry", async () => {
  const normal = vi.mocked(fetch).getMockImplementation()!;
  let release!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/strikes/replacements")
        ? new Promise<Response>((resolve) => {
            release = resolve;
          })
        : normal(input, init),
    ),
  );
  await mount("/strikes?view=replacements&slot_weight=143000");
  expect(button("Finding…").getAttribute("aria-busy")).toBe("true");
  await closeTopPanel();
  await act(async () =>
    release(
      new Response(JSON.stringify({ error: "Fixture slots unavailable" }), {
        status: 503,
        headers: { "X-Read-Retries-Exhausted": "1" },
      }),
    ),
  );
  const calls = vi.mocked(fetch).mock.calls.length;
  await act(async () => opener().click());
  expect(field("[role=alert]").textContent).toContain(
    "Fixture slots unavailable",
  );
  expect(field("input").value).toBe("143");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
});

function HistorySlots() {
  const [query, setQuery] = useState(location.search);
  useEffect(() => {
    const restore = () => setQuery(location.search);
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  return (
    <FindSlots
      clans={clans}
      accounts={accounts}
      search={parseActivityFilters(query)}
      onSearch={vi.fn()}
      onChoose={vi.fn()}
    />
  );
}

it("reopens Back/Forward URL weights once each time they change, without focusing Weights", async () => {
  history.replaceState({}, "", "/strikes?view=replacements&slot_weight=143000");
  await act(async () => root.render(<HistorySlots />));
  expect(replacementCalls()).toHaveLength(1);
  expect(panelOpen()).toBe(true);
  await closeTopPanel();
  for (const weight of [173000, 143000]) {
    await act(async () => {
      history.replaceState(
        {},
        "",
        `/strikes?view=replacements&slot_weight=${weight}`,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(panelOpen()).toBe(true);
    expect(document.activeElement).not.toBe(field("input"));
    expect(field("input").value).toBe(String(weight / 1000));
    await closeTopPanel();
  }
  expect(replacementCalls()).toHaveLength(3);
});

it("keeps Find slots mounted when the viewport crosses the phone width", async () => {
  viewport.compact = false;
  await mount("/strikes?activity_view=replacements");
  await act(async () => opener().click());
  await type(field("input"), "143, 173");
  await closeTopPanel();
  const before = opener();
  const calls = vi.mocked(fetch).mock.calls.length;
  for (const compact of [true, false]) {
    viewport.compact = compact;
    await act(async () =>
      root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
    );
    expect(opener()).toBe(before);
    expect(panelOpen()).toBe(false);
  }
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
  await act(async () => opener().click());
  expect(field("input").value).toBe("143, 173");
  expect(replacementCalls()).toHaveLength(0);
});

it("replaces the history entry for a search run in the panel and keeps the results after Back", async () => {
  history.replaceState({}, "", "/strikes");
  const pushes: boolean[] = [];
  const states: string[] = [];
  const view = (state: string) => (
    <StrikeActivityRoster
      state={state}
      onState={(next, push) => {
        states.push(next);
        pushes.push(push);
      }}
      onChoose={vi.fn()}
    />
  );
  await act(async () => root.render(view("activity_view=replacements")));
  await act(async () => opener().click());
  await type(field("input"), "143, 173k");
  await act(async () => button("Find").click());
  expect(replacementCalls()).toHaveLength(1);
  expect(pushes).toEqual([false]);
  expect(states[0]).toContain("slot_weight=143000");
  const result = document.querySelector(".strike-slot-group")!.textContent;
  await act(async () => root.render(view(states[0])));
  // Back from the open panel lands on the entry without slot keys.
  await act(async () => root.render(view("activity_view=replacements")));
  expect(panelOpen()).toBe(true);
  expect(field("input").value).toBe("143, 173");
  expect(document.querySelector(".strike-slot-group")!.textContent).toBe(
    result,
  );
  expect(replacementCalls()).toHaveLength(1);
});
