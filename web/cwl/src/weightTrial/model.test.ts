import { expect, it } from "vitest";
import { draftFor, editDraft, validateDraft, warLoot } from "./model";
it("links loot and full weight, including changes to storages", () => {
  const draft = { storages: "5", loot: "29800", full: "149000" };
  expect(validateDraft(draft)).toEqual({ storages: 5, weight: 149000 });
  expect(editDraft(draft, "full", "150,000").loot).toBe("30000");
  expect(editDraft(draft, "storages", "4").full).toBe("119200");
  expect(() => validateDraft(editDraft(draft, "full", "149001"))).toThrow();
  expect(() => validateDraft(editDraft(draft, "storages", "0"))).toThrow();
  expect(validateDraft(editDraft(draft, "loot", "")).weight).toBeNull();
});
it("copies only complete war rows in map order, never clan display order", () => {
  const rows = [
    { tag: "#P2Y", name: "First", town_hall: 16, weight: 149000, revision: 0 },
    { tag: "#Q2Y", name: "Second", town_hall: 16, weight: 150000, revision: 0 },
  ];
  const drafts = Object.fromEntries(
    rows.map((row) => [row.tag, draftFor(row)]),
  );
  expect(warLoot(rows, drafts, { "#P2Y": 2, "#Q2Y": 1 })).toBe("30000\n29800");
  expect(() => warLoot(rows, drafts, null)).toThrow();
  expect(() => warLoot(rows, drafts, { "#P2Y": 2 })).toThrow();
  expect(() => warLoot(rows, drafts, { "#G2Y": 1 })).toThrow();
  expect(() =>
    warLoot(
      rows,
      { ...drafts, "#P2Y": { storages: "5", loot: "", full: "" } },
      { "#P2Y": 1 },
    ),
  ).toThrow();
});
import { pasteColumn } from "./model";
it("pastes loot as one atomic column and rejects overflow or multiple columns", () => {
  const rows = [
    { tag: "#P2Y", name: "Test", town_hall: 16, weight: null, revision: 0 },
  ];
  const drafts = { "#P2Y": draftFor(rows[0]) };
  expect(pasteColumn(rows, drafts, 0, "loot", "29,800\n")["#P2Y"].full).toBe(
    "149000",
  );
  expect(() => pasteColumn(rows, drafts, 0, "loot", "29800\n30000")).toThrow();
  expect(() => pasteColumn(rows, drafts, 0, "loot", "29800\t30000")).toThrow();
  expect(drafts["#P2Y"].full).toBe("");
});

import { orderedMembers, orderLabel } from "./model";
it("shows war map order before non-war members regardless of clan rank", () => {
  const rows = [1, 2, 3].map((n) => ({
    tag: `#P${n}`,
    name: `Player ${n}`,
    town_hall: 18,
    weight: null,
    revision: 0,
    clan_position: n,
  }));
  const roster = {
    clan: { tag: "#P0", name: "Test" },
    members: rows,
    checked_at: "",
    war_order: { "#P2": 2, "#P3": 1 },
    war_source: { state: "preparation" },
  };
  expect(orderedMembers(roster).map((row) => row.tag)).toEqual([
    "#P3",
    "#P2",
    "#P1",
  ]);
  expect(rows.map((row) => row.tag)).toEqual(["#P1", "#P2", "#P3"]);
  expect(orderLabel(roster)).toContain("Preparation");
  expect(
    orderLabel({ ...roster, war_source: { state: "warEnded" } }),
  ).toContain("Last completed");
  expect(orderLabel({ ...roster, war_order: null })).toContain(
    "War lineup unavailable",
  );
  expect(
    orderedMembers({ ...roster, war_order: null }).map((row) => row.tag),
  ).toEqual(["#P1", "#P2", "#P3"]);
});

import { sheetWeightWarning } from "./model";
it("matches sheet limits and thousand checks without changing weights", () => {
  const row = {
    tag: "#P2Y",
    name: "Test",
    town_hall: 18,
    weight: 149000,
    revision: 1,
  };
  const check = (weight: number | null) =>
    sheetWeightWarning(row.tag, [{ ...row, weight }], {}, null);
  expect(check(1000)).toContain("42,000");
  expect(check(181000)).toContain("180,000");
  expect(check(149005)).toContain("000");
  for (const weight of [null, 42000, 149000, 180000])
    expect(check(weight)).toBe("");
  expect(row.weight).toBe(149000);
});
it("compares adjacent actual war positions and reacts to unsaved edits", () => {
  const rows = [
    { tag: "A", name: "First", town_hall: 18, weight: 150000, revision: 1 },
    { tag: "B", name: "Next", town_hall: 18, weight: 149000, revision: 1 },
  ];
  const order = { A: 1, B: 2 };
  const drafts = { A: { storages: "5", loot: "200", full: "1000" } };
  expect(sheetWeightWarning("B", rows, drafts, order)).toContain("player 1");
  expect(sheetWeightWarning("B", rows, {}, order)).toBe("");
  expect(sheetWeightWarning("B", rows, drafts, null)).toBe("");
  expect(sheetWeightWarning("B", rows, drafts, { A: 1, B: 3 })).toBe("");
  expect(sheetWeightWarning("B", rows, drafts, { A: 1 })).toBe("");
  for (const full of ["", "=123", "abc"])
    expect(
      sheetWeightWarning(
        "B",
        rows,
        { A: { storages: "5", loot: "", full } },
        order,
      ),
    ).toBe("");
  expect(rows[0].weight).toBe(150000);
});

it("labels persisted ordering as saved rather than current", () => {
  const text = orderLabel({
    clan: { tag: "#R2Y", name: "Family" },
    members: [],
    checked_at: "",
    war_order: { "#P2Y": 1 },
    war_source: {
      state: "inWar",
      cached: true,
      captured_at: "2026-10-21T12:00:00Z",
    },
  });
  expect(text).toContain("Saved war lineup");
  expect(text).toContain("Check this matches the spreadsheet");
  expect(text).not.toContain("Current war");
});

it("normalizes equivalent loot forms and formats full weights without rounding writes", () => {
  const blank = { storages: "5", loot: "", full: "" };
  for (const text of ["35800", "35,800", "35.8k", "35.8K"]) {
    expect(validateDraft(editDraft(blank, "loot", text))).toEqual({
      storages: 5,
      weight: 179000,
    });
  }
  for (const text of ["3,58,00", "35.8001k", "1e5", "12cats"])
    expect(() => validateDraft(editDraft(blank, "loot", text))).toThrow();
});
