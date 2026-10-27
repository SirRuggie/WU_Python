/** Roster summaries use thousands without switching to millions. */
export function compactRosterWeight(weight: number | null): string {
  if (weight === null || !Number.isFinite(weight)) return "—";
  return `${new Intl.NumberFormat("en-US", {
    useGrouping: false,
    maximumFractionDigits: 1,
  }).format(weight / 1000)}k`;
}
