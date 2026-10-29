import type { RosterAccount, RosterClan } from "./roster";
import { compactRosterWeight } from "./rosterCompactWeight";
import type { PublishedComparisonAccount } from "./useComparisonLocations";
export function comparisonWeightRange(
  clan: Pick<RosterClan, "min_weight" | "max_weight">,
) {
  const min = clan.min_weight,
    max = clan.max_weight;
  return min !== null && max !== null
    ? `${compactRosterWeight(min)}–${compactRosterWeight(max)}`
    : min !== null
      ? `${compactRosterWeight(min)}+`
      : max !== null
        ? `under ${compactRosterWeight(max)}`
        : "";
}
export function outsideComparisonRange(
  weight: number | null,
  clan: Pick<RosterClan, "min_weight" | "max_weight">,
) {
  return (
    weight !== null &&
    ((clan.min_weight !== null && weight < clan.min_weight) ||
      (clan.max_weight !== null && weight >= clan.max_weight))
  );
}
export function comparisonPublishNote(
  account: RosterAccount,
  published: PublishedComparisonAccount[] | null,
) {
  if (published === null) return "";
  const previous = published.find((item) => item.tag === account.tag);
  if (!previous) return "Not published yet";
  return previous.assigned_clan_tag !== account.assigned_clan_tag
    ? `Moved since publish · members still see ${previous.assigned_clan_name || previous.assigned_clan_tag || "Unassigned"}`
    : "";
}
