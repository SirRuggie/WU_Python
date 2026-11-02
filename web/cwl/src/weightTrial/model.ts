export type Member = {
  tag: string;
  name: string;
  town_hall: number | null;
  weight: number | null;
  revision: number;
  storages?: number | null;
  storages_saved?: boolean;
  current_member?: boolean;
  war_position?: number;
  clan_position?: number;
};
export type WarLineup = {
  order: Record<string, number>;
  names?: Record<string, string>;
  town_halls?: Record<string, number>;
  state: string;
  unverified_identity?: boolean;
  end_time?: string | null;
  cached?: boolean;
  captured_at?: string;
  opponent?: string | null;
};
export type Roster = {
  clan: { tag: string; name: string };
  members: Member[];
  weight_members?: Member[];
  checked_at: string;
  current_members_count?: number;
  war_lineups?: WarLineup[];
  last_saved?: {
    at: string;
    discord_id: string;
    name: string;
    imported: boolean;
  } | null;
  war_source?: {
    names?: Record<string, string>;
    state: string;
    unverified_identity?: boolean;
    cached?: boolean;
    captured_at?: string;
    end_time?: string | null;
    opponent?: string | null;
  } | null;
  war_order?: Record<string, number> | null;
};
/** A departed player's optional details belong to the selected saved war. */
export function selectedRoster(
  roster: Roster | null,
  selected = "",
): Roster | null {
  if (!roster) return null;
  const lineups = roster.war_lineups || [];
  const lineup = lineups.find((war) => war.end_time === selected) || lineups[0];
  const order = lineup?.order || roster.war_order;
  return {
    ...roster,
    war_order: order,
    war_source: lineup || roster.war_source,
    members: (roster.weight_members || roster.members)
      .filter((row) => row.current_member !== false || order?.[row.tag])
      .map((row) =>
        row.current_member !== false || !lineup
          ? row
          : {
              ...row,
              name: lineup.names?.[row.tag] || row.tag,
              town_hall: lineup.town_halls?.[row.tag] ?? null,
            },
      ),
  };
}

export function draftsForRoster(roster: Roster, selected = "") {
  return Object.fromEntries(
    [
      ...(roster.weight_members || roster.members),
      ...(selectedRoster(roster, selected)?.members || []),
    ].map((row) => [row.tag, draftFor(row)]),
  );
}

export type Draft = { storages: string; loot: string; full: string };
export function draftFor(row: Member): Draft {
  const knownStorages = row.storages_saved === false ? null : row.storages;
  const storages =
    knownStorages ?? (row.town_hall == null ? null : row.town_hall > 8 ? 5 : 4);
  return {
    storages: storages == null ? "" : String(storages),
    full: row.weight === null ? "" : String(row.weight),
    loot:
      row.weight === null || storages == null
        ? ""
        : String(row.weight / storages),
  };
}
export function whole(text: string, max: number): number {
  const clean = text.trim();
  const match = clean.match(/^(\d+|\d{1,3}(?:,\d{3})+)(?:\.(\d+))?([kK])?$/);
  // Scale the digit string, never a binary floating-point fraction.
  const fraction = match?.[2] || "";
  const places = match?.[3] ? 3 : 0;
  const exact = match && !/[1-9]/.test(fraction.slice(places));
  const digits = match
    ? match[1].replace(/,/g, "") + fraction.slice(0, places).padEnd(places, "0")
    : "";
  const value = exact ? Number(digits) : NaN;
  if (!Number.isSafeInteger(value) || value < 1 || value > max)
    throw new Error(
      `Enter a whole number from 1 to ${max.toLocaleString()}, such as 35,800 or 35.8k.`,
    );
  return value;
}
export function formatFull(value: string) {
  try {
    return `${(whole(value, 9999999) / 1000).toLocaleString("en-US", { maximumFractionDigits: 3 })}k`;
  } catch {
    return value.trim() ? "—" : "N/A";
  }
}
export function isMissing(row: Member, draft: Draft) {
  return row.revision === 0 && !draft.full.trim() && !draft.loot.trim();
}
export function gaps(roster: Roster) {
  const current = new Set(roster.members.map((row) => row.tag));
  return Object.entries(roster.war_order || {})
    .filter(([tag]) => !current.has(tag))
    .map(([tag, position]) => ({
      tag,
      position,
      name: roster.war_source?.names?.[tag],
    }));
}
export function validateDraft(draft: Draft) {
  if (!draft.storages.trim())
    throw new Error(
      "Choose storages; the saved lineup has no Town Hall default.",
    );
  const storages = whole(draft.storages, 5);
  if (!draft.full.trim() && !draft.loot.trim())
    return { storages, weight: null };
  const weight = whole(draft.full, 999999);
  if (weight % 1000)
    throw new Error(
      "Full weight must end in 000. Correct Loot or Full weight; values are never rounded.",
    );
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
          "A saved war player is missing from this view. Refresh members before copying.",
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

export function orderedMembers(roster: Roster | null): Member[] {
  if (!roster) return [];
  const order = roster.war_order;
  return [...roster.members].sort(
    (a, b) =>
      (order?.[a.tag] ?? 1000) - (order?.[b.tag] ?? 1000) ||
      (a.clan_position ?? 1000) - (b.clan_position ?? 1000) ||
      a.tag.localeCompare(b.tag),
  );
}
export function orderLabel(roster: Roster): string {
  if (roster.war_source?.unverified_identity)
    return "War identity unavailable · only current members can be saved. Refresh members to check again.";
  if (!roster.war_order)
    return "Clan order · War lineup unavailable. Positions are not war placements.";
  if (roster.war_source?.cached) {
    const captured = roster.war_source.captured_at;
    const date = captured
      ? new Date(captured).toLocaleString()
      : "unknown time";
    return `Saved war lineup · Captured ${date}. Check this matches the spreadsheet before copying.`;
  }
  const state = roster.war_source?.state;
  return state === "preparation"
    ? "Preparation day · Upcoming war order"
    : state === "inWar"
      ? "Current war · Battle day order"
      : state === "warEnded"
        ? "Last completed war · War order"
        : "War lineup order";
}

// Advisory checks mirror the destination sheet, not authoritative FWA rules.
export function sheetWeightWarning(
  tag: string,
  rows: Member[],
  drafts: Record<string, Draft>,
  order: Roster["war_order"],
): string {
  const weightFor = (row: Member) => {
    try {
      return validateDraft(drafts[row.tag] ?? draftFor(row)).weight;
    } catch {
      return null; // The editor shows its input error instead.
    }
  };
  const row = rows.find((member) => member.tag === tag);
  if (!row) return "";
  const raw =
    drafts[tag]?.full ?? (row.weight === null ? "" : String(row.weight));
  if (/^\d+$/.test(raw) && Number(raw) % 1000)
    return "Weight must end in 000 for the FWA sheet.";
  const weight = weightFor(row);
  if (weight === null) return "";
  if (weight % 1000 !== 0) return "Weight must end in 000 for the FWA sheet.";
  if (weight < 42000)
    return "Weight is below the FWA sheet’s minimum of 42,000.";
  if (weight > 180000)
    return "Weight exceeds the FWA sheet’s maximum of 180,000.";
  const position = order?.[tag];
  if (!position || position <= 1) return "";
  const previous = rows.find((member) => order?.[member.tag] === position - 1);
  const previousWeight = previous ? weightFor(previous) : null;
  if (previousWeight !== null && weight > previousWeight)
    return `Weight is higher than player ${position - 1} above. Double-check; this can sometimes be correct.`;
  return "";
}
