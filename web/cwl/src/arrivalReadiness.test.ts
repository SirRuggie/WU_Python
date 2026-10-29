import { expect, it } from "vitest";
import { summarizeArrivalReadiness } from "./arrivalReadiness";
const now = Date.parse("2026-10-28T12:00:00Z");
const players = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    tag: `#${i}`,
    assigned_clan_tag: "#HOST",
    current_clan_tag: "#HOST",
    current_clan_name: "Host",
    current_clan_checked_at: new Date(now).toISOString(),
  }));
it.each([15, 30])(
  "requires %i fresh arrivals, not every assigned player",
  (capacity) => {
    expect(
      summarizeArrivalReadiness(players(capacity - 1), { now, capacity }).ready,
    ).toBe(false);
    const accounts = [
      ...players(capacity),
      { ...players(1)[0], tag: "#LATE", current_clan_tag: "#ELSE" },
    ];
    expect(
      summarizeArrivalReadiness(accounts, { now, capacity }),
    ).toMatchObject({
      ready: true,
      arrivedCount: capacity,
      assignedCount: capacity + 1,
    });
  },
);
it("null war size is never ready", () =>
  expect(
    summarizeArrivalReadiness(players(50), { now, capacity: null }).ready,
  ).toBe(false));
it("keeps old arrival counts but requests confirmation only when fresh arrivals are insufficient", () => {
  const accounts = players(16);
  accounts[0].current_clan_checked_at = new Date(now - 300001).toISOString();
  expect(summarizeArrivalReadiness(accounts, { now, capacity: 15 }).ready).toBe(
    true,
  );
  accounts[1].current_clan_checked_at = new Date(now - 300001).toISOString();
  expect(
    summarizeArrivalReadiness(accounts, { now, capacity: 15 }),
  ).toMatchObject({
    ready: false,
    refreshToConfirm: true,
    arrivedCount: 16,
    freshCount: 14,
  });
});
it("ignores unassigned and unchecked accounts", () => {
  expect(
    summarizeArrivalReadiness(
      [
        ...players(14),
        { ...players(1)[0], assigned_clan_tag: null },
        { ...players(1)[0], current_clan_checked_at: undefined },
      ],
      { now, capacity: 15 },
    ).ready,
  ).toBe(false);
});
