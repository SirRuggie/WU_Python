// @vitest-environment happy-dom
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
  it("shares the TH-first headline and keeps the lock only on the meta line", () => {
    const host = document.createElement("div");
    host.innerHTML = render({ account: { ...account, town_hall: 18 } });
    const headline = host.querySelector(".player-card-top")!;
    expect(
      headline.firstElementChild?.querySelector(".town-hall-icon"),
    ).not.toBeNull();
    expect(headline.children[1].textContent).toBe(account.player_name);
    expect(
      host.querySelectorAll('[aria-label="Locked placement"]'),
    ).toHaveLength(1);
    expect(
      host.querySelector('.player-card-meta [aria-label="Locked placement"]'),
    ).not.toBeNull();
    expect(
      host.querySelector(".roster-player-placement")?.textContent,
    ).toContain("Not assigned · now in —");
    host.innerHTML = render({
      account: {
        ...account,
        assigned_clan_tag: "#CLAN",
        current_clan_status: "current",
        current_clan_name: "Home",
      },
      assignedClanName: "Assigned",
    });
    expect(host.querySelector(".roster-player-placement")?.textContent).toBe(
      "Assigned · now in Home",
    );
  });
  it("escapes player text and presents missing, locked and unavailable values", () => {
    const html = render();
    expect(html).toContain("&lt;Alpha &amp; Beta&gt;");
    expect(html).not.toContain("<Alpha & Beta>");
    expect(html).toContain('aria-label="Select &lt;Alpha &amp; Beta&gt;"');
    expect(html).toContain("No weight");
    expect(html).toContain("Held unassigned");
    expect(html).toContain('is-unknown">—</span>');
    expect(html).not.toContain("Unavailable");
    expect(html).toContain("Main CWL");
  });

  it("shows a dim dash for stale clan data, and the name for current data", () => {
    const stale = render({
      account: {
        ...account,
        current_clan_status: "stale",
        current_clan_name: "Old clan",
      },
    });
    expect(stale).toContain('is-unknown">—</span>');
    expect(stale).not.toContain("Old clan");
    const current = render({
      account: {
        ...account,
        current_clan_status: "current",
        current_clan_name: "Home clan",
      },
    });
    expect(current).toContain("Home clan");
    expect(current).not.toContain("is-unknown");
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
