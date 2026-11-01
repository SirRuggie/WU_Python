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
  extraHosts: { tag: string; name: string; capacity: number | null }[] = [],
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
  for (const clan of extraHosts)
    map.set(clan.tag, { ...clan, pool: "lazy", accounts: [] });
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
  return [...map.values()]
    .map((g) => {
      const arrived = (a: (typeof g.accounts)[number]) =>
        comparisonLocation(records[a.tag], g.tag, now, g.name).state ===
        "arrived";
      const accounts = [...g.accounts].sort(
        (a, b) =>
          Number(arrived(a)) - Number(arrived(b)) ||
          a.player_name.localeCompare(b.player_name) ||
          a.tag.localeCompare(b.tag),
      );
      const late = accounts.filter((a) => !!g.tag && !arrived(a));
      return {
        ...g,
        key: g.tag || `unassigned:${g.pool}`,
        accounts,
        late,
        readiness: summarizeArrivalReadiness(
          accounts.map((a) => ({
            ...a,
            current_clan_tag: records[a.tag]?.current_clan_tag ?? null,
            current_clan_name: records[a.tag]?.current_clan_name ?? null,
            current_clan_checked_at: records[a.tag]?.current_clan_checked_at,
            assigned_clan_name: g.name,
          })),
          { now, capacity: g.capacity },
        ),
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
