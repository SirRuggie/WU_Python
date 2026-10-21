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

import { orderedMembers, orderLabel } from './model';
it('shows war map order before non-war members regardless of clan rank', () => {
 const rows = [1,2,3].map(n=>({tag:`#P${n}`,name:`Player ${n}`,town_hall:18,weight:null,revision:0,clan_position:n}));
 const roster={clan:{tag:'#P0',name:'Test'},members:rows,checked_at:'',war_order:{'#P2':2,'#P3':1},war_source:{state:'preparation'}};
 expect(orderedMembers(roster).map(row=>row.tag)).toEqual(['#P3','#P2','#P1']);
 expect(rows.map(row=>row.tag)).toEqual(['#P1','#P2','#P3']);
 expect(orderLabel(roster)).toContain('Preparation');
 expect(orderLabel({...roster,war_source:{state:'warEnded'}})).toContain('Last completed');
 expect(orderLabel({...roster,war_order:null})).toContain('War lineup unavailable');
 expect(orderedMembers({...roster,war_order:null}).map(row=>row.tag)).toEqual(['#P1','#P2','#P3']);
});
