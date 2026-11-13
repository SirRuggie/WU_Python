import { NUMBER_LOCALE } from "./format";

const compactWeightFormat = new Intl.NumberFormat(NUMBER_LOCALE, {
  useGrouping: false,
  maximumFractionDigits: 1,
});

/** Roster summaries use thousands without switching to millions. */
export function compactRosterWeight(weight: number | null): string {
  if (weight === null || !Number.isFinite(weight)) return "—";
  return `${compactWeightFormat.format(weight / 1000)}k`;
}
