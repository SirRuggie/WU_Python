// Local visual fixture. This page is separate from the signed-in dashboard.
import React from "react";
import { createRoot } from "react-dom/client";
import StrikesWorkspace, { type Entry } from "./StrikesWorkspace";
import "./style.css";

const now = new Date().toISOString();
const entries: Entry[] = [
  {
    id: "mismatch",
    player_tag: "#P22ABC",
    player_name: "CastleFox",
    war_end: now,
    opponent_name: "Mismatch opponent",
    source: "war",
    kind: "mismatch",
    status: "mismatch",
    source_label: "Clash API",
    war_key: "mismatch-war",
    reason: "Mismatch war (no strike)",
  },
  {
    id: "no-attack",
    player_tag: "#P22ABC",
    player_name: "CastleFox",
    war_end: now,
    opponent_name: "NO WAR",
    source: "war",
    kind: "no_attack",
    status: "no_attack",
    source_label: "Clash API",
    war_key: "neutral-war",
  },
  {
    id: "1",
    player_tag: "#P22ABC",
    player_name: "CastleFox",
    discord_id: "123456789012345678",
    discord_name: "Fox",
    current_clan_name: "Warriors United FWA",
    war_clan_name: "Warriors United FWA",
    opponent_name: "Edrag Rush",
    war_key: "war-fwa-edrag",
    war_end: now,
    kind: "strike",
    source: "war",
    source_label: "Clash API",
    status: "active",
  },
  {
    id: "2",
    player_tag: "#Q99XYZ",
    player_name: "BlueDragon",
    discord_id: "123456789012345679",
    discord_name: "Dragon",
    current_clan_name: "WU North",
    war_clan_name: "Warriors United FWA",
    opponent_name: "Edrag Rush",
    war_key: "war-fwa-edrag",
    war_end: now,
    kind: "miss",
    source: "war",
    source_label: "ClashKing (legacy)",
    status: "recorded",
  },
  {
    id: "cwl-1",
    player_tag: "#P22ABC",
    player_name: "CastleFox",
    discord_id: "123456789012345678",
    current_clan_name: "Warriors United FWA",
    war_clan_name: "Warriors United FWA",
    opponent_name: "Edrag Rush",
    war_key: "war-cwl-edrag",
    war_end: now,
    kind: "cwl",
    source: "cwl",
    source_label: "ClashKing (import)",
    war_type: "cwl",
    attacks_used: 0,
    missed_attacks: 1,
    attacks_per_member: 1,
    status: "recorded",
  },
  {
    id: "3",
    player_tag: "#8LQQRT",
    player_name: "LittleThunder",
    discord_id: "123456789012345678",
    discord_name: "Fox",
    current_clan_name: "WU North",
    war_clan_name: "Warriors United FWA",
    war_end: "2026-09-03T12:00:00Z",
    kind: "strike",
    source: "manual",
    status: "expired",
    reason: "Missed war meeting",
  },
];
// A long player history and full-population account list exercise real paging.
entries.push(
  ...Array.from(
    { length: 26 },
    (_, index): Entry => ({
      ...entries.find((entry) => entry.kind === "strike")!,
      id: `history-${index}`,
      war_key: `fixture-war-${index}`,
      opponent_name: `Opponent ${index + 1}`,
      status: index < 5 ? "active" : "expired",
      war_end: new Date(Date.now() - (index + 1) * 86400000).toISOString(),
    }),
  ),
);
for (const entry of entries) {
  entry.expires_at = new Date(
    new Date(entry.war_end || now).getTime() + 60 * 86400000,
  ).toISOString();
}
const wars = [
  {
    war_key: "mismatch-war",
    clan_tag: "#FWA",
    clan_name: "Warriors United FWA",
    opponent_tag: "#MISMATCH",
    opponent_name: "Mismatch opponent",
    war_end: now,
    missed_accounts: 1,
    strikes: 0,
    one_missed: 0,
    mismatch: true,
    source_label: "Clash API",
  },
  {
    war_key: "war-fwa-edrag",
    clan_tag: "#FWA",
    clan_name: "Warriors United FWA",
    opponent_tag: "#EDRAG",
    opponent_name: "Edrag Rush",
    war_end: now,
    missed_accounts: 2,
    strikes: 1,
    one_missed: 1,
    source_label: "Clash API",
  },
  {
    war_key: "war-cwl-edrag",
    clan_tag: "#FWA",
    clan_name: "Warriors United FWA",
    opponent_tag: "#EDRAG",
    opponent_name: "Edrag Rush",
    war_end: now,
    war_type: "cwl",
    missed_accounts: 1,
    strikes: 0,
    one_missed: 0,
    cwl_missed: 1,
    source_label: "ClashKing (import)",
  },
  {
    war_key: "war-incomplete",
    clan_tag: "#NORTH",
    clan_name: "WU North",
    opponent_tag: "#HIDDEN",
    opponent_name: "Unfinalized opponent",
    war_end: now,
    missed_accounts: 0,
    strikes: 0,
    one_missed: 0,
    source_label: "Clash API",
    incomplete: true,
    review_message: "War ended before final check: review in Find war",
  },
];
const candidates = [
  {
    player_tag: "#P22ABC",
    player_name: "CastleFox",
    clan_tag: "#FWA",
    clan_name: "Warriors United FWA",
    weight: 115000,
    active_strikes: 1,
    is_filler: true,
    is_manual: true,
    priority: "replace_first",
    note: "Temporary filler",
    weight_difference: 0,
    discord_name: "Fox",
  },
  {
    player_tag: "#P44DEF",
    player_name: "MiniWolf",
    clan_tag: "#FWA",
    clan_name: "Warriors United FWA",
    weight: 114000,
    active_strikes: 3,
    is_filler: false,
    is_manual: false,
    priority: "normal",
    weight_difference: 1000,
  },
  {
    player_tag: "#P55GHI",
    player_name: "GreenOak",
    clan_tag: "#FWA2",
    clan_name: "WU FWA Two",
    weight: 115000,
    active_strikes: 2,
    is_filler: false,
    is_manual: true,
    priority: "high",
    note: "Free a space soon",
    weight_difference: 0,
  },
  {
    player_tag: "#P66JKL",
    player_name: "Departed Aspen",
    clan_tag: "#FWA2",
    clan_name: "WU FWA Two",
    current_clan_tag: null,
    clan_is_current: false,
    departed: true,
    last_seen_clan_tag: "#FWA2",
    last_seen_clan_name: "WU FWA Two",
    last_seen_at: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
    active_strikes: 2,
    is_manual: true,
    priority: "high",
    note: "Confirmed departure six hours ago; retained during grace",
  },
  {
    player_tag: "#P77MOVED",
    player_name: "Transferred Birch",
    clan_tag: "#FWA2",
    clan_name: "WU FWA Two",
    current_clan_tag: "#FWA",
    current_clan_name: "Warriors United FWA",
    clan_is_current: false,
    departed: true,
    last_seen_clan_tag: "#FWA2",
    last_seen_clan_name: "WU FWA Two",
    last_seen_at: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
    active_strikes: 2,
    is_manual: true,
    priority: "high",
    note: "Moved to another family clan; original mark retained during grace",
  },
  {
    player_tag: "#P77STALE",
    player_name: "Stale Cedar",
    clan_tag: "#NORTH",
    clan_name: "WU North",
    clan_is_current: false,
    active_strikes: 1,
    is_manual: false,
    priority: "normal",
  },
];
const settings = {
  revision: 1,
  strike_limit: 7,
  excluded_roles: [{ id: "769130325460254740", name: "Strike exempt" }],
  roles: [
    { id: "769130325460254740", name: "Strike exempt" },
    { id: "123456789012345600", name: "Leave team", managed: false },
    { id: "333", name: "Managed integration", managed: true },
    { id: "444", name: "Helper bot", managed: false },
  ],
  leaves: [
    {
      discord_id: "123456789012345678",
      display_name: "Fox",
      player_tags: ["#P22ABC", "#8LQQRT"],
      resume_date: "2026-11-01",
      revision: 1,
    },
  ],
};
const members = [
  {
    id: "123456789012345678",
    name: "Fox",
    accounts: [
      {
        tag: "#P22ABC",
        name: "CastleFox",
        current_clan_name: "Warriors United FWA",
      },
      { tag: "#8LQQRT", name: "LittleThunder", current_clan_name: "WU North" },
    ],
  },
];
const preview = {
  summary: { strikes: 1, accounts: 1, history_only: 2 },
  preview_id: "fixture-preview",
  wars_scanned: 7,
  complete_wars: 6,
  incomplete_wars: 1,
  cwl_records: 1,
  deferred_count: 1,
  deferred_accounts: [
    {
      player_tag: "#P77UNKNOWN",
      player_name: "UnlinkedWolf",
      clan_name: "WU North",
      war_end: now,
      missed_attacks: 2,
      reason: "Account link needs review.",
    },
  ],
  coverage: [
    {
      clan_name: "Warriors United FWA",
      wars: 4,
      earliest: "2026-09-22T12:00:00Z",
      latest: now,
    },
    {
      clan_name: "WU North",
      wars: 3,
      deferred_accounts: 1,
      earliest: "2026-10-01T12:00:00Z",
      latest: now,
    },
  ],
  entries: [
    {
      key: "cwl-1-a",
      player_tag: "#P22ABC",
      player_name: "CastleFox",
      clan_name: "Warriors United FWA",
      discord_id: "123456789012345678",
      link_status: "linked",
      war_end: now,
      kind: "cwl",
      source: "cwl",
      war_type: "cwl",
      attacks_used: 0,
      attacks_per_member: 1,
      missed_attacks: 1,
      will_strike: false,
    },
    {
      key: "war-1-a",
      player_tag: "#P22ABC",
      player_name: "CastleFox",
      clan_name: "Warriors United FWA",
      discord_id: "123456789012345678",
      link_status: "linked",
      war_end: now,
      missed_attacks: 2,
      will_strike: true,
    },
    {
      key: "war-2-b",
      player_tag: "#Q99XYZ",
      player_name: "BlueDragon",
      clan_name: "WU North",
      discord_id: null,
      link_status: "unlinked",
      war_end: now,
      missed_attacks: 1,
      will_strike: false,
    },
  ],
};

