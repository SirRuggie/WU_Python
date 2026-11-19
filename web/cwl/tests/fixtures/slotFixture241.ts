import type { SlotCandidate, SlotResponse } from "../../src/SlotResults";

export const recruitId241 = "241000000000000001";
export const recruitAccounts241 = [
  179000,
  179000,
  173000,
  150000,
  143000,
  165000,
  null,
].map((saved_weight, index) => ({
  tag: ["#QVVJG0VR", "#PQQ", "#PRR", "#PGG", "#PYY", "#PJJ", "#PVV"][index],
  name: index ? `Recruit account ${index + 1}` : "SHOGUN",
  saved_weight,
  link_disputed: index === 1,
}));
export const slotClans241 = [
  { tag: "#PQQ", name: "Warriors United FWA", is_fwa: true },
  { tag: "#PRR", name: "Four and Twenty", is_fwa: true },
];
export function slotCandidates241(now = Date.now()): SlotCandidate[] {
  return Array.from({ length: 16 }, (_, index) => ({
    player_tag: `#P${"Y".repeat(Math.floor(index / 8) + 1)}${["P", "Q", "G", "R", "J", "C", "U", "V"][index % 8]}Y`,
    player_name: `Slot fixture ${index + 1}`,
    clan_tag: slotClans241[index % 2].tag,
    clan_name: slotClans241[index % 2].name,
    current_clan_tag: index === 13 ? null : slotClans241[index % 2].tag,
    current_clan_name: index === 13 ? null : slotClans241[index % 2].name,
    weight: index === 15 ? null : 179000 - index * 1000,
    town_hall: 18 - (index % 2),
    active_strikes: 3,
    total_strikes: 3,
    marked_for_replacement: true,
    priority: index === 0 ? "replace_first" : "normal",
    departed: index === 13,
    left_label: index === 13 ? "Left clan · 47 h ago" : null,
    stale: index === 14,
    clan_seen_at: new Date(
      now - (index === 14 ? 48 : 1) * 3600000,
    ).toISOString(),
    last_seen_at: new Date(
      now - (index === 14 ? 48 : 1) * 3600000,
    ).toISOString(),
  }));
}

/** Read-only preview response mirrors the approved contract; every filter is applied. */
export function slotFixtureReply241(query: URLSearchParams): SlotResponse & {
  candidates: SlotCandidate[];
  clans: typeof slotClans241;
  total: number;
} {
  const member = query.get("member"),
    typed = query.getAll("weight").map(Number);
  const memberAccounts = member === recruitId241 ? recruitAccounts241 : [];
  const groups = typed.length
    ? typed.map((weight) => ({
        weight,
        account: memberAccounts.find((row) => row.saved_weight === weight),
      }))
    : memberAccounts
        .filter((row) => row.saved_weight !== null)
        .slice(0, 5)
        .map((account) => ({ weight: account.saved_weight!, account }));
  const clans = query.getAll("clan"),
    hall = Number(query.get("town_hall") || 0);
  const pool = slotCandidates241().filter(
    (row) =>
      (!clans.length || clans.includes(row.clan_tag!)) &&
      (!hall || row.town_hall === hall),
  );
  const known = pool.filter((row) => row.weight != null),
    perWeight = Math.max(
      1,
      Math.min(100, Number(query.get("per_weight") || 3)),
    );
  const slots = groups.map(({ weight, account }) => ({
    weight,
    weight_label: `${weight / 1000}k`,
    label: account
      ? `${account.name} · ${weight / 1000}k`
      : `${weight / 1000}k`,
    source: typed.length ? ("typed" as const) : ("saved" as const),
    account_tag: typed.length ? null : account?.tag,
    link_disputed: account?.link_disputed,
    total: known.length,
    candidates: [...known]
      .sort(
        (a, b) =>
          Number(!!a.stale) - Number(!!b.stale) ||
          Math.abs(a.weight! - weight) - Math.abs(b.weight! - weight),
      )
      .slice(0, perWeight)
      .map((row) => ({
        ...row,
        weight_difference: Math.abs(row.weight! - weight),
      })),
  }));
  return {
    slots,
    member_accounts: memberAccounts,
    member_partial: false,
    weights_stale: false,
    member_notice:
      member && !memberAccounts.length
        ? "No linked accounts"
        : !typed.length && groups.length === 5
          ? "Showing 5 of 6 accounts"
          : null,
    unknown_weight: pool.length - known.length,
    candidates: slots[0]?.candidates || [],
    total: slots[0]?.total || 0,
    clans: slotClans241,
  };
}
