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

import { whole } from "./model";
it("parses every one- and two-decimal k value in the accepted range exactly", () => {
  for (const places of [1, 2]) {
    const scale = 10 ** places;
    for (let digits = 1; digits * (1000 / scale) <= 999999; digits++) {
      const text = `${Math.floor(digits / scale)}.${String(digits % scale).padStart(places, "0")}k`;
      expect(whole(text, 999999), text).toBe(digits * (1000 / scale));
    }
  }
  for (const text of ["32.2k", "32.20k", "32.2000k", "32,200", "32200.00"])
    expect(whole(text, 999999)).toBe(32200);
  for (const text of [
    "0",
    "0.0001k",
    "1.001",
    "999.9991k",
    "1000k",
    "1e3",
    "NaN",
    "3,22k",
    "999999999999999999k",
  ])
    expect(() => whole(text, 999999), text).toThrow();
});

it("does not guess storages for an unknown saved-lineup Town Hall", () => {
  const row = {
    tag: "#G2Y",
    name: "Departed",
    town_hall: null,
    weight: null,
    revision: 0,
    current_member: false,
  };
  expect(draftFor(row)).toEqual({ storages: "", loot: "", full: "" });
  expect(() => validateDraft(draftFor(row))).toThrow("Choose storages");
  expect(draftFor({ ...row, weight: 140000, storages: 4 })).toEqual({
    storages: "4",
    loot: "35000",
    full: "140000",
  });
});

import { selectedRoster, draftsForRoster } from "./model";
it("uses selected-war details for departed people and saved per-player storage across wars", () => {
  const current = {
    tag: "#P2Y",
    name: "Current name",
    town_hall: 17,
    weight: null,
    revision: 0,
    current_member: true,
  };
  const left = {
    tag: "#G2Y",
    name: "Latest name",
    town_hall: 16,
    weight: null,
    storages: 5,
    storages_saved: false,
    revision: 0,
    current_member: false,
  };
  const latest = {
    order: { "#G2Y": 1 },
    state: "inWar",
    end_time: "20261102T070000.000Z",
    names: { "#G2Y": "Latest name" },
    town_halls: { "#G2Y": 16 },
  };
  const older = {
    order: { "#G2Y": 1 },
    state: "warEnded",
    end_time: "20261031T070000.000Z",
    names: { "#G2Y": "Old name" },
  };
  const roster = {
    clan: { tag: "#R2Y", name: "Clan" },
    members: [current, left],
    checked_at: "",
    war_lineups: [latest, older],
  };
  const previous = selectedRoster(roster, older.end_time)!;
  expect(previous.members[1].name).toBe("Old name");
  expect(previous.members[1].town_hall).toBeNull();
  expect(draftsForRoster(roster, older.end_time)["#G2Y"].storages).toBe("");
  expect(selectedRoster(roster)!.members[1].town_hall).toBe(16);
  expect(
    draftsForRoster(
      {
        ...roster,
        members: [current, { ...left, storages: 4, storages_saved: true }],
      },
      older.end_time,
    )["#G2Y"].storages,
  ).toBe("4");
});

it("accepts the additive eligible union without relabelling current-member data", () => {
  const current = {
    tag: "#P2Y",
    name: "Current",
    town_hall: 16,
    weight: null,
    revision: 0,
    current_member: true,
  };
  const departed = {
    tag: "#G2Y",
    name: "Left",
    town_hall: 15,
    weight: null,
    revision: 0,
    current_member: false,
  };
  const wire = {
    clan: { tag: "#R2Y", name: "Clan" },
    checked_at: "",
    members: [current],
    weight_members: [current, departed],
    war_lineups: [
      {
        state: "inWar",
        end_time: "20261102T070000.000Z",
        order: { "#G2Y": 1 },
        names: { "#G2Y": "Left" },
        town_halls: { "#G2Y": 15 },
      },
    ],
  };
  expect(selectedRoster(wire)!.members.map((row) => row.tag)).toEqual([
    "#P2Y",
    "#G2Y",
  ]);
  expect(wire.members.map((row) => row.tag)).toEqual(["#P2Y"]);
  expect(draftsForRoster(wire)["#G2Y"].storages).toBe("5");
});

import { retainSavedWarSource, type Roster } from "./model";
it("uses selected lineup details then ledger details rather than another war or unknown", () => {
  const latest = {
    end_time: "20261102",
    state: "inWar",
    order: { "#G2Y": 1 },
    names: { "#G2Y": "New name" },
    town_halls: { "#G2Y": 18 },
  };
  const older = {
    end_time: "20261101",
    state: "warEnded",
    order: { "#G2Y": 1 },
  };
  const row = {
    tag: "#G2Y",
    name: "New name",
    town_hall: 18,
    current_member: false,
    saved_name: "Ace",
    saved_town_hall: 16,
  };
  const roster = {
    members: [],
    weight_members: [row],
    war_lineups: [latest, older],
  } as unknown as Roster;
  expect(selectedRoster(roster, older.end_time)?.members[0]).toMatchObject({
    name: "Ace",
    town_hall: 16,
  });
  expect(selectedRoster(roster, latest.end_time)?.members[0]).toMatchObject({
    name: "New name",
    town_hall: 18,
  });
});
it("keeps exact verified war labeling through a weight-only save without refreshing another snapshot", () => {
  const war = {
    end_time: "20261102",
    state: "inWar",
    order: { "#G2Y": 1 },
    cached: false,
    captured_at: "2026-11-02T12:00:00Z",
  };
  const before = {
    members: [],
    war_lineups: [war],
    war_order: war.order,
    war_source: war,
  } as unknown as Roster;
  const saved = {
    ...before,
    war_lineups: [{ ...war, cached: true }],
    war_source: { ...war, cached: true },
  };
  const retained = retainSavedWarSource(before, saved);
  expect(orderLabel(selectedRoster(retained)!)).toBe(
    "Current war · Battle day order",
  );
  for (const change of [
    { end_time: "20261103" },
    { state: "warEnded" },
    { captured_at: "2026-11-02T13:00:00Z" },
    { order: { "#P2Y": 1 } },
  ]) {
    const next = { ...war, ...change, cached: true };
    expect(
      retainSavedWarSource(before, { ...saved, war_lineups: [next] })
        .war_lineups?.[0].cached,
    ).toBe(true);
  }
});