const fixtureJobs = new Map<string, { reads: number; result: unknown }>();
let trackingQueued = false;
let reviewResolved = false;
const realFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = new URL(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url,
    location.origin,
  );
  const path = url.pathname;
  if (!path.startsWith("/api/cwl/strikes/")) return realFetch(input, init);
  const method = init?.method || "GET";
  let data: unknown = { ok: true };
  if (path.endsWith("/strikes/tracking") && method === "GET")
    data = {
      clans: [
        {
          clan_tag: "#FWA",
          clan_name: "Warriors United FWA",
          status: "healthy",
          current_war_state: "notInWar",
          last_checked_at: now,
          last_success_at: now,
          latest_recorded_war_at: now,
          regular_wars: 4,
          cwl_wars: 1,
          deferred_accounts: 0,
          skipped_wars: 0,
          retry_pending: false,
        },
        {
          clan_tag: "#NORTH",
          clan_name: "WU North",
          status: "behind",
          current_war_state: "warEnded",
          last_checked_at: now,
          last_success_at: "2026-10-19T12:00:00Z",
          latest_recorded_war_at: "2026-10-18T12:00:00Z",
          regular_wars: 2,
          cwl_wars: 0,
          deferred_accounts: 1,
          skipped_wars: 1,
          error: "War ended before final check: review in Find war.",
          retry_pending: trackingQueued,
        },
        {
          clan_tag: "#PRIVATE",
          clan_name: "Four and Twenty",
          status: "private",
          current_war_state: "private",
          last_checked_at: now,
          last_success_at: null,
          latest_recorded_war_at: null,
          regular_wars: 0,
          cwl_wars: 0,
          error: "War log private.",
        },
        {
          clan_tag: "#ERROR",
          clan_name: "WWWarriors",
          status: "error",
          current_war_state: "unknown",
          last_checked_at: now,
          last_success_at: null,
          latest_recorded_war_at: null,
          regular_wars: 0,
          cwl_wars: 0,
          error: "Official API unavailable.",
        },
        {
          clan_tag: "#UNKNOWN",
          clan_name: "New FWA Clan",
          status: "healthy",
          current_war_state: "unknown",
          last_checked_at: now,
          last_success_at: null,
          latest_recorded_war_at: null,
          regular_wars: 0,
          cwl_wars: 0,
        },
      ],
    };
  else if (path.endsWith("/strikes/tracking/retry")) {
    trackingQueued = true;
    data = { clan_tag: "#NORTH", retry_pending: true, retry_requested_at: now };
  } else if (
    path.endsWith("/strikes/accounts") &&
    url.searchParams.get("activity") === "true"
  ) {
    const options = new URLSearchParams(location.search);
    const count = [26, 65, 125].includes(Number(options.get("count")))
      ? Number(options.get("count"))
      : 125;
    const clans = [
      { tag: "#PQQ", name: "Warriors United FWA" },
      { tag: "#PYY", name: "WU North" },
      { tag: "#PJJ", name: "Lazy CWL 5" },
    ];
    data = {
      clans,
      accounts: Array.from({ length: count }, (_, index) => {
        const clan = clans[index % 3];
        const healthy = index === 1;
        const unknown = index === 2;
        const quiet = healthy
          ? 0
          : unknown
            ? null
            : index === 0
              ? 48
              : index % 18;
        const strikes = healthy || unknown ? 0 : index === 0 ? 6 : index % 5;
        return {
          player_tag:
            index === 0
              ? "#P22ABC"
              : `#P${index
                  .toString(8)
                  .padStart(6, "0")
                  .replace(
                    /[134567]/g,
                    (c) =>
                      ({
                        "1": "Y",
                        "3": "Q",
                        "4": "G",
                        "5": "R",
                        "6": "J",
                        "7": "C",
                      })[c]!,
                  )}`,
          player_name:
            index === 0
              ? "CastleFox"
              : healthy
                ? "Healthy Birch"
                : unknown
                  ? "New tracker Aspen"
                  : `Fixture player ${index + 1}`,
          current_clan_tag: clan.tag,
          current_clan_name: clan.name,
          town_hall: 16 - (index % 4),
          weight: 149000 - index * 100,
          active_strikes: strikes,
          total_strikes: index === 0 ? 28 : strikes,
          marked_for_replacement: strikes >= 3,
          replacement_eligible_low: strikes > 0 && strikes < 3,
          priority: index === 0 ? "replace_first" : null,
          status:
            strikes >= 3 || (quiet !== null && quiet >= 14)
              ? "risk"
              : strikes > 0 || (quiet !== null && quiet >= 7)
                ? "watch"
                : "active",
          quiet_days: quiet,
          last_seen_at: unknown
            ? null
            : new Date(Date.now() - (quiet || 0) * 86400000).toISOString(),
          last_seen_source: index === 3 ? "clashking_seed" : "clash_api",
          tracking_started_at: now,
          missed_attacks: index === 0 ? 28 : 0,
          observed_attacks: index === 0 ? 28 : 0,
          no_attack_wars: index === 0 ? 14 : 0,
          skipped_raid_weekends: index === 0 ? 2 : 0,
          discord_name: "Fixture member",
          discord_id: "123456789012345678",
        };
      }),
    };
  } else if (path.endsWith("/strikes/accounts")) {
    const accounts = Array.from({ length: 300 }, (_, index) => ({
      player_tag:
        index === 0 ? "#P22ABC" : `#P${index.toString(10).padStart(6, "0")}`,
      player_name: index === 0 ? "CastleFox" : `Fixture player ${index + 1}`,
      discord_id: "123456789012345678",
      discord_name: "Fox",
      current_clan_tag: "#FWA",
      current_clan_name: "Warriors United FWA",
      clan_is_current: true,
      active_strikes: index === 0 ? 6 : index % 10,
      total_strikes: index === 0 ? 28 : index % 10,
      over_limit: index % 10 >= 7,
      new_this_week: index % 3 === 0,
      last_strike_at: now,
    }));
    const query = (url.searchParams.get("query") || "").toLowerCase();
    const filtered = accounts.filter(
      (item) =>
        (url.searchParams.get("status") === "all" || item.active_strikes > 0) &&
        (!query ||
          `${item.player_name} ${item.player_tag} ${item.discord_name}`
            .toLowerCase()
            .includes(query)) &&
        (url.searchParams.get("action") !== "over_limit" || item.over_limit) &&
        (url.searchParams.get("action") !== "new_this_week" ||
          item.new_this_week),
    );
    const offset = Number(url.searchParams.get("offset") || 0);
    data = {
      accounts: filtered.slice(offset, offset + 25),
      total: filtered.length,
      summary: { over_limit: 90, new_this_week: 100 },
      strike_limit: 7,
      clans: [
        { tag: "#FWA", name: "Warriors United FWA", is_fwa: true },
        { tag: "#NORTH", name: "WU North" },
      ],
    };
  } else if (path.endsWith("/overview")) {
    const filtered = entries.filter(
      (item) =>
        (!url.searchParams.get("war_key") ||
          item.war_key === url.searchParams.get("war_key")) &&
        (!url.searchParams.get("query")?.startsWith("#") ||
          item.player_tag === url.searchParams.get("query")) &&
        (url.searchParams.get("status") !== "mismatch" ||
          item.kind === "mismatch") &&
        (url.searchParams.get("status") !== "strikes" ||
          item.kind === "strike"),
    );
    data = {
      entries: filtered.slice(
        Number(url.searchParams.get("offset") || 0),
        Number(url.searchParams.get("offset") || 0) + 25,
      ),
      clans: [
        { tag: "#FWA", name: "Warriors United FWA", is_fwa: true },
        { tag: "#NORTH", name: "WU North" },
      ],
      total: filtered.length,
      ...(url.searchParams.get("query")?.startsWith("#")
        ? {
            streak: {
              count: url.searchParams.get("query") === "#P22ABC" ? 3 : 0,
              last_war_key: "fixture-played-war",
            },
          }
        : {}),
    };
  } else if (path.endsWith("/tracking/review")) {
    data = { manual_review_required: !reviewResolved, review_revision: 1 };
  } else if (path.endsWith("/tracking/resolve")) {
    reviewResolved = true;
    data = {
      resolved: true,
      receipt: { reason: "Fixture staff review", revision: 2 },
    };
  } else if (path.endsWith("/wars"))
    data = {
      wars: wars
        .map((item) =>
          item.war_key === "war-incomplete" &&
          new URLSearchParams(location.search).has("review")
            ? {
                ...item,
                manual_review_required: !reviewResolved,
                review_revision: 1,
              }
            : item,
        )
        .filter(
          (item) =>
            (!url.searchParams.get("clan") ||
              item.clan_tag === url.searchParams.get("clan")) &&
            (!url.searchParams.get("query") ||
              `${item.clan_name} ${item.opponent_name}`
                .toLowerCase()
                .includes(url.searchParams.get("query")!.toLowerCase())),
        ),
    };
  else if (path.endsWith("/targets"))
    data = {
      members,
      accounts: members[0].accounts.map((account) => ({
        ...account,
        town_hall: 18,
        discord_id: members[0].id,
        discord_name: members[0].name,
      })),
    };
  else if (path.endsWith("/members"))
    data = { members: members.map((item) => ({ ...item, accounts: [] })) };
  else if (path.includes("/members/") && path.endsWith("/accounts"))
    data = { member: members[0] };
  else if (path.endsWith("/settings/roles") && method === "PUT") {
    const body = JSON.parse(String(init?.body || "{}"));
    if (
      new URLSearchParams(location.search).has("settingsConflict") ||
      body.revision !== settings.revision
    ) {
      return new Response(
        JSON.stringify({ error: "Changed by someone else" }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      );
    }
    settings.revision += 1;
    settings.strike_limit = body.strike_limit;
    settings.excluded_roles = settings.roles.filter((role) =>
      body.role_ids.includes(role.id),
    );
    data = {
      revision: settings.revision,
      strike_limit: settings.strike_limit,
    };
  } else if (path.endsWith("/settings")) data = settings;
  else if (path.endsWith("/replacement-roster"))
    data = {
      accounts:
        url.searchParams.get("clan") === "#FWA"
          ? [
              {
                player_tag: "#P22ABC",
                player_name: "CastleFox",
                is_manual: true,
              },
              {
                player_tag: "#P44DEF",
                player_name: "MiniWolf",
                is_manual: false,
              },
              {
                player_tag: "#P88NEW",
                player_name: "StoneBird",
                is_manual: false,
              },
            ]
          : [
              {
                player_tag: "#P55GHI",
                player_name: "GreenOak",
                is_manual: true,
              },
              {
                player_tag: "#P66JKL",
                player_name: "RedRock",
                is_manual: false,
              },
            ],
    };
  else if (path.endsWith("/replacements"))
    data = {
      candidates: candidates.filter(
        (item) =>
          !url.searchParams.get("clan") ||
          item.clan_tag === url.searchParams.get("clan"),
      ),
      clans: [
        { tag: "#FWA", name: "Warriors United FWA", is_fwa: true },
        { tag: "#FWA2", name: "WU FWA Two", is_fwa: true },
        { tag: "#NORTH", name: "WU North", is_fwa: false },
      ],
    };
  else if (path.endsWith("/import/preview") || path.endsWith("/import/apply")) {
    const job_id = crypto.randomUUID();
    fixtureJobs.set(job_id, {
      reads: 0,
      result: path.endsWith("/preview")
        ? preview
        : {
            applied: 2,
            strikes: 1,
            added_strikes: 1,
            history_only: 1,
            duplicates: 0,
            excluded: 0,
            skipped: 0,
          },
    });
    data = { job_id, status: "running" };
  } else if (path.includes("/import/jobs/")) {
    const job_id = path.split("/").at(-1) || "";
    const job = fixtureJobs.get(job_id);
    if (job) {
      job.reads++;
      data =
        job.reads < 2
          ? { job_id, status: "running" }
          : { job_id, status: "complete", result: job.result };
    } else data = { job_id, status: "failed", error: "Job unavailable" };
  }
  return new Response(JSON.stringify(data), {
    status: method === "POST" ? 202 : 200,
    headers: { "Content-Type": "application/json" },
  });
};

const fixtureScope = new URLSearchParams(location.search).get("scope");
const fixturePermissions =
  fixtureScope === "add"
    ? ["strikes_add"]
    : fixtureScope === "remove"
      ? ["strikes_remove"]
      : fixtureScope === "manage"
        ? ["strikes"]
        : ["strikes", "strikes_add", "strikes_remove"];
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 20px" }}>
      <StrikesWorkspace
        permissions={fixturePermissions}
        isOwner={false}
        userId="fixture"
        markedDefault={
          new URLSearchParams(location.search).get("page") === "replacements"
        }
      />
    </main>
  </React.StrictMode>,
);
