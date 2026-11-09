import { memberName, type ActivityGroup } from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";

export const activityPageSize = 25;
export type ActivityGroupKey = {
  key: string;
  kind: "clan" | "discord" | "unlinked";
  /** Sort label; never an ID. */
  label: string;
  discordId?: string;
};
export const unlinkedLabel = "No linked member";
export function groupKey(
  row: ActivityAccount,
  group: ActivityGroup,
): ActivityGroupKey | null {
  if (group === "clan") {
    const tag =
      (row.left_clan ? row.last_clan_tag : row.current_clan_tag) || "";
    const name =
      (row.left_clan ? row.last_clan_name : row.current_clan_name) || "No clan";
    return { key: `clan:${tag}`, kind: "clan", label: name };
  }
  if (group === "discord") {
    return row.discord_id
      ? {
          key: `discord:${row.discord_id}`,
          kind: "discord",
          label: memberName(row) || "",
          discordId: row.discord_id,
        }
      : { key: "unlinked", kind: "unlinked", label: unlinkedLabel };
  }
  return null;
}
/** Groups ordered by label (unlinked last); rows keep the chosen sort inside a group. */
export function groupRows(rows: ActivityAccount[], group: ActivityGroup) {
  const groups = new Map<
    string,
    { head: ActivityGroupKey; rows: ActivityAccount[] }
  >();
  for (const row of rows) {
    const head = groupKey(row, group)!;
    const found = groups.get(head.key);
    if (found) found.rows.push(row);
    else groups.set(head.key, { head, rows: [row] });
  }
  return [...groups.values()].sort(
    (a, b) =>
      Number(a.head.kind === "unlinked") - Number(b.head.kind === "unlinked") ||
      Number(!a.head.label) - Number(!b.head.label) ||
      a.head.label.localeCompare(b.head.label, undefined, {
        sensitivity: "base",
      }) ||
      a.head.key.localeCompare(b.head.key),
  );
}
/**
 * Pages of rows. A group is never split: a page closes before the group that
 * would pass the page size, and one larger group gets a page of its own.
 */
export function activityPages(
  rows: ActivityAccount[],
  group: ActivityGroup,
): ActivityAccount[][] {
  const pages: ActivityAccount[][] = [];
  if (group === "none") {
    for (let i = 0; i < rows.length; i += activityPageSize)
      pages.push(rows.slice(i, i + activityPageSize));
    return pages;
  }
  let current: ActivityAccount[] = [];
  for (const { rows: members } of groupRows(rows, group)) {
    if (current.length && current.length + members.length > activityPageSize) {
      pages.push(current);
      current = [];
    }
    current.push(...members);
  }
  if (current.length) pages.push(current);
  return pages;
}
