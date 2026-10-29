import type { RosterClan } from "./roster";
export type SignupChange = {
  id: number;
  tag: string;
  player_name: string;
  user_id: string;
  action: string;
  from_pool: string;
  to_pool: string | null;
  assigned_clan_tag: string | null;
  assigned_clan_name: string | null;
  created_at: string;
};
export const signupPoolName = (pool: string | null) =>
  pool === "lazy" ? "Lazy CWL" : "Main CWL";
export function signupShortage(items: SignupChange[], clans: RosterClan[]) {
  const affected = new Set(items.map((item) => item.assigned_clan_tag));
  const below = clans.filter(
    (clan) =>
      affected.has(clan.tag) &&
      !clan.archived &&
      (clan.capacity === 15 || clan.capacity === 30) &&
      clan.assigned_count < clan.capacity,
  );
  below.sort(
    (a, b) =>
      b.capacity! - b.assigned_count - (a.capacity! - a.assigned_count) ||
      a.name.localeCompare(b.name),
  );
  const worst = below[0];
  return worst
    ? {
        text: `${worst.name} · ${worst.assigned_count} / ${worst.capacity} players${below.length > 1 ? ` · +${below.length - 1} more` : ""}`,
        item: items.find((item) => item.assigned_clan_tag === worst.tag)!,
      }
    : null;
}
export function signupActivitySummary(
  items: SignupChange[],
  clans: RosterClan[],
) {
  const count = items.length === 100 ? "100+" : String(items.length);
  const affected = new Set(items.map((item) => item.assigned_clan_tag));
  const below = clans.filter(
    (clan) =>
      affected.has(clan.tag) &&
      (clan.capacity === 15 || clan.capacity === 30) &&
      clan.assigned_count < clan.capacity,
  );
  if (below.length)
    return {
      danger: true,
      text: `${below.length === 1 ? `${below[0].name} below ${below[0].capacity}` : `${below.length} clans below war size`} · ${count} change${items.length === 1 ? "" : "s"}`,
    };
  const withdrawn = items.filter(
    (item) => item.action === "member_withdrawal",
  ).length;
  const switched = items.length - withdrawn;
  return {
    danger: false,
    text:
      withdrawn && switched
        ? `${count} assigned players changed: ${withdrawn} withdrew, ${switched} switched pool`
        : `${count} assigned player${items.length === 1 ? "" : "s"} ${withdrawn ? "withdrew" : "switched pool"}`,
  };
}
export function signupActivityIntro(version?: number) {
  return `Their spots are open in the draft.${version ? ` Members still see them on version ${version} until you publish again.` : ""}`;
}
