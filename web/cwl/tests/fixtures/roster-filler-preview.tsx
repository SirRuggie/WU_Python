import { DashboardPermissions } from "../../src/DashboardPermissions";
/** Disconnected sample data. The only write changes this page's in-memory marks. */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import RosterAccountCard from "../../src/RosterAccountCard";
import RosterPlayerDialog from "../../src/RosterPlayerDialog";
import RosterClanChips from "../../src/RosterClanChips";
import RosterFilters from "../../src/RosterFilters";
import DeclarationExtras from "../../src/DeclarationExtras";
import {
  DEFAULT_ROSTER_RELEASE_PREFERENCES,
  deriveRosterRelease,
} from "../../src/rosterReleaseModel";
import type { RosterSnapshot } from "../../src/roster";
import type { DeclarationExtraClan } from "../../src/declarationExtras";
import "../../src/style.css";
const count = Number(new URLSearchParams(location.search).get("count") || 26);
if (![26, 65, 125].includes(count)) throw new Error("Choose a fixture size");
const now = new Date().toISOString();
const methods: string[] = [];
const initial: RosterSnapshot = {
  revision: 1,
  undo: null,
  clans: [
    {
      tag: "#HOST",
      name: "Quiet Meadow hosting clan",
      archived: false,
      pool: "lazy",
      capacity: 15,
      effective_capacity: 15,
      assigned_count: 16,
      min_weight: null,
      max_weight: null,
    },
  ],
  accounts: Array.from({ length: count }, (_, i) => ({
    tag: `#P${i}`,
    player_name: `Sample member ${i + 1}${i === 0 ? " with a deliberately long account name" : ""}`,
    user_id: "123456789012345678",
    pool: "lazy",
    town_hall: i % 12 === 0 ? 9 : 16,
    prefer_crystal_1_or_lower: false,
    source_weight: 150000,
    source_status: "current",
    source_name: "Fixture",
    source_checked_at: now,
    source_modified_at: now,
    manual_weight: null,
    effective_weight: 150000,
    assigned_clan_tag: i < 16 ? "#HOST" : null,
    kept: false,
    roster_filler: i === 0,
    roster_filler_revision: i === 0 ? 1 : 0,
    current_clan_tag: "#HOST",
    current_clan_name: "Quiet Meadow",
    current_clan_checked_at: now,
    current_clan_status: "current",
  })),
};
function Preview() {
  const [roster, setRoster] = useState(initial),
    [filters, setFilters] = useState(DEFAULT_ROSTER_RELEASE_PREFERENCES),
    [editing, setEditing] = useState<string | null>(null),
    [extraMarks, setExtraMarks] = useState<
      Record<string, { value: boolean; revision: number }>
    >({});
  Object.assign(window, {
    fillerFixture: () => ({ count, revision: roster.revision, methods }),
  });
  window.fetch = async (input, options) => {
    const url = new URL(String(input), location.origin);
    const method = options?.method || "GET";
    methods.push(method);
    if (
      url.origin !== location.origin ||
      method !== "PATCH" ||
      !url.pathname.startsWith("/api/cwl/seasons/1/roster-filler/")
    )
      throw new Error("Disconnected fixture rejects this request");
    const tag = decodeURIComponent(url.pathname.split("/").at(-1)!);
    const body = JSON.parse(String(options?.body));
    const old = roster.accounts.find((a) => a.tag === tag);
    const prior = extraMarks[tag];
    if (
      body.revision !== roster.revision ||
      body.mark_revision !==
        (old?.roster_filler_revision || prior?.revision || 0)
    )
      return new Response(
        JSON.stringify({ error: "Fixture revision changed" }),
        { status: 409 },
      );
    setRoster((r) => ({
      ...r,
      revision: r.revision + 1,
      accounts: r.accounts.map((a) =>
        a.tag === tag
          ? {
              ...a,
              roster_filler: body.roster_filler,
              roster_filler_revision: body.mark_revision + 1,
            }
          : a,
      ),
    }));
    setExtraMarks((m) => ({
      ...m,
      [tag]: { value: body.roster_filler, revision: body.mark_revision + 1 },
    }));
    return new Response(JSON.stringify({ revision: roster.revision + 1 }), {
      headers: { "Content-Type": "application/json" },
    });
  };
  const sample = [
    {
      tag: "#LOW",
      name: "Low TH sample",
      town_hall: 9,
      context: "Not signed up",
      assigned_clan_tag: null,
    },
    {
      tag: "#EXTRA",
      name: "Unexpected sample",
      discord_id: "123456789012345678",
      discord_profile: {
        id: "123456789012345678",
        display_name:
          "Family member with a deliberately very long display name",
        username: "family_fixture",
        avatar_url: null,
      },
      town_hall: 16,
      context: "Not signed up",
      assigned_clan_tag: null,
    },
  ].map((a) => ({
    ...a,
    roster_filler: !!extraMarks[a.tag]?.value,
    roster_filler_revision: extraMarks[a.tag]?.revision || 0,
  }));
  const extra: DeclarationExtraClan = {
    tag: "#HOST",
    name: "Quiet Meadow",
    capacity: 15,
    status: "current",
    checked_at: now,
    extras: sample.filter((a) => !a.roster_filler && a.town_hall > 9),
    low_th: sample.filter((a) => !a.roster_filler && a.town_hall <= 9),
    fillers: sample.filter((a) => a.roster_filler),
    count: sample.filter((a) => !a.roster_filler && a.town_hall > 9).length,
  };
  const shown = deriveRosterRelease(
    roster.accounts,
    roster.clans,
    filters,
  ).matches;
  return (
    <main
      className="roster-ui roster-workspace"
      style={{ maxWidth: 1100, margin: "0 auto", padding: 16 }}
    >
      <p>Isolated sample · no live API</p>
      <h1>Build roster</h1>
      <RosterClanChips
        roster={roster}
        pool="lazy"
        selectedTags={[]}
        onSelect={() => {}}
        disabled={false}
      />
      <RosterFilters
        roster={roster}
        value={filters}
        onChange={setFilters}
        disabled={false}
      />
      <h2>Checked clan</h2>
      <DeclarationExtras
        row={extra}
        loading={false}
        error=""
        now={Date.now()}
        markControl={{
          seasonId: "1",
          revision: roster.revision,
          onChanged: () => {},
        }}
      />
      <h2>{shown.length} accounts</h2>
      <div className="roster-account-list">
        {shown.map((a) => (
          <RosterAccountCard
            key={a.tag}
            now={Date.now()}
            account={a}
            assignedClanName="Quiet Meadow"
            showPool
            selected={false}
            selectionMode={false}
            disabled={false}
            canRoster
            canSignups
            archived={false}
            onToggle={() => {}}
            onDetails={() => setEditing(a.tag)}
            onAssign={() => setEditing(a.tag)}
            onSignup={() => {}}
          />
        ))}
      </div>
      {editing && (
        <RosterPlayerDialog
          seasonId="1"
          account={roster.accounts.find((a) => a.tag === editing)!}
          roster={roster}
          clans={roster.clans}
          busy={false}
          onClose={() => setEditing(null)}
          onSave={async () => false}
          onRemove={async () => false}
          onReload={async () => {}}
        />
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
    <Preview />
  </DashboardPermissions.Provider>,
);
