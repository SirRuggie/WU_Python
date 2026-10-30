import { expect, it } from "vitest";
import {
  planPresentation,
  publishedMoveCount,
  rosterWeightSummary,
} from "./rosterPlanPresentation";
import type { RosterAccount, RosterClan } from "./roster";

const accounts = [
  { tag: "#A", assigned_clan_tag: "#X", effective_weight: 2_500_000 },
  { tag: "#B", assigned_clan_tag: "#X", effective_weight: null },
  { tag: "#C", assigned_clan_tag: "#Y", effective_weight: 2_012_500 },
  { tag: "#D", assigned_clan_tag: "#Y", effective_weight: null },
] as RosterAccount[];

it("sums known weights and reports none known explicitly", () => {
  expect(rosterWeightSummary(accounts)).toEqual({
    count: 4,
    weighed: 2,
    total: 4_512_500,
  });
  expect(rosterWeightSummary([accounts[1]])).toEqual({
    count: 1,
    weighed: 0,
    total: null,
  });
});

it("projects source and destination totals for a move without counting unknown weights", () => {
  const result = planPresentation(
    accounts,
    [{ tag: "#X" }, { tag: "#Y" }] as RosterClan[],
    {
      revision: 2,
      placements: [{ tag: "#A", assigned_clan_tag: "#Y" }],
      unassigned: [{ tag: "#B", reason: "missing_weight" }],
    },
    ["#A", "#B", "#C", "#D"],
    ["#Y"],
  );
  expect(result.unchanged.map((account) => account.tag)).toEqual(["#C", "#D"]);
  expect(result.clans[0].before).toEqual({
    count: 2,
    weighed: 1,
    total: 2_500_000,
  });
  expect(result.clans[0].after).toEqual({ count: 1, weighed: 0, total: null });
  expect(result.clans[1].before).toEqual({
    count: 2,
    weighed: 1,
    total: 2_012_500,
  });
  expect(result.clans[1].after).toEqual({
    count: 3,
    weighed: 2,
    total: 4_512_500,
  });
});

it("counts published destination changes rather than any selected published player", () => {
  expect(
    publishedMoveCount(
      {
        revision: 1,
        placements: [
          { tag: "#A", assigned_clan_tag: "#X" },
          { tag: "#B", assigned_clan_tag: "#Y" },
          { tag: "#C", assigned_clan_tag: "#Y" },
        ],
        unassigned: [],
      },
      [
        { tag: "#A", assigned_clan_tag: "#X" },
        { tag: "#B", assigned_clan_tag: "#X" },
        { tag: "#C", assigned_clan_tag: null },
      ],
    ),
  ).toBe(1);
});
