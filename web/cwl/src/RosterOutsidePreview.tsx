import { useState } from "react";
import { createRoot } from "react-dom/client";
import RosterFilters from "./RosterFilters";
import {
  DEFAULT_ROSTER_RELEASE_PREFERENCES,
  deriveRosterRelease,
  type RosterReleaseFilters,
} from "./rosterReleaseModel";
import type { RosterSnapshot } from "./roster";
import "./style.css";
const roster: RosterSnapshot = {
  revision: 1,
  clans: [],
  undo: null,
  accounts: Array.from({ length: 65 }, (_, index) => ({
    tag: `#P${index}`,
    user_id: String(index),
    pool: index % 2 ? "lazy" : "main",
    player_name: `Fixture player ${index + 1}`,
    town_hall: 16 - (index % 4),
    prefer_crystal_1_or_lower: false,
    source_weight: 149000,
    source_status: "current",
    source_name: "Fixture",
    source_checked_at: null,
    source_modified_at: null,
    manual_weight: null,
    effective_weight: index % 11 ? 149000 : null,
    assigned_clan_tag: null,
    kept: index % 7 === 0,
    outside_family_and_hosts: index % 5 === 0,
  })),
};
function Preview() {
  const [value, setValue] = useState<RosterReleaseFilters>(
    DEFAULT_ROSTER_RELEASE_PREFERENCES,
  );
  const rows = deriveRosterRelease(
    roster.accounts,
    roster.clans,
    value,
  ).matches;
  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <p className="eyebrow">Isolated fixture · no API</p>
      <h1>Build roster</h1>
      <RosterFilters
        roster={roster}
        value={value}
        onChange={setValue}
        disabled={false}
      />
      <h2 data-outside-results={rows.length}>Showing {rows.length} accounts</h2>
      <ul>
        {rows.map((row) => (
          <li key={row.tag} style={{ padding: "12px 0" }}>
            {row.player_name}
            {row.outside_family_and_hosts
              ? " · Outside family / hosting clans"
              : ""}
          </li>
        ))}
      </ul>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
