// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import type { ActivityAccount } from "./strikeActivityView";
const row: ActivityAccount = {
  player_tag: "#PYY",
  player_name: "Fixture healthy",
  current_clan_tag: "#PQQ",
  current_clan_name: "Family",
  town_hall: 16,
  weight: 149000,
  active_strikes: 0,
  total_strikes: 0,
  marked_for_replacement: false,
  status: "active",
  quiet_days: 0,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  observed_wars: 3,
  attacked_wars: 3,
  skipped_raid_weekends: 0,
};
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/strikes?view=all");
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
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            accounts: [
              row,
              {
                ...row,
                player_tag: "#PQQ",
                player_name: "Risk fixture",
                active_strikes: 3,
                total_strikes: 3,
                marked_for_replacement: true,
                status: "risk",
                quiet_days: 14,
                no_attack_wars: 3,
                attacked_wars: 0,
                missed_attacks: 6,
                observed_attacks: 6,
              },
            ],
            clans: [{ tag: "#PQQ", name: "Family" }],
          }),
        ),
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("loads the family once, keeps weight tool closed, and row selection only navigates", async () => {
  const choose = vi.fn();
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={choose} />),
  );
  expect(host.textContent).toContain("Showing 2 of 2");
  expect(host.textContent).not.toContain("at risk");
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(2);
  expect(host.textContent).toContain("Quiet 0d");
  expect(host.textContent).toContain("Missed last 3 wars");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click(),
  );
  expect(choose.mock.calls[0][0].player_name).toBe("Fixture healthy");
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(
        ([, options]) => !options?.method || options.method === "GET",
      ),
  ).toBe(true);
});
it("replacements alias starts with marked filter and preserves URL changes", async () => {
  history.replaceState({}, "", "/replacements");
  await act(async () =>
    root.render(<StrikeActivityRoster markedDefault onChoose={vi.fn()} />),
  );
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(1);
  const all = [
    ...host.querySelectorAll<HTMLButtonElement>(".strike-activity-tabs button"),
  ].find((b) => b.textContent?.startsWith("All"))!;
  await act(async () => all.click());
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(2);
  expect(new URLSearchParams(location.search).get("marked")).toBe("0");
});
it("permission loss clears loaded protected rows", async () => {
  const denied = vi.fn();
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} onDenied={denied} />),
  );
  vi.mocked(fetch).mockImplementation(
    async () =>
      new Response(JSON.stringify({ error: "No strike access" }), {
        status: 403,
      }),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Refresh activity")!
      .click(),
  );
  expect(denied).toHaveBeenCalledOnce();
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(0);
  expect(host.querySelector("[role=alert]")).not.toBeNull();
});

it("loads recruit matches only on request and ignores a response after the weight changes", async () => {
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  const disclosure = [...host.querySelectorAll("details")].find(
    (node) =>
      node.querySelector("summary")?.textContent === "Match a recruit’s weight",
  )!;
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  await act(async () => {
    disclosure.open = true;
    disclosure.dispatchEvent(new Event("toggle"));
  });
  let finish!: (response: Response) => void;
  vi.mocked(fetch).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const input = host.querySelector<HTMLInputElement>(
    ".strike-activity-recruit input",
  )!;
  async function weight(value: string) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await weight("149");
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((node) => node.textContent === "Find closest weights")!
      .click(),
  );
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  await weight("150");
  await act(async () =>
    finish(
      new Response(
        JSON.stringify({
          candidates: [
            {
              player_tag: "#PYY",
              player_name: "Stale match",
              weight: 149000,
              clan_name: "Family",
            },
          ],
        }),
      ),
    ),
  );
  expect(host.textContent).not.toContain("Stale match");
  expect(input.value).toBe("150");
  expect(
    [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (node) => node.textContent === "Find closest weights",
    )!.disabled,
  ).toBe(false);
});

