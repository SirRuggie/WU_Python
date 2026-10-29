import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { RosterAccount, RosterClan } from "./roster";
import RosterClanChips, {
  buildRosterClanChipSummaries,
} from "./RosterClanChips";

const account = (
  tag: string,
  assigned_clan_tag: string | null,
  effective_weight: number | null,
): RosterAccount => ({
  tag,
  assigned_clan_tag,
  effective_weight,
  user_id: tag,
  pool: "main",
  player_name: tag,
  town_hall: 16,
  prefer_crystal_1_or_lower: false,
  source_weight: null,
  source_status: "missing",
  source_name: null,
  source_checked_at: null,
  source_modified_at: null,
  manual_weight: null,
  kept: false,
});
const clan = (
  tag: string,
  pool: "main" | "lazy" | null,
  capacity: number | null,
  archived = false,
): RosterClan => ({
  tag,
  name: tag,
  pool,
  capacity,
  archived,
  effective_capacity: capacity || 0,
  min_weight: null,
  max_weight: null,

  assigned_count: 99,
});

describe("clan filter summaries", () => {
  const clans = [
    clan("#LAZY", "lazy", 30),
    clan("#ALL", null, null),
    clan("#MAIN", "main", 15),
    clan("#OLD", "main", 15, true),
  ];
  const accounts = [
    account("#A", "#MAIN", 170000),
    account("#B", "#MAIN", null),
    account("#C", "#ALL", 190000),
    account("#D", "#OLD", 160000),
  ];

  it("uses actual assignments, known weights, and configured capacity", () => {
    const summaries = buildRosterClanChipSummaries(accounts, clans, "all");
    expect(summaries.map((item) => item.clan.tag)).toEqual([
      "#MAIN",
      "#LAZY",
      "#ALL",
    ]);
    expect(summaries[0]).toMatchObject({
      assignedCount: 2,
      knownWeightCount: 1,
      missingWeightCount: 1,
      totalWeight: 170000,
      capacity: 15,
    });
    expect(summaries[2]).toMatchObject({
      assignedCount: 1,
      totalWeight: 190000,
      capacity: null,
    });
  });

  it("respects the placement pool and excludes archived clans", () => {
    expect(
      buildRosterClanChipSummaries(accounts, clans, "main").map(
        (item) => item.clan.tag,
      ),
    ).toEqual(["#MAIN", "#ALL"]);
    expect(
      buildRosterClanChipSummaries(accounts, clans, "lazy").map(
        (item) => item.clan.tag,
      ),
    ).toEqual(["#LAZY"]);
  });

  it("renders totals for every clan and bars only for configured capacities", () => {
    const html = renderToStaticMarkup(
      createElement(RosterClanChips, {
        roster: { revision: 1, accounts, clans, undo: null },
        pool: "all",
        selectedTags: [],
        onSelect: () => {},
        disabled: false,
      }),
    );
    expect(html).toContain("roster-clan-chip is-room");
    expect(html).toContain("Total 170k");
    expect(html).toContain("1 of 2 weighed");
    expect(html).not.toContain("1 of 1 weighed");
    const unconfigured = html.slice(html.indexOf("#ALL"));
    expect(unconfigured).toContain(">1</span>");
    expect(unconfigured).toContain("Total 190k");
    expect(unconfigured).not.toContain("capacity");
  });

  it("sums only finite known weights of assigned accounts, not missing or unassigned weights", () => {
    const result = buildRosterClanChipSummaries(
      [
        account("#A", "#MAIN", 170000),
        account("#B", "#MAIN", 180000),
        account("#C", "#MAIN", null),
        account("#D", null, 900000),
        account("#E", "#MAIN", Number.NaN),
      ],
      [clan("#MAIN", "main", 15)],
      "all",
    )[0];
    expect(result).toMatchObject({
      assignedCount: 4,
      knownWeightCount: 2,
      missingWeightCount: 2,
      totalWeight: 350000,
    });
  });

  it("distinguishes empty, all-missing and a known zero total", () => {
    const result = buildRosterClanChipSummaries(
      [account("#A", "#MISSING", null), account("#B", "#ZERO", 0)],
      [
        clan("#EMPTY", "main", 15),
        clan("#MISSING", "main", 15),
        clan("#ZERO", "main", 15),
      ],
      "all",
    );
    expect(result.map(({ totalWeight }) => totalWeight)).toEqual([
      null,
      null,
      0,
    ]);
  });

  it("formats grouped thousands, empty totals and missing-weight notes without changing selection", () => {
    const html = renderToStaticMarkup(
      createElement(RosterClanChips, {
        roster: {
          revision: 1,
          accounts: [
            account("#A", "#MAIN", 2579000),
            account("#B", "#MAIN", null),
          ],
          clans: [clan("#MAIN", "main", 30), clan("#EMPTY", "main", 15)],
          undo: null,
        },
        pool: "all",
        selectedTags: ["#MAIN"],
        onSelect: () => {},
        disabled: false,
      }),
    );
    expect(html).toContain("Total 2,579k");
    expect(html).not.toContain("Total —");
    expect(html).toContain("with no players");
    expect(html).toContain("1 of 2 weighed");
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("is-selected");
    expect(html).not.toContain("Avg");
  });

  it("does not treat an unsupported capacity as configured", () => {
    expect(
      buildRosterClanChipSummaries([], [clan("#ODD", "main", 20)], "all")[0]
        .capacity,
    ).toBeNull();
  });
});
