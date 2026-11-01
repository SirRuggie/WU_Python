import type { DeclarationExtraClan } from "./declarationExtras";
import { comparisonLocation, type LocationRecords } from "./comparisonLocation";
import { summarizeArrivalReadiness } from "./arrivalReadiness";
import type { DeclarationData } from "./declarationData";
import type { RosterSnapshot } from "./roster";
import { discordContact } from "./DiscordContact";
export function declarationGroups(
  data: DeclarationData,
  snapshot: RosterSnapshot,
  records: LocationRecords,
  now: number,
  extras: DeclarationExtraClan[] = [],
) {
  const map = new Map<
    string,
    {
      tag: string;
      name: string;
      pool: "main" | "lazy";
      capacity: number | null;
      accounts: RosterSnapshot["accounts"];
    }
  >();
  for (const a of snapshot.accounts) {
    const tag = a.assigned_clan_tag || "";
    const source = data.arrival.accounts.find((x) => x.tag === a.tag)!;
    const key = tag || `unassigned:${source.hosting_pool}`;
    if (!map.has(key))
      map.set(key, {
        tag,
        name: source.assigned_clan_name || tag || "Awaiting placement",
        pool: source.hosting_pool,
        capacity:
          data.roster.clans.find((c) => c.tag === tag)?.capacity ?? null,
        accounts: [],
      });
    map.get(key)!.accounts.push(a);
  }
  for (const extra of extras) {
    if (extra.status === 'current' && extra.fillers?.length && !map.has(extra.tag))
      map.set(extra.tag, {tag: extra.tag, name: extra.name, pool: 'lazy', capacity: extra.capacity, accounts: []});
  }
  return [...map.values()]
    .map((g) => {
      const extra = extras.find(
        (c) => c.tag === g.tag && c.status === "current",
      );
      const observed = (a: (typeof g.accounts)[number]) =>
        extra?.fillers?.some((f) => f.tag === a.tag)
          ? {
              current_clan_tag: g.tag,
              current_clan_name: g.name,
              current_clan_checked_at: extra.checked_at || undefined,
            }
          : records[a.tag];
      const arrived = (a: (typeof g.accounts)[number]) =>
        comparisonLocation(observed(a), g.tag, now, g.name).state === "arrived";
      const accounts = [...g.accounts].sort(
        (a, b) =>
          Number(arrived(a)) - Number(arrived(b)) ||
          a.player_name.localeCompare(b.player_name) ||
          a.tag.localeCompare(b.tag),
      );
      const late = accounts.filter((a) => !!g.tag && !arrived(a));
      const presentFillers =
        extra?.fillers?.filter((f) => !accounts.some((a) => a.tag === f.tag)) ||
        [];
      const readiness = summarizeArrivalReadiness(
        [
          ...accounts.map((a) => ({
            ...a,
            current_clan_tag: observed(a)?.current_clan_tag ?? null,
            current_clan_name: observed(a)?.current_clan_name ?? null,
            current_clan_checked_at: observed(a)?.current_clan_checked_at,
            assigned_clan_name: g.name,
          })),
          ...presentFillers.map((f) => ({
            tag: f.tag,
            assigned_clan_tag: g.tag,
            assigned_clan_name: g.name,
            current_clan_tag: g.tag,
            current_clan_name: g.name,
            current_clan_checked_at: extra?.checked_at || undefined,
          })),
        ],
        { now, capacity: g.capacity },
      );
      return {
        ...g,
        key: g.tag || `unassigned:${g.pool}`,
        accounts,
        late,
        checkingCount: g.tag
          ? accounts.filter(
              (a) =>
                comparisonLocation(observed(a), g.tag, now, g.name).state ===
                "checking",
            ).length
          : 0,
        readiness,
      };
    })
    .sort(
      (a, b) => Number(!a.tag) - Number(!b.tag) || a.name.localeCompare(b.name),
    );
}
export function declarationMentions(accounts: RosterSnapshot["accounts"]) {
  const ids = [
    ...new Set(
      accounts
        .filter((a) => discordContact(a.user_id).href)
        .map((a) => a.user_id),
    ),
  ];
  return {
    text: ids.map((id) => `<@${id}>`).join(" "),
    count: ids.length,
    unlinked: accounts
      .filter((a) => !discordContact(a.user_id).href)
      .map((a) => a.player_name),
  };
}
