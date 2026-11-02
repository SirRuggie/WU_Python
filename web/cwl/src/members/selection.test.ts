import { expect, it } from "vitest";
import {
  selectPage,
  selectMatching,
  selectionSummary,
  toggleMember,
  confirmedTargets,
} from "./selection";
const rows = Array.from({ length: 1448 }, (_, i) => ({
  discord_id: String(100000000000000000n + BigInt(i)),
  bot: i < 3,
}));
it("Select page adds only this page, not the whole directory or bots", () => {
  const result = selectPage(new Set(), rows.slice(0, 25));
  expect(result.size).toBe(22);
  expect(result.has(rows[25].discord_id)).toBe(false);
  expect(result.has(rows[0].discord_id)).toBe(false);
});
it("Select matching excludes bots and preserves other page selections", () => {
  const old = new Set([rows[100].discord_id]);
  const next = selectMatching(old, rows.slice(0, 30));
  expect(next.size).toBe(28);
  expect(old.size).toBe(1);
  expect(next.has(rows[100].discord_id)).toBe(true);
});
it("selection survives filtering, paging and query changes, with hidden count", () => {
  const selected = selectPage(new Set(), rows.slice(3, 28));
  const visible = rows.slice(23, 48);
  expect(selectionSummary(selected, visible)).toEqual({
    count: 25,
    hidden: 20,
    all: false,
    partial: true,
  });
  expect(selectionSummary(selected, rows.slice(3, 28)).all).toBe(true);
});
it("toggling a checkbox changes exactly one ID", () => {
  const original = new Set([rows[10].discord_id]);
  const next = toggleMember(original, rows[11].discord_id);
  expect(next.size).toBe(2);
  expect(toggleMember(next, rows[10].discord_id)).toEqual(
    new Set([rows[11].discord_id]),
  );
  expect(original.size).toBe(1);
});
it("confirmed count equals immutable sent IDs and rejects bots or departed people", () => {
  const selected = selectPage(new Set(), rows.slice(3, 28));
  const payload = confirmedTargets(selected, rows);
  expect(payload.length).toBe(selectionSummary(selected, []).count);
  selected.clear();
  expect(payload.length).toBe(25);
  expect(Object.isFrozen(payload)).toBe(true);
  expect(() => confirmedTargets(new Set([rows[0].discord_id]), rows)).toThrow();
  expect(() => confirmedTargets(new Set(["missing"]), rows)).toThrow();
});
