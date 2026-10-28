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

function render(
  pool: "main" | "lazy" | "all",
  seasonId = "1",
  seasonLabel = "June",
  activeStatuses: string[] = [],
) {
  return renderToStaticMarkup(
    <RosterHeader
      onFillSignupSpot={() => false}
      onSignupDetails={() => false}
      seasonId={seasonId}
      seasons={[
        { id: 1, label: seasonLabel, status: "active", signup_open: true },
      ]}
      roster={roster}
      activeStatuses={activeStatuses}
      pool={pool}
      canRoster
      canSignups
      canPublish
      onFinalize={() => {}}
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
  it("does not duplicate the workflow Finalize action", () => {
    expect(render("all")).not.toContain("Finalize →");
  });
  it("reflects active status filters in the stat chip pressed state", () => {
    const active = render("all", "1", "June", ["unassigned"]);
    expect(active).toMatch(
      /aria-pressed="true"[^>]*><span><strong>2<\/strong> unplaced/,
    );
    expect(render("all")).not.toContain('aria-pressed="true"');
  });
  it("keeps the season selector available before a season is selected", () => {
    expect(render("all", "")).toContain("Select a season");
  });
  it("shows a compact month while retaining the full accessible season and menu label", () => {
    const html = render("all", "1", "November 2026");
    expect(html).toContain('aria-label="Season: November 2026"');
    expect(html).toContain(
      'class="roster-header-season-short" aria-hidden="true">Nov 2026</span>',
    );
    expect(html).toContain('class="roster-menu-current">November 2026</span>');
  });
  it("keeps custom season names intact in the compact label", () => {
    expect(render("all", "1", "Championship season")).toContain(
      'class="roster-header-season-short" aria-hidden="true">Championship season</span>',
    );
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
