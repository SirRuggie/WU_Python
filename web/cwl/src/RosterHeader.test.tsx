import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { RosterAccount, RosterSnapshot } from "./roster";
import RosterHeader from "./RosterHeader";

const account = (
  tag: string,
  pool: "main" | "lazy",
  assigned: string | null,
  weight: number | null,
): RosterAccount => ({
  tag,
  pool,
  assigned_clan_tag: assigned,
  effective_weight: weight,
  user_id: tag,
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

const roster: RosterSnapshot = {
  revision: 1,
  undo: null,
  clans: [],
  accounts: [
    account("#A", "main", "#CLAN", 170000),
    account("#B", "main", null, null),
    account("#C", "lazy", null, null),
  ],
};

function render(pool: "main" | "lazy" | "all", seasonId = "1") {
  return renderToStaticMarkup(
    <RosterHeader
      seasonId={seasonId}
      seasons={[{ id: 1, label: "June", status: "active", signup_open: true }]}
      roster={roster}
      pool={pool}
      canRoster
      canSignups
      canPublish={false}
      uiLocked={false}
      archived={false}
      onSeasonChange={() => {}}
      onRefresh={() => {}}
      onAutoPlace={() => {}}
      onStatusFilter={() => {}}
      onAccessError={() => {}}
    />,
  );
}

describe("roster header counts", () => {
  it("keeps the season selector available before a season is selected", () => {
    expect(render("all", "")).toContain("Select a season");
  });
  it("scopes signed and unplaced to the chosen pool but keeps missing weight global", () => {
    expect(render("main")).toContain("<strong>2</strong> signed");
    expect(render("main")).toContain("<strong>1</strong> unplaced");
    expect(render("main")).toContain(
      "<strong>2</strong> no weight (all pools)",
    );
    expect(render("lazy")).toContain("<strong>1</strong> signed");
    expect(render("lazy")).toContain("<strong>1</strong> unplaced");
    expect(render("lazy")).toContain(
      "<strong>2</strong> no weight (all pools)",
    );
    expect(render("all")).toContain("<strong>3</strong> signed");
    expect(render("all")).toContain("<strong>2</strong> unplaced");
    expect(render("all")).toContain("<strong>2</strong> no weight");
    expect(render("all")).not.toContain("(all pools)");
  });
});