it("selection controls are manager-only and Select all covers the current filter", async () => {
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} canManage={false} />),
  );
  expect(host.textContent).not.toContain("Select accounts");
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} canManage />),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select accounts")!
      .click(),
  );
  const all = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Select all (2)",
  )!;
  await act(async () => all.click());
  expect(
    host.querySelectorAll('input[aria-label^="Select "]:checked'),
  ).toHaveLength(2);
  expect(host.textContent).toContain("2 selected");
});

it("failure shows unavailable counts instead of a false zero summary", async () => {
  vi.mocked(fetch).mockImplementation(
    async () =>
      new Response(JSON.stringify({ error: "Fixture unavailable" }), {
        status: 503,
        headers: { "X-Read-Retries-Exhausted": "1" },
      }),
  );
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  expect(host.textContent).toContain("Activity unavailable");
  expect(host.textContent).toContain("Fixture unavailable");
});

it("state-driven filters and explicit Discard clear selection", async () => {
  const choose = vi.fn();
  await act(async () =>
    root.render(
      <StrikeActivityRoster state="?view=all" onChoose={choose} canManage />,
    ),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select accounts")!
      .click(),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select all (2)")!
      .click(),
  );
  expect(host.textContent).toContain("2 selected");
  expect(
    host.querySelector('[aria-label="Selected accounts"]')!.textContent,
  ).toContain("Fixture healthy");
  await act(async () =>
    root.render(
      <StrikeActivityRoster
        state="?view=all&q=Risk"
        onChoose={choose}
        canManage
      />,
    ),
  );
  expect(
    host.querySelector('[aria-label="Mark selected replacements"]'),
  ).toBeNull();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select accounts")!
      .click(),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select all (1)")!
      .click(),
  );
  await act(async () =>
    root.render(
      <StrikeActivityRoster
        state="?view=all&q=Risk"
        selectionReset={1}
        onChoose={choose}
        canManage
      />,
    ),
  );
  expect(
    host.querySelector('[aria-label="Mark selected replacements"]'),
  ).toBeNull();
});

it("disables oversized Select all and explains how to enable it", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            accounts: Array.from({ length: 125 }, (_, n) => ({
              ...row,
              player_tag: `#P${n}`,
            })),
            clans: [{ tag: "#PQQ", name: "Family" }],
          }),
        ),
    ),
  );
  await act(async () =>
    root.render(
      <StrikeActivityRoster state="?view=all" onChoose={vi.fn()} canManage />,
    ),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select accounts")!
      .click(),
  );
  const selectAll = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Select all (125)",
  )!;
  expect(selectAll.disabled).toBe(true);
  expect(host.textContent).toContain("Filter to 50 or fewer to select all.");
});

it("makes a cold Discord-name search find the row without reloading or replacing strike state", async () => {
  vi.useFakeTimers();
  try {
    history.replaceState({}, "", "/strikes?view=all&q=Resolved%20member");
    vi.mocked(fetch)
      .mockReset()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            accounts: [row],
            clans: [],
            identity_updating: true,
            identity_warning: "Names loading",
          }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            accounts: [
              { ...row, discord_name: "Resolved member", active_strikes: 99 },
            ],
            clans: [],
            identity_updating: false,
          }),
        ),
      );
    const choose = vi.fn();
    await act(async () =>
      root.render(<StrikeActivityRoster onChoose={choose} />),
    );
    expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(0);
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(1);
    await act(async () =>
      host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click(),
    );
    expect(choose.mock.calls[0][0].discord_name).toBe("Resolved member");
    expect(choose.mock.calls[0][0].active_strikes).toBe(0);
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});

it("defaults to known three-war misses and exposes the threshold chip", async () => {
  history.replaceState({}, "", "/strikes");
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} canManage />),
  );
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(1);
  expect(host.querySelector(".strike-activity-row")!.textContent).toContain(
    "Risk fixture",
  );
  expect(host.textContent).toContain("No attacks in last 3+ known wars");
  expect(host.textContent).not.toContain("at risk");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select accounts")!
      .click(),
  );
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Select all (1)")!
      .click(),
  );
  expect(host.textContent).toContain("1 selected");
  expect(host.querySelector(".strike-tab-predicate")).not.toBeNull();
});

