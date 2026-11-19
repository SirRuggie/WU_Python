/** URL identity belongs to a recruit account or an explicit typed weight. */
export type SlotSearch = {
  slotWeights: number[];
  slotClans: string[];
  slotMember: string;
  slotTownHall?: number | null;
  slotExpanded?: Record<string, number>;
};

type SlotIdentity = {
  weight: number;
  source?: string;
  account_tag?: string | null;
};

export function slotGroupKey(group: SlotIdentity, occurrence?: number) {
  return group.source === "saved" && group.account_tag
    ? `a${group.account_tag.toUpperCase()}`
    : `w${group.weight}${occurrence === undefined ? "" : `o${occurrence}`}`;
}

/** Occurrence counts only typed groups of the same weight, in input order. */
export function slotGroupKeys(groups: SlotIdentity[]) {
  const occurrences = new Map<number, number>();
  return groups.map((group) => {
    if (group.source === "saved" && group.account_tag)
      return slotGroupKey(group);
    const occurrence = (occurrences.get(group.weight) ?? 0) + 1;
    occurrences.set(group.weight, occurrence);
    return slotGroupKey(group, occurrence);
  });
}

export function slotVisibleCount(
  group: SlotIdentity,
  key: string,
  expanded: Record<string, number>,
) {
  return expanded[key] ?? expanded[slotGroupKey(group)] ?? 3;
}

export function parseSlotExpansion(values: string[]) {
  const result: Record<string, number> = {};
  for (const value of values.slice(0, 25)) {
    const match =
      /^(w([1-9][0-9]{0,5})(?:o[1-5])?|a#[0289PYLQGRJCUV]{3,15}):([0-9]{1,6})$/.exec(
        value,
      );
    if (!match || (match[1][0] === "w" && Number(match[2]) > 500000)) continue;
    result[match[1]] = Math.max(3, Math.min(100, Number(match[3])));
  }
  return result;
}

export function normalizedSlotSearch(search: SlotSearch): SlotSearch {
  return {
    slotWeights: search.slotWeights,
    slotClans: search.slotClans,
    slotMember: search.slotMember,
    slotTownHall: search.slotTownHall ?? null,
    slotExpanded: parseSlotExpansion(
      Object.entries(search.slotExpanded ?? {}).map(
        ([key, count]) => `${key}:${count}`,
      ),
    ),
  };
}

export function slotSearchKey(search: SlotSearch) {
  const value = normalizedSlotSearch(search);
  return JSON.stringify([
    value.slotWeights,
    value.slotClans,
    value.slotMember,
    value.slotTownHall,
    Object.entries(value.slotExpanded!).sort(([a], [b]) => a.localeCompare(b)),
  ]);
}
