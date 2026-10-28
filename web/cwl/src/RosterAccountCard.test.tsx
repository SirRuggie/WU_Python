// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
const cardCss = readFileSync("src/PlayerCard.css", "utf8");
const accountCss = readFileSync("src/RosterAccountCard.css", "utf8");
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RosterAccount } from "./roster";
import RosterAccountCard from "./RosterAccountCard";

afterEach(() => vi.restoreAllMocks());

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
      now={Date.now()}
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
    ).toContain("Not assigned· location not checked yet");
    host.innerHTML = render({
      account: {
        ...account,
        assigned_clan_tag: "#CLAN",
        current_clan_status: "current",
        current_clan_name: "Home",
        current_clan_checked_at: new Date().toISOString(),
      },
      assignedClanName: "Assigned",
    });
    expect(host.querySelector(".roster-player-placement")?.textContent).toBe(
      "Assigned· now in Home · just now",
    );
  });
  it("escapes player text and presents missing, locked and unavailable values", () => {
    const html = render();
    expect(html).toContain("&lt;Alpha &amp; Beta&gt;");
    expect(html).not.toContain("<Alpha & Beta>");
    expect(html).toContain('aria-label="Select &lt;Alpha &amp; Beta&gt;"');
    expect(html).toContain("No weight");
    expect(html).toContain("Held unassigned");
    expect(html).toContain("location not checked yet");
    expect(html).not.toContain("Unavailable");
    expect(html).toContain("Main CWL");
  });

  it("keeps stale location results with Compare's age formatter", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-28T14:00:00Z"));
    const html = render({
      account: {
        ...account,
        current_clan_status: "stale",
        current_clan_name: "Old clan",
        current_clan_checked_at: "2026-10-28T12:00:00Z",
      },
    });
    expect(html).toContain("· now in Old clan · 2h 0m ago");
    expect(html).not.toContain("location not checked yet");
  });
  it("omits duplicate Not assigned notes but preserves real notes and Held", () => {
    const host = document.createElement("div");
    host.innerHTML = render({
      account: {
        ...account,
        kept: false,
        auto_placement_reason: "missing_weight",
      },
    });
    expect(host.querySelector(".roster-player-note")).toBeNull();
    expect(host.querySelector(".roster-player-sr-only")?.textContent).toContain(
      "Assigned clan: Not assigned.",
    );
    host.innerHTML = render({
      account: { ...account, kept: false, auto_placement_note: "Needs review" },
    });
    expect(host.querySelector(".roster-player-note")?.textContent).toBe(
      "Needs review",
    );
    expect(render()).toContain("Held unassigned");
  });
  it("keeps the full location in a title and ellipsizes only the current clan", () => {
    const html = render({
      account: {
        ...account,
        current_clan_checked_at: new Date().toISOString(),
        current_clan_name: "A very long current clan",
      },
    });
    expect(html).toContain(
      'title="· now in A very long current clan · just now"',
    );
    const style = document.createElement("style");
    style.textContent = cardCss + accountCss;
    const host = document.createElement("div");
    host.className = "roster-ui roster-workspace";
    host.style.width = "300px";
    host.innerHTML = html;
    document.head.append(style);
    document.body.append(host);
    try {
      const row = host.querySelector(".roster-player-placement")!;
      const current = host.querySelector(".roster-player-current")!;
      expect(getComputedStyle(row).display).toBe("flex");
      expect(getComputedStyle(row).whiteSpace).toBe("nowrap");
      expect(getComputedStyle(current).overflow).toBe("hidden");
      expect(getComputedStyle(current).textOverflow).toBe("ellipsis");
      expect(getComputedStyle(row.querySelector("strong")!).flexShrink).toBe(
        "0",
      );
    } finally {
      host.remove();
      style.remove();
    }
  });
  it("keeps card text at least 12px and both headline weights 15px bold", () => {
    for (const css of [cardCss, accountCss]) {
      for (const match of css.matchAll(/font-size:\s*(\d+)px/g))
        expect(Number(match[1])).toBeGreaterThanOrEqual(12);
    }
    const css = cardCss;
    expect(css).toMatch(
      /player-card-weight\s*\{[^}]*font-size: 15px;[^}]*font-weight: 700/s,
    );
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

it("hides backend ready notes for unassigned, unkept accounts", () => {
  const host = document.createElement("div");
  host.innerHTML = render({
    account: {
      ...account,
      kept: false,
      auto_placement_reason: "ready",
      auto_placement_note:
        "Ready for auto-placement. Preview and apply to assign.",
    },
  });
  expect(host.querySelector(".roster-player-note")).toBeNull();
});
it("says in no clan for a checked clanless account", () => {
  const html = render({
    account: {
      ...account,
      current_clan_checked_at: new Date().toISOString(),
      current_clan_tag: null,
      current_clan_name: null,
    },
  });
  expect(html).toContain("· in no clan · just now");
  expect(html).not.toContain("now in No clan");
});