it("copies every matching account across pages and reports clipboard refusal", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            accounts: Array.from({ length: 65 }, (_, index) => ({
              ...row,
              player_tag: `#P${index}`,
              player_name: `Account ${index}`,
            })),
            clans: [],
          }),
        ),
    ),
  );
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(25);
  const copy = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Copy list",
  )!;
  await act(async () => copy.click());
  expect(writeText.mock.calls[0][0].split("\n")).toHaveLength(65);
  expect(host.textContent).toContain("Copied 65 accounts");
  writeText.mockRejectedValueOnce(new Error("Denied"));
  await act(async () => copy.click());
  expect(host.textContent).toContain("Copy failed");
});

it("table headers change the same sort and direction shown in the toolbar", async () => {
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  const header = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Sort by Strikes"]',
  )!;
  await act(async () => header.click());
  expect(
    host.querySelector<HTMLSelectElement>('select[aria-label="Sort accounts"]')!
      .value,
  ).toBe("strikes");
  expect(host.querySelector("th[aria-sort=descending]")!.textContent).toContain(
    "Strikes",
  );
  expect(host.querySelector("[data-strike-player]")!.textContent).toContain(
    "Risk fixture",
  );
  await act(async () => header.click());
  expect(host.querySelector("th[aria-sort=ascending]")!.textContent).toContain(
    "Strikes",
  );
  expect(host.querySelector("[data-strike-player]")!.textContent).toContain(
    "Fixture healthy",
  );
});
it("keeps Not attacking when applying another filter", async () => {
  history.replaceState({}, "", "/strikes");
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((b) => b.textContent === "Filters")!
      .click(),
  );
  const label = [...document.querySelectorAll("dialog label")].find((l) =>
    l.textContent?.startsWith("Quiet days"),
  )!;
  await act(async () => {
    const select = label.querySelector("select")!;
    select.value = "7";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("dialog button")]
      .find((b) => b.textContent === "Apply filters")!
      .click(),
  );
  const active = host.querySelector(
    '.strike-activity-tabs [aria-pressed="true"]',
  )!;
  expect(active.textContent).toContain("Not attacking");
  expect(active.textContent).toContain("1");
  expect(host.textContent).toContain("Showing 1 of 2");
});
it("clears extra filters without changing the selected All tab", async () => {
  history.replaceState({}, "", "/strikes?activity_view=all&q=Missing");
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(0);
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((b) => b.textContent === "Clear filters")!
      .click(),
  );
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(2);
  expect(
    host.querySelector('.strike-activity-tabs [aria-pressed="true"]')!
      .textContent,
  ).toContain("All");
});
it("closes the Copy menu and clears a brief toast when filters change", async () => {
  vi.useFakeTimers();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
  try {
    await act(async () =>
      root.render(
        <StrikeActivityRoster state="?activity_view=all" onChoose={vi.fn()} />,
      ),
    );
    const menu = host.querySelector<HTMLDetailsElement>(
      ".strike-activity-actions",
    )!;
    menu.open = true;
    await act(async () =>
      [...host.querySelectorAll<HTMLButtonElement>("button")]
        .find((b) => b.textContent === "Copy list")!
        .click(),
    );
    expect(menu.open).toBe(false);
    expect(host.querySelector(".strike-copy-toast")!.textContent).toContain(
      "Copied 2",
    );
    await act(async () =>
      root.render(
        <StrikeActivityRoster
          state="?activity_view=all&q=Risk"
          onChoose={vi.fn()}
        />,
      ),
    );
    expect(host.querySelector(".strike-copy-toast")).toBeNull();
    expect(host.textContent).toContain("Showing 1 of 2");
    await act(async () =>
      [...host.querySelectorAll<HTMLButtonElement>("button")]
        .find((b) => b.textContent === "Copy list")!
        .click(),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4001);
    });
    expect(host.querySelector(".strike-copy-toast")).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});
