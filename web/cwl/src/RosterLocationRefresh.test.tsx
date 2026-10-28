import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { mergeRosterMetadata, type RosterSnapshot } from "./roster";
import RosterAccountCard from "./RosterAccountCard";
it("background refresh gives an already-shown card its completed location without changing saved fields", () => {
  const old: RosterSnapshot = {
    revision: 4,
    undo: null,
    clans: [],
    accounts: [
      {
        tag: "#P2Y",
        user_id: "123",
        prefer_crystal_1_or_lower: false,
        source_weight: null,
        source_status: "missing",
        source_name: null,
        source_checked_at: null,
        source_modified_at: null,
        manual_weight: null,
        player_name: "Alpha",
        pool: "main",
        town_hall: 18,
        assigned_clan_tag: "#A",
        kept: true,
        effective_weight: 170000,
        current_clan_status: "unavailable",
      },
    ],
  };
  const incoming = {
    ...old,
    metadata_updating: false,
    accounts: [
      {
        ...old.accounts[0],
        assigned_clan_tag: "#WRONG",
        kept: false,
        effective_weight: 1,
        current_clan_tag: "#B",
        current_clan_name: "Home",
        current_clan_status: "current" as const,
        current_clan_checked_at: "2026-10-28T12:00:00Z",
      },
    ],
  };
  const result = mergeRosterMetadata(old, incoming);
  expect(result.accounts[0]).toEqual({
    ...old.accounts[0],
    current_clan_tag: "#B",
    current_clan_name: "Home",
    current_clan_status: "current",
    current_clan_checked_at: "2026-10-28T12:00:00Z",
    outside_family_and_hosts: undefined,
  });
  const html = renderToStaticMarkup(
    <RosterAccountCard
      now={Date.parse("2026-10-28T12:04:00Z")}
      account={result.accounts[0]}
      assignedClanName="Assigned"
      showPool
      selected={false}
      selectionMode={false}
      disabled={false}
      canRoster
      canSignups
      archived={false}
      onToggle={() => {}}
      onDetails={() => {}}
      onAssign={() => {}}
      onSignup={() => {}}
    />,
  );
  expect(html).toContain("Home");
  expect(html).toContain("4m ago");
  expect(html).not.toContain("location not checked yet");
  expect(mergeRosterMetadata(old, { ...incoming, revision: 5 }).accounts).toBe(
    old.accounts,
  );
});
