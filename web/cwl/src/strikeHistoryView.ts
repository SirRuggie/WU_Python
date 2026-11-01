import { strikeCountLabel } from "./strikeCountLabel";
export function strikeBadge(
  kind: "strike" | "miss" | "completed" | "cwl",
  status: string,
  attacksUsed?: number | null,
): string {
  if (kind === "cwl")
    return attacksUsed === 0
      ? "Attack missed"
      : attacksUsed === 1
        ? "Attack used"
        : "CWL record";
  if (status === "exempt") return "Exempt";
  if (kind === "completed") return "Attacks done";
  if (kind === "miss")
    return status === "completed" ? "Attacks done" : "One missed";
  if (status === "active") return "Active strike";
  return `${status[0]?.toUpperCase() || ""}${status.slice(1)} strike`;
}

export function warMatchup(
  clanName?: string | null,
  opponentName?: string | null,
): string {
  const clan = clanName || "Unknown clan";
  return opponentName ? `${clan} vs ${opponentName}` : clan;
}

export function detailQuery(
  page: number,
  status: string,
  playerTag?: string,
  warKey?: string,
): URLSearchParams {
  const params = new URLSearchParams({
    limit: "25",
    offset: String(page * 25),
    status,
  });
  if (playerTag) params.set("query", playerTag);
  if (warKey) params.set("war_key", warKey);
  return params;
}

export function importEmptyText(
  entries: unknown[],
  deferredCount: number,
  skippedWars = 0,
): string {
  return entries.length === 0 && (deferredCount > 0 || skippedWars > 0)
    ? "No records ready to import."
    : "No missed attacks found in saved wars.";
}

export function isCwlRecord(item: {
  kind?: string | null;
  war_type?: string | null;
  source?: string | null;
}): boolean {
  return (
    item.kind === "cwl" || item.war_type === "cwl" || item.source === "cwl"
  );
}

export function warSummary(war: {
  no_attack?: number | boolean;
  mismatch?: number | boolean;
  war_type?: string | null;
  strikes: number;
  one_missed: number;
  cwl_missed?: number;
}): string {
  if (war.mismatch) return "⊖ Mismatch war (no strike)";
  if (war.no_attack) return "⊖ No-attack war (no strike)";
  return war.war_type === "cwl"
    ? `CWL · ${war.cwl_missed ?? 0} missed · No strikes`
    : `${strikeCountLabel(war.strikes, "strike")} · ${war.one_missed} one missed`;
}
