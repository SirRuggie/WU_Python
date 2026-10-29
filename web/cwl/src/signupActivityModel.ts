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
export function signupChangeLabel(items: SignupChange[]) {
  const count = items.length === 100 ? "100+" : items.length;
  return `${count} signup change${items.length === 1 ? "" : "s"} to review · Review ›`;
}
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
export function signupActivityIntro(version?: number) {
  return `Their spots are open in the draft.${version ? ` Members still see them on version ${version} until you publish again.` : ""}`;
}
