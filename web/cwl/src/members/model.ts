import type { Member } from "../memberTimezones/types";
export type DirectoryMember = Member & {
  role_ids: string[];
  username?: string;
};
export type MemberStatus = "all" | "needs_flag" | "no_time_zone" | "check_name";
export type MemberFilters = {
  query: string;
  status: MemberStatus;
  roles: readonly string[];
  bots: boolean;
  selectedOnly: boolean;
};
export const emptyFilters: MemberFilters = {
  query: "",
  status: "all",
  roles: [],
  bots: false,
  selectedOnly: false,
};
const fold = (value: string) => value.normalize("NFKC").toLocaleLowerCase();
/** This is the existing directory's normalization and matching rule, now shared. */
export function matchesMember(
  member: Member & { username?: string },
  query: string,
) {
  return fold(
    `${member.name} ${member.nickname || ""} ${member.discord_profile?.username || member.username || ""} ${member.discord_id}`,
  ).includes(fold(query.trim()));
}
export function memberStatus(member: Member, status: MemberStatus) {
  const offset =
    member.profile?.utc_offset_minutes ?? member.parsed?.offsetMinutes;
  if (status === "needs_flag") return !member.profile?.flag;
  if (status === "no_time_zone") return offset == null;
  if (status === "check_name")
    return !member.nickname || member.status === "Unknown";
  return true;
}
export function filterMembers(
  rows: readonly DirectoryMember[],
  filters: MemberFilters,
  selected: ReadonlySet<string>,
) {
  return rows.filter(
    (row) =>
      (filters.bots || !row.bot) &&
      matchesMember(row, filters.query) &&
      memberStatus(row, filters.status) &&
      (!filters.roles.length ||
        filters.roles.some((role) =>
          role === "none"
            ? row.role_ids.length === 0
            : row.role_ids.includes(role),
        )) &&
      (!filters.selectedOnly || selected.has(row.discord_id)),
  );
}
export function statusCounts(
  rows: readonly DirectoryMember[],
  filters: MemberFilters,
  selected: ReadonlySet<string>,
) {
  return Object.fromEntries(
    (["all", "needs_flag", "no_time_zone", "check_name"] as const).map(
      (status) => [
        status,
        filterMembers(rows, { ...filters, status }, selected).length,
      ],
    ),
  ) as Record<MemberStatus, number>;
}
export function localMemberTime(member: Member, now = new Date()) {
  const offset =
    member.profile?.utc_offset_minutes ?? member.parsed?.offsetMinutes;
  if (offset == null) return null;
  const shifted = new Date(now.getTime() + offset * 60000);
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(shifted);
}
