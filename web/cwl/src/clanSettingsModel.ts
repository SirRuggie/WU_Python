import { outsideComparisonRange } from "./comparePresentation";
import type { Pool } from "./api";
import type { RosterAccount, RosterClan } from "./roster";

export type ClanRules = {
  pool: Pool;
  capacity: number;
  min_weight: number | null;
  max_weight: number | null;
};

export function settingsClans(clans: RosterClan[], pool: Pool) {
  return clans.filter(
    (clan) => !clan.archived && (!clan.pool || clan.pool === pool),
  );
}

export function poolChangeReason(clan: RosterClan, pool: Pool) {
  return clan.pool && clan.pool !== pool && clan.assigned_count > 0
    ? `Can't move to ${pool === "main" ? "Main" : "Lazy"} CWL: ${clan.assigned_count} players are assigned here. Assign them elsewhere first.`
    : "";
}

export function weightKeystroke(value: string) {
  return /^\d*(?:\.\d*)?$/.test(value);
}

export function settingsWeight(value: string): {
  value: number | null;
  error: string;
} {
  if (value === "") return { value: null, error: "" };
  if (!weightKeystroke(value) || !/\d/.test(value))
    return {
      value: null,
      error: "Enter a weight using digits and one decimal point.",
    };
  if (Number(value) === 0)
    return {
      value: null,
      error: "Enter a weight above 0, or leave blank for no limit.",
    };
  const [whole, fraction = ""] = value.split(".");
  const weight = Number(whole || "0") * 1000 + Number(fraction.padEnd(3, "0"));
  if (
    fraction.length > 3 ||
    !Number.isSafeInteger(weight) ||
    weight > 1_000_000_000
  )
    return {
      value: null,
      error:
        "Use up to 3 decimal places and a weight no greater than 1000000k.",
    };
  return { value: weight, error: "" };
}

export function capacityState(count: number, capacity: number | null) {
  return capacity && count > capacity
    ? "over"
    : capacity && count === capacity
      ? "full"
      : "room";
}

export function rangeImpact(
  accounts: RosterAccount[],
  tag: string,
  min: number | null,
  max: number | null,
) {
  return accounts.filter(
    (account) =>
      account.assigned_clan_tag === tag &&
      outsideComparisonRange(account.effective_weight, {
        min_weight: min,
        max_weight: max,
      }),
  );
}
