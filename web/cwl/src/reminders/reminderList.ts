import type { Pool } from "../api";
import {
  nextReminderOccurrence,
  type Campaign,
  type Occurrence,
} from "../reminderCampaign";
import { variantErrors, type ReminderLookups } from "./reminderErrors";

export type ReminderPoolScope = "all" | Pool;
export type ReminderListFilters = { hasError: boolean; off: boolean };
export type ReminderListSort = "send_time" | "name";
export const reminderPools = ["main", "lazy"] as const;
export const scopePools = (scope: ReminderPoolScope): readonly Pool[] =>
  scope === "all" ? reminderPools : [scope];

export function variantIsOn(campaign: Campaign, id: string, pool: Pool) {
  const item = campaign.messages[id];
  return (
    !!item?.enabled &&
    !!item.variants[pool] &&
    item.variants[pool].enabled !== false
  );
}

export function reminderNextSend(
  campaign: Campaign,
  id: string,
  scope: ReminderPoolScope,
  schedule: Occurrence[],
  activated = true,
) {
  if (!activated) return undefined;
  return scopePools(scope)
    .filter((pool) => variantIsOn(campaign, id, pool))
    .map((pool) => nextReminderOccurrence(schedule, id, pool)?.run_at)
    .filter((value): value is string => !!value)
    .sort((left, right) => Date.parse(left) - Date.parse(right))[0];
}

export function initialEditorPool(
  campaign: Campaign,
  id: string,
  scope: ReminderPoolScope,
  lookups: ReminderLookups,
): Pool {
  if (scope !== "all") return scope;
  const main = variantErrors(campaign, id, "main", lookups).length > 0;
  const lazy = variantErrors(campaign, id, "lazy", lookups).length > 0;
  return lazy && !main ? "lazy" : "main";
}

export function reminderRows(
  campaign: Campaign,
  scope: ReminderPoolScope,
  lookups: ReminderLookups,
  schedule: Occurrence[],
  activated: boolean,
) {
  return Object.entries(campaign.messages)
    .filter(([id]) => id !== "roster")
    .map(([id, message]) => ({
      id,
      message,
      hasError: scopePools(scope).some(
        (pool) => variantErrors(campaign, id, pool, lookups).length > 0,
      ),
      off: scopePools(scope).some((pool) => !variantIsOn(campaign, id, pool)),
      next: reminderNextSend(campaign, id, scope, schedule, activated),
    }));
}

export function visibleReminderRows(
  rows: ReturnType<typeof reminderRows>,
  filters: ReminderListFilters,
  sort: ReminderListSort,
) {
  const names = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: "base",
  });
  return rows
    .filter(
      (row) => (!filters.hasError || row.hasError) && (!filters.off || row.off),
    )
    .sort((a, b) => {
      const byName = names.compare(
        a.message.label || a.id,
        b.message.label || b.id,
      );
      if (sort === "name") return byName;
      const left = a.next ? Date.parse(a.next) : Infinity;
      const right = b.next ? Date.parse(b.next) : Infinity;
      return left === right ? byName : left - right;
    });
}
