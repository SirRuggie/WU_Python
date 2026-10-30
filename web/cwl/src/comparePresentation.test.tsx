import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  comparisonPublishNote,
  comparisonWeightRange,
  outsideComparisonRange,
} from "./comparePresentation";
import { totalRosterWeight } from "./rosterTotalWeight";
import CompareClanHeader from "./CompareClanHeader";
import ComparePlayerCard from "./ComparePlayerCard";
import { rosterAccountMenuItems } from "./RosterAccountMenu";
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
  it("uses inclusive minimum and maximum, never flags missing", () => {
    expect(outsideComparisonRange(149999, clan)).toBe(true);
    expect(outsideComparisonRange(150000, clan)).toBe(false);
    expect(outsideComparisonRange(169999, clan)).toBe(false);
    expect(outsideComparisonRange(170000, clan)).toBe(false);
    expect(outsideComparisonRange(170001, clan)).toBe(true);
    expect(outsideComparisonRange(null, clan)).toBe(false);
    expect(comparisonWeightRange(clan)).toBe("150k–170k");
    expect(comparisonWeightRange({ ...clan, max_weight: null })).toBe("150k+");
    expect(comparisonWeightRange({ ...clan, min_weight: null })).toBe(
      "up to 170k",
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
    const items = rosterAccountMenuItems({ account, onDetails: () => {} });
    expect(items.map((item) => item.label)).toEqual(["DM ↗", "Details"]);
    expect(items[0].href).toBe("https://discord.com/users/123456789012345678");
    const roster = rosterAccountMenuItems({
      account,
      canRoster: true,
      canSignups: true,
      onDetails: () => {},
    });
    expect(roster.map((item) => item.label)).toEqual([
      "Assign",
      "Change signup",
      "DM ↗",
      "Details",
    ]);
    expect(
      rosterAccountMenuItems({
        account,
        canRoster: true,
        canSignups: true,
        archived: true,
        onDetails: () => {},
      }).map((item) => item.label),
    ).toEqual(["DM ↗", "Details"]);
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
    expect(html).not.toContain("Outside weight range");
    const overMax = renderToStaticMarkup(
      <ComparePlayerCard
        account={{ ...account, effective_weight: 170001 }}
        clan={clan}
        now={Date.now()}
        published={[]}
        busy={false}
        onDetails={() => {}}
      />,
    );
    expect(overMax).toContain("Outside weight range");
    expect(html).toContain("Locked placement");
    expect(html).not.toContain('type="checkbox"');
    expect(html).not.toContain("Location unknown");
  });
});

it("marks room, full and over capacity distinctly in shared headers", () => {
  for (const [capacity, expected] of [
    [2, "has-room"],
    [1, "is-full"],
    [0.5, "is-over"],
  ] as const) {
    const html = renderToStaticMarkup(
      <CompareClanHeader
        clan={{ ...clan, effective_capacity: capacity }}
        accounts={[account]}
        locations={{}}
      />,
    );
    expect(html).toContain(`roster-ui-progress ${expected}`);
  }
});

it("omits Avg TH entirely when no town hall is known", () => {
  const html = renderToStaticMarkup(
    <CompareClanHeader
      clan={clan}
      accounts={[{ ...account, town_hall: null }]}
      locations={{}}
    />,
  );
  expect(html).not.toContain("Avg TH");
});
