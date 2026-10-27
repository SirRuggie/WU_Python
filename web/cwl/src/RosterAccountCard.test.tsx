import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { RosterAccount } from "./roster";
import RosterAccountCard from "./RosterAccountCard";

const account: RosterAccount = {
  tag: "#PLAYER",
  user_id: "123",
  pool: "main",
  player_name: "<Alpha & Beta>",
  town_hall: null,
  prefer_crystal_1_or_lower: false,
  source_weight: null,
  source_status: "missing",
  source_name: null,
  source_checked_at: null,
  source_modified_at: null,
  manual_weight: null,
  effective_weight: null,
  assigned_clan_tag: null,
  kept: true,
  current_clan_status: "unavailable",
};

function render(
  overrides: Partial<Parameters<typeof RosterAccountCard>[0]> = {},
) {
  return renderToStaticMarkup(
    <RosterAccountCard
      account={account}
      assignedClanName="Unassigned"
      showPool
      selected={false}
      selectionMode
      disabled={false}
      canRoster
      canSignups
      archived={false}
      onToggle={() => {}}
      onDetails={() => {}}
      onAssign={() => {}}
      onSignup={() => {}}
      {...overrides}
    />,
  );
}

describe("roster account card", () => {
  it("escapes player text and presents missing, locked and unavailable values", () => {
    const html = render();
    expect(html).toContain("&lt;Alpha &amp; Beta&gt;");
    expect(html).not.toContain("<Alpha & Beta>");
    expect(html).toContain("No weight");
    expect(html).toContain("Held unassigned");
    expect(html).toContain("Unavailable");
    expect(html).toContain("Main CWL");
  });

  it("prevents selection in archived or read-only views while retaining Details", () => {
    const archived = render({ archived: true });
    expect(archived).toMatch(/type="checkbox"[^>]*disabled=""/);
    expect(archived).toContain("Details for &lt;Alpha &amp; Beta&gt;");
    const readOnly = render({ canRoster: false, canSignups: false });
    expect(readOnly).toMatch(/type="checkbox"[^>]*disabled=""/);
    expect(readOnly).toContain("Details for &lt;Alpha &amp; Beta&gt;");
  });
});
