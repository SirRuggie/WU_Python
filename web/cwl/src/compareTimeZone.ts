import type { RosterAccount } from "./roster";

export type OwnerTimeZone = { label: string; offsetMinutes: number | null };
const offsets: Record<string, number> = {
  UTC: 0,
  GMT: 0,
  BST: 60,
  WET: 0,
  CET: 60,
  CEST: 120,
  EET: 120,
  EEST: 180,
  MSK: 180,
  IST: 330,
  PKT: 300,
  SGT: 480,
  AWST: 480,
  JST: 540,
  AEST: 600,
  AEDT: 660,
  NZST: 720,
  EST: -300,
  EDT: -240,
  CST: -360,
  CDT: -300,
  MST: -420,
  MDT: -360,
  PST: -480,
  PDT: -420,
  AST: -240,
  HST: -600,
  AKST: -540,
  EASTERN: -300,
  CENTRAL: -360,
  PACIFIC: -480,
  MOUNTAIN: -420,
};
export function ownerTimeZone(nickname?: string | null): OwnerTimeZone | null {
  if (!nickname || !nickname.includes(" | ")) return null;
  const label = nickname
    .slice(nickname.lastIndexOf(" | ") + 3)
    .replace(
      /[\p{Extended_Pictographic}\p{Regional_Indicator}\uFE0F\u200D]/gu,
      "",
    )
    .trim()
    .replace(/\s+/g, " ")
    .toUpperCase();
  if (!label) return null;
  if (Object.hasOwn(offsets, label))
    return { label, offsetMinutes: offsets[label] };
  const numeric = /^(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::([0-5]\d))?$/.exec(
    label,
  );
  if (numeric) {
    const hours = Number(numeric[2]),
      minutes = Number(numeric[3] || 0);
    if (hours < 14 || (hours === 14 && minutes === 0))
      return {
        label,
        offsetMinutes: (numeric[1] === "-" ? -1 : 1) * (hours * 60 + minutes),
      };
  }
  return { label, offsetMinutes: null };
}

export function sortTimeZoneAccounts(
  accounts: RosterAccount[],
  owners: Record<string, string>,
): RosterAccount[] {
  const text = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: "base" });
  const rows = accounts.map((account) => ({
    account,
    nickname: owners[account.user_id] || "",
    zone: ownerTimeZone(owners[account.user_id]),
  }));
  const rank = (zone: OwnerTimeZone | null) =>
    zone?.offsetMinutes != null ? 0 : zone ? 1 : 2;
  return rows
    .sort(
      (a, b) =>
        rank(a.zone) - rank(b.zone) ||
        (rank(a.zone) === 0
          ? a.zone!.offsetMinutes! - b.zone!.offsetMinutes!
          : rank(a.zone) === 1
            ? text(a.zone!.label, b.zone!.label)
            : 0) ||
        text(a.nickname, b.nickname) ||
        text(
          a.account.user_id || a.account.tag,
          b.account.user_id || b.account.tag,
        ) ||
        (b.account.effective_weight ?? -Infinity) -
          (a.account.effective_weight ?? -Infinity) ||
        text(a.account.player_name, b.account.player_name) ||
        text(a.account.tag, b.account.tag),
    )
    .map((row) => row.account);
}
