// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikesWorkspace from "./StrikesWorkspace";

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
        strike_limit: 4,
        summary: { over_limit: 0, new_this_week: 0 },
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
  expect(
    host.querySelector('button[aria-label="How strikes work"]'),
  ).not.toBeNull();
  await click("Alpha");
  await settle();
  expect(host.textContent).toContain(
    "Streak: 3 wars played · 1 more to lose a strike",
  );
  expect(host.textContent).toContain("No records found.");
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
