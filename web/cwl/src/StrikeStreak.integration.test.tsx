// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikesWorkspace from "./StrikesWorkspace";
import ReplacementWorkspace from "./ReplacementWorkspace";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
vi.mock("./StrikeTrackingStatus", () => ({ default: () => null }));
let host: HTMLDivElement;
let root: Root;
const settle = async () => {
  await act(async () => vi.advanceTimersByTimeAsync(200));
};
const click = async (name: string) => {
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((item) => item.textContent?.includes(name))!
      .click(),
  );
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  transport.mockReset();
  sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});

it("shows the account-scoped streak independently of records and rejects late prior-account data", async () => {
  let finishOld!: (value: object) => void;
  let oldPending = false;
  transport.mockImplementation((path: string) => {
    if (path.startsWith("/strikes/accounts"))
      return Promise.resolve({
        clans: [],
        total: 2,
        accounts: ["Alpha", "Birch"].map((name) => ({
          player_tag: `#${name}`,
          player_name: name,
          active_strikes: 2,
          total_strikes: 2,
        })),
      });
    if (path.includes("%23Alpha") && oldPending)
      return new Promise((resolve) => {
        finishOld = resolve;
      });
    if (path.startsWith("/strikes/overview"))
      return Promise.resolve({
        entries: [],
        clans: [],
        total: 0,
        streak: {
          count: path.includes("%23Alpha") ? 3 : 1,
          last_war_key: "war",
        },
      });
    throw new Error(`Unexpected read: ${path}`);
  });
  await act(async () =>
    root.render(
      <StrikesWorkspace
        permissions={["strikes_remove"]}
        isOwner={false}
        userId="1"
      />,
    ),
  );
  await settle();
  expect(host.textContent).toContain("How strikes work");
  await click("Alpha");
  await settle();
  expect(host.textContent).toContain(
    "Streak: 3 wars played · 1 more to lose a strike",
  );
  expect(host.textContent).toContain("No strikes found.");
  await click("← Players");
  await settle();
  oldPending = true;
  await click("Alpha");
  await settle();
  await click("← Players");
  await settle();
  await click("Birch");
  expect(host.textContent).not.toContain("Streak: 3 wars played");
  await settle();
  await act(async () =>
    finishOld({ entries: [], total: 0, clans: [], streak: { count: 5 } }),
  );
  expect(host.textContent).toContain(
    "Streak: 1 war played · 1 more to lose a strike",
  );
  expect(host.textContent).not.toContain("Streak: 5 wars played");
  expect(
    transport.mock.calls.every((call) => !call[1] || call[1] === "GET"),
  ).toBe(true);
});

it("shows grace only for confirmed departures and names the last observed clan/time", async () => {
  transport.mockResolvedValue({
    clans: [],
    candidates: [
      {
        player_tag: "#LEFT",
        player_name: "Departed",
        active_strikes: 1,
        clan_tag: "#OLD",
        clan_name: "Old Clan",
        departed: true,
        last_seen_clan_tag: "#OLD",
        last_seen_clan_name: "Observed Clan",
        current_clan_tag: "#NEW",
        current_clan_name: "New Clan",
        last_seen_at: "2026-10-30T12:00:00Z",
        clan_is_current: false,
      },
      {
        player_tag: "#STALE",
        player_name: "Stale roster",
        active_strikes: 1,
        clan_tag: "#OLD",
        clan_name: "Old Clan",
        clan_is_current: false,
      },
    ],
  });
  await act(async () =>
    root.render(
      <ReplacementWorkspace permissions={["strikes_remove"]} isOwner={false} />,
    ),
  );
  await settle();
  expect(host.querySelectorAll(".replacement-departure")).toHaveLength(1);
  expect(host.textContent).toContain("Left Observed Clan");
  expect(host.textContent).toContain("now in New Clan");
  const departureDetails = host.querySelector('.replacement-departure details')!;
  expect(departureDetails.hasAttribute('open')).toBe(false);
  await act(async () => (departureDetails.querySelector('summary') as HTMLElement).click());
  expect(departureDetails.hasAttribute('open')).toBe(true);
  expect(host.querySelector("time")?.getAttribute("datetime")).toBe(
    "2026-10-30T12:00:00.000Z",
  );
  expect(host.querySelectorAll(".replacement-row")).toHaveLength(2);
  expect(
    transport.mock.calls.every((call) => !call[1] || call[1] === "GET"),
  ).toBe(true);
});
