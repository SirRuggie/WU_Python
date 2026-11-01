import type { RosterAccount } from "./roster";

export type OwnerTimeZone = { label: string; offsetMinutes: number | null };
import zoneData from "../../../utils/member_timezone_data.json";
const offsets: Record<string, number> = zoneData.offsets;
export function ownerTimeZone(
  nickname?: string | null,
  saved?: OwnerTimeZone | null,
): OwnerTimeZone | null {
  if (saved && typeof saved.label === "string") {
    const checked = ownerTimeZone(`Member | ${saved.label}`);
    if (
      checked &&
      checked.offsetMinutes !== null &&
      checked.offsetMinutes === saved.offsetMinutes
    )
      return checked;
  }
  if (!nickname || !nickname.includes("|")) return null;
  const rawLabel = nickname
    .slice(nickname.lastIndexOf("|") + 1)
    .normalize("NFKC");
  const cleanLabel = Array.from(rawLabel)
    .filter((character) => {
      const point = character.codePointAt(0)!;
      return !zoneData.ignoredRanges.some(
        ([low, high]) => point >= low && point <= high,
      );
    })
    .join("")
    .trim()
    .replace(/\s+/gu, " ");
  const label = cleanLabel.toUpperCase();
  if (zoneData.caseSensitive.includes(label) && cleanLabel !== label)
    return { label, offsetMinutes: null };
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
  profiles: Record<string, OwnerTimeZone> = {},
): RosterAccount[] {
  const text = (a: string, b: string) =>
    a.localeCompare(b, undefined, { sensitivity: "base" });
  const rows = accounts.map((account) => ({
    account,
    nickname: owners[account.user_id] || "",
    zone: ownerTimeZone(owners[account.user_id], profiles[account.user_id]),
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
