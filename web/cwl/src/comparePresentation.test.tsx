import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  comparisonPublishNote,
  comparisonWeightRange,
  outsideComparisonRange,
} from "./comparePresentation";
import { totalRosterWeight } from "./rosterTotalWeight";
import ComparePlayerCard from "./ComparePlayerCard";
import RosterAccountMenu from "./RosterAccountMenu";
import type { RosterAccount, RosterClan } from "./roster";
const account = {
  tag: "#P",
  player_name: "Long <Name>",
  user_id: "123456789012345678",
  assigned_clan_tag: "#A",
  effective_weight: 170000,
  kept: true,
  town_hall: 18,
} as RosterAccount;
const clan = {
  tag: "#A",
  min_weight: 150000,
  max_weight: 170000,
} as RosterClan;
describe("Compare presentation contracts", () => {
  it("uses inclusive minimum and exclusive maximum, never flags missing", () => {
    expect(outsideComparisonRange(149999, clan)).toBe(true);
    expect(outsideComparisonRange(150000, clan)).toBe(false);
    expect(outsideComparisonRange(169999, clan)).toBe(false);
    expect(outsideComparisonRange(170000, clan)).toBe(true);
    expect(outsideComparisonRange(null, clan)).toBe(false);
    expect(comparisonWeightRange(clan)).toBe("150k–170k");
    expect(comparisonWeightRange({ ...clan, max_weight: null })).toBe("150k+");
    expect(comparisonWeightRange({ ...clan, min_weight: null })).toBe(
      "under 170k",
    );
  });
  it("formats identical known totals for both header consumers", () => {
    expect(totalRosterWeight(null)).toBe("Total —");
    expect(totalRosterWeight(2579000)).toBe("Total 2,579k");
    expect(totalRosterWeight(1881600)).toBe("Total 1,881.6k");
    expect(totalRosterWeight(0)).toBe("Total 0k");
  });
  it("distinguishes moved, unpublished, unassigned and absent publication", () => {
    expect(comparisonPublishNote(account, null)).toBe("");
    expect(comparisonPublishNote(account, [])).toBe("Not published yet");
    expect(
      comparisonPublishNote(account, [
        { tag: "#P", assigned_clan_tag: null, assigned_clan_name: null },
      ]),
    ).toBe("Moved since publish · members still see Unassigned");
    expect(
      comparisonPublishNote(account, [
        { tag: "#P", assigned_clan_tag: "#A", assigned_clan_name: "A" },
      ]),
    ).toBe("");
  });
  it("Compare menu has only contact and Details, roster retains its actions", () => {
    const html = renderToStaticMarkup(
      <RosterAccountMenu
        account={account}
        disabled={false}
        onDetails={() => {}}
      />,
    );
    expect(html).toContain("DM ↗");
    expect(html).toContain("Details");
    expect(html).not.toContain("Change signup");
    expect(html).not.toContain(">Assign<");
    const roster = renderToStaticMarkup(
      <RosterAccountMenu
        account={account}
        disabled={false}
        canRoster
        canSignups
        onDetails={() => {}}
        onAssign={() => {}}
        onSignup={() => {}}
      />,
    );
    expect(roster).toContain("Change signup");
    expect(roster).toContain("Assign");
  });
  it("card body is an explicitly labelled Details button without selection", () => {
    const html = renderToStaticMarkup(
      <ComparePlayerCard
        account={account}
        clan={clan}
        now={Date.now()}
        published={[]}
        busy={false}
        onDetails={() => {}}
      />,
    );
    expect(html).toContain('aria-label="Details for Long &lt;Name&gt;"');
    expect(html).toContain("Checking…");
    expect(html).toContain("Outside weight range");
    expect(html).toContain("Locked placement");
    expect(html).not.toContain('type="checkbox"');
    expect(html).not.toContain("Location unknown");
  });
});
