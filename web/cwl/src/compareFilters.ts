import type { RosterAccount, RosterClan } from "./roster";
import { leagueValue, matchesLeague, matchesTownHall } from "./ClanFilters";
export function comparisonFilters(
  accounts: RosterAccount[],
  clans: RosterClan[],
  chosen: string[],
  leagues: string[],
  townHalls: string[],
) {
  const byTag = new Map(clans.map((clan) => [clan.tag, clan]));
  const poolAccounts = accounts.filter(
    (account) =>
      account.assigned_clan_tag && byTag.has(account.assigned_clan_tag),
  );
  const selectedAccounts = poolAccounts.filter((account) =>
    chosen.includes(account.assigned_clan_tag!),
  );
  const halls = [
    ...new Set([
      ...poolAccounts.map((account) =>
        account.town_hall === null ? "Unknown TH" : `TH ${account.town_hall}`,
      ),
      ...townHalls,
    ]),
  ].sort(
    (a, b) =>
      (Number(b.replace("TH ", "")) || -1) -
      (Number(a.replace("TH ", "")) || -1),
  );
  const tiers = [
    ...new Set([
      ...clans.map((clan) => leagueValue(clan.cwl_league)),
      ...leagues,
    ]),
  ];
  const leagueMatches = (account: RosterAccount) =>
    matchesLeague(byTag.get(account.assigned_clan_tag!)?.cwl_league, leagues);
  return {
    townHalls: halls.map((value) => ({
      value,
      label: value,
      count: selectedAccounts.filter(
        (account) =>
          leagueMatches(account) && matchesTownHall(account.town_hall, [value]),
      ).length,
    })),
    leagues: tiers.map((value) => ({
      value,
      label: value,
      count: selectedAccounts.filter(
        (account) =>
          matchesTownHall(account.town_hall, townHalls) &&
          matchesLeague(byTag.get(account.assigned_clan_tag!)?.cwl_league, [
            value,
          ]),
      ).length,
    })),
    count: selectedAccounts.filter(
      (account) =>
        leagueMatches(account) && matchesTownHall(account.town_hall, townHalls),
    ).length,
  };
}
