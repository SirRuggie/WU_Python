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
  lower_league: null,
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
      averageWeight: 170000,
      capacity: 15,
    });
    expect(summaries[2]).toMatchObject({
      assignedCount: 1,
      averageWeight: 190000,
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

  it("renders configured capacity details but count only for unconfigured clans", () => {
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
    expect(html).toContain("Avg 170k");
    expect(html).toContain("1 of 2 weighed");
    const unconfigured = html.slice(html.indexOf("#ALL"));
    expect(unconfigured).toContain(">1</span>");
    expect(unconfigured).not.toContain("Avg 190k");
    expect(unconfigured).not.toContain("capacity");
  });

  it("does not treat an unsupported capacity as configured", () => {
    expect(
      buildRosterClanChipSummaries([], [clan("#ODD", "main", 20)], "all")[0]
        .capacity,
    ).toBeNull();
  });
});
