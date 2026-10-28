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
export function signupActivitySummary(
  items: SignupChange[],
  clans: RosterClan[],
) {
  const count = items.length === 100 ? "100+" : String(items.length);
  const below = items
    .map((item) => clans.find((clan) => clan.tag === item.assigned_clan_tag))
    .find(
      (clan) =>
        clan &&
        (clan.capacity === 15 || clan.capacity === 30) &&
        clan.assigned_count < clan.capacity,
    );
  if (below)
    return {
      danger: true,
      text: `${count} signup change${items.length === 1 ? "" : "s"} · ${below.name} now below ${below.capacity}`,
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
