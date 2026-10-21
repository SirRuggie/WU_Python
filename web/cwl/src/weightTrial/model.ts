export type Member = {
  tag: string;
  name: string;
  town_hall: number | null;
  weight: number | null;
  revision: number;
  storages?: number;
  clan_position?: number;
};
export type Roster = {
  clan: { tag: string; name: string };
  members: Member[];
  checked_at: string;
  war_order?: Record<string, number> | null;
};
export type Draft = { storages: string; loot: string; full: string };
export function draftFor(row: Member): Draft {
  const storages = row.storages ?? ((row.town_hall ?? 18) > 8 ? 5 : 4);
  return {
    storages: String(storages),
    full: row.weight === null ? "" : String(row.weight),
    loot: row.weight === null ? "" : String(row.weight / storages),
  };
}
function whole(text: string, max: number): number {
  const clean = text.trim().replace(/,/g, "");
  if (!/^\d+$/.test(clean) || Number(clean) < 1 || Number(clean) > max)
    throw new Error(`Enter a whole number from 1 to ${max.toLocaleString()}.`);
  return Number(clean);
}
export function validateDraft(draft: Draft) {
  const storages = whole(draft.storages, 5);
  if (!draft.full.trim() && !draft.loot.trim())
    return { storages, weight: null };
  const weight = whole(draft.full, 999999);
  const loot = whole(draft.loot, 999999);
  if (loot * storages !== weight)
    throw new Error(
      "Weight must divide evenly by storages. Check loot and full weight.",
    );
  return { storages, weight };
}
export function editDraft(
  draft: Draft,
  field: keyof Draft,
  text: string,
): Draft {
  const next = { ...draft, [field]: text };
  try {
    const storages = whole(next.storages, 5);
    if (field === "full")
      next.loot = text.trim() ? String(whole(text, 999999) / storages) : "";
    else
      next.full = next.loot.trim()
        ? String(whole(next.loot, 999999) * storages)
        : "";
  } catch {
    /* Keep invalid input visible for correction; saving validates both fields. */
  }
  return next;
}
export function warLoot(
  rows: Member[],
  drafts: Record<string, Draft>,
  order: Record<string, number> | null | undefined,
) {
  if (!order || !Object.keys(order).length)
    throw new Error(
      "Refresh members to load an available war lineup before copying.",
    );
  const sorted = Object.entries(order).sort((a, b) => a[1] - b[1]);
  if (sorted.some(([, position], i) => position !== i + 1))
    throw new Error("War lineup is incomplete. Refresh members.");
  return sorted
    .map(([tag]) => {
      const row = rows.find((row) => row.tag === tag);
      if (!row || !drafts[tag])
        throw new Error(
          "A war player is no longer in this clan. Match the spreadsheet manually using the full table export.",
        );
      const { weight, storages } = validateDraft(drafts[tag]);
      if (weight === null)
        throw new Error(
          `Enter loot for ${row.name} before copying the war column.`,
        );
      return String(weight / storages);
    })
    .join("\n");
}

export function copyTable(rows: Member[], drafts: Record<string, Draft>) {
  const safe = (text: string) => "'" + text.replace(/[\t\r\n]/g, " ");
  return [
    "Clan position\tPlayer tag\tPlayer name\tTH\tStorages\tLoot\tFull weight",
    ...rows.map((row, index) => {
      const draft = drafts[row.tag];
      const { weight, storages } = validateDraft(draft);
      return [
        row.clan_position ?? index + 1,
        safe(row.tag),
        safe(row.name),
        row.town_hall ?? "",
        storages,
        weight === null ? "" : weight / storages,
        weight ?? "",
      ].join("\t");
    }),
  ].join("\n");
}

export function pasteColumn(
  rows: Member[],
  drafts: Record<string, Draft>,
  start: number,
  field: keyof Draft,
  text: string,
) {
  const cells = text.replace(/\r/g, "").replace(/\n$/, "").split("\n");
  if (
    cells.length > rows.length - start ||
    cells.some((cell) => cell.includes("\t"))
  )
    throw new Error(
      "Paste one column, with no more values than remaining players.",
    );
  const updates: Record<string, Draft> = {};
  cells.forEach((cell, offset) => {
    const row = rows[start + offset];
    const next = editDraft(drafts[row.tag], field, cell);
    validateDraft(next);
    updates[row.tag] = next;
  });
  return updates;
}
