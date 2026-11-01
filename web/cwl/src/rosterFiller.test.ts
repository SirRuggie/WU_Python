import { expect, it } from "vitest";
import { declarationGroups } from "./declarationGroups";
import type { DeclarationData } from "./declarationData";
import type { RosterSnapshot } from "./roster";
import type { DeclarationExtraClan } from "./declarationExtras";
import { buildRosterClanChipSummaries } from "./RosterClanChips";
const now = Date.parse("2026-11-01T00:00:00Z");
const stamp = new Date(now).toISOString();
function fixture() {
  const a = {
    tag: "#A",
    player_name: "Assigned",
    assigned_clan_tag: "#HOST",
    user_id: "123456789012345678",
    roster_filler: true,
  };
  const clan = {
    tag: "#HOST",
    name: "Host",
    capacity: 15,
    effective_capacity: 15,
    pool: "lazy",
    archived: false,
  };
  const roster = {
    revision: 1,
    undo: null,
    accounts: [a],
    clans: [clan],
  } as unknown as RosterSnapshot;
  const data = {
    roster,
    arrival: {
      accounts: [{ ...a, assigned_clan_name: "Host", hosting_pool: "lazy" }],
    },
  } as unknown as DeclarationData;
  const extra = {
    tag: "#HOST",
    name: "Host",
    capacity: 15,
    status: "current",
    checked_at: stamp,
    extras: [],
    count: 0,
    fillers: [
      {
        tag: "#A",
        name: "Assigned",
        town_hall: 16,
        context: "Assigned",
        assigned_clan_tag: "#HOST",
      },
      {
        tag: "#B",
        name: "Outside roster",
        town_hall: 8,
        context: "Not signed up",
        assigned_clan_tag: null,
      },
    ],
  } as DeclarationExtraClan;
  return { roster, data, extra };
}
it("counts observed marked fillers once, including off-roster, and never pings present fillers", () => {
  const { roster, data, extra } = fixture();
  const groups = declarationGroups(data, roster, {}, now, [extra]);
  expect(groups[0].readiness.arrivedCount).toBe(2);
  expect(groups[0].readiness.freshCount).toBe(2);
  expect(groups[0].late).toHaveLength(0);
  expect(groups[0].checkingCount).toBe(0);
});
it("off-roster fillers create a checked Lazy host group, not a missing ping target", () => {
  const { roster, data, extra } = fixture();
  roster.accounts = [];
  data.arrival.accounts = [];
  const groups = declarationGroups(data, roster, {}, now, [extra]);
  expect(groups).toHaveLength(1);
  expect(groups[0].pool).toBe("lazy");
  expect(groups[0].readiness.arrivedCount).toBe(2);
  expect(groups[0].late).toHaveLength(0);
});
it("assigned fillers absent from the observed clan remain missing and unavailable rows never invent presence", () => {
  const { roster, data, extra } = fixture();
  extra.fillers = [];
  const records = {
    "#A": {
      current_clan_tag: "#OTHER",
      current_clan_name: "Other",
      current_clan_checked_at: stamp,
    },
  };
  expect(
    declarationGroups(data, roster, records, now, [extra])[0].late,
  ).toHaveLength(1);
  extra.status = "unavailable";
  extra.fillers = [
    {
      tag: "#A",
      name: "A",
      town_hall: 8,
      context: "",
      assigned_clan_tag: "#HOST",
    },
  ];
  expect(
    declarationGroups(data, roster, records, now, [extra])[0].readiness
      .arrivedCount,
  ).toBe(0);
});
it("capacity summaries include filler occupants without losing their explicit mark count", () => {
  const { roster } = fixture();
  roster.accounts = Array.from({ length: 16 }, (_, i) => ({
    ...roster.accounts[0],
    tag: String(i),
    roster_filler: i === 0,
  }));
  const summary = buildRosterClanChipSummaries(
    roster.accounts,
    roster.clans,
    "lazy",
  )[0];
  expect(summary.assignedCount).toBe(16);
  expect(summary.fillerCount).toBe(1);
});

it("current mark changes and undo never replace published placements, including removed signup tags", async () => {
  const { mergeRosterMarks } = await import("./roster");
  const { roster } = fixture();
  roster.accounts[0].assigned_clan_tag = "#PUBLISHED";
  const latest = { ...roster, revision: 4, accounts: [] };
  const changed = mergeRosterMarks(roster, latest, {
    tag: "#A",
    roster_filler: false,
    mark_revision: 2,
  });
  expect(changed.accounts[0].assigned_clan_tag).toBe("#PUBLISHED");
  expect(changed.accounts[0].roster_filler).toBe(false);
  const restored = mergeRosterMarks(
    changed,
    { ...latest, revision: 5 },
    { tag: "#A", roster_filler: true, mark_revision: 3 },
  );
  expect(restored.accounts[0].assigned_clan_tag).toBe("#PUBLISHED");
  expect(restored.accounts[0].roster_filler).toBe(true);
  expect(restored.revision).toBe(5);
});

it("newer individual location evidence wins over an older filler clan observation", () => {
  const { roster, data, extra } = fixture();
  extra.checked_at = new Date(now - 60000).toISOString();
  const records = {
    "#A": {
      current_clan_tag: "#NEW",
      current_clan_name: "New clan",
      current_clan_checked_at: stamp,
    },
  };
  const group = declarationGroups(data, roster, records, now, [extra])[0];
  expect(group.late.map((a) => a.tag)).toEqual(["#A"]);
  expect(group.readiness.arrivedCount).toBe(1);
});

it("Ping missing count uses the same observation as late and excludes newer off-roster departures", () => {
  const { roster, data, extra } = fixture();
  const records = {
    "#A": {
      current_clan_tag: "#OLD",
      current_clan_name: "Old",
      current_clan_checked_at: new Date(now - 1000).toISOString(),
    },
    "#B": {
      current_clan_tag: "#NEW",
      current_clan_name: "New",
      current_clan_checked_at: new Date(now + 1000).toISOString(),
    },
  };
  const group = declarationGroups(data, roster, records, now, [extra])[0];
  expect(group.late).toHaveLength(0);
  expect(group.missingCount).toBe(0);
  expect(group.readiness.arrivedCount).toBe(1);
});
