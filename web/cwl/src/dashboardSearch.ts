import type { Account, Clan } from "./api";
export type GameResult = {
  kind: "player" | "clan";
  tag: string;
  name: string;
  source: "family" | "clash";
  town_hall?: number;
  clan_name?: string;
  clan_tag?: string;
  level?: number;
  members?: number;
  badge_url?: string | null;
  trophies?: number;
  war_league?: string;
  public_war_log?: boolean;
};
export type GameSearchResponse = {
  results: GameResult[];
  notes?: string[];
  errors?: string[];
};

export function gameTag(value: string) {
  const token = value.trim().toUpperCase().replace(/O/g, "0").replace(/^#/, "");
  return /^[0289PYLQGRJCUV]{3,12}$/.test(token) ? `#${token}` : null;
}
/** Already-authorized loaded view data only; never fetch or cache user rows. */
export function familyGameResults(
  accounts: Account[],
  family: Clan[],
  query: string,
): GameResult[] {
  const needle = query
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase()
    .replace(/^#/, "");
  if (!needle) return [];
  const byClan = new Map<string, GameResult>();
  for (const clan of family)
    byClan.set(clan.tag, {
      kind: "clan",
      tag: clan.tag,
      name: clan.name,
      source: "family",
    });
  for (const account of accounts)
    if (account.current_clan_tag && !byClan.has(account.current_clan_tag))
      byClan.set(account.current_clan_tag, {
        kind: "clan",
        tag: account.current_clan_tag,
        name: account.current_clan_name || account.current_clan_tag,
        source: "family",
      });
  const rows: GameResult[] = [
    ...accounts.map((account) => ({
      kind: "player" as const,
      tag: account.tag,
      name: account.name,
      source: "family" as const,
      town_hall: account.town_hall ?? undefined,
      clan_name: account.current_clan_name ?? undefined,
      clan_tag: account.current_clan_tag ?? undefined,
    })),
    ...byClan.values(),
  ];
  const token = gameTag(query);
  return rows.filter(
    (row) =>
      [row.name, row.tag, row.clan_name, row.clan_tag].some((value) =>
        value?.toLowerCase().includes(needle),
      ) ||
      (token !== null && (row.tag === token || row.clan_tag === token)),
  );
}
export function mergeGameResults(
  family: GameResult[],
  publicRows: GameResult[],
) {
  const seen = new Set(family.map((row) => `${row.kind}:${row.tag}`));
  return [
    ...family,
    ...publicRows.filter(
      (row) => row.source === "clash" && !seen.has(`${row.kind}:${row.tag}`),
    ),
  ];
}
