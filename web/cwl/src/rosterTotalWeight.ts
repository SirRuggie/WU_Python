import { NUMBER_LOCALE } from "./format";

const totalWeightFormat = new Intl.NumberFormat(NUMBER_LOCALE, {
  maximumFractionDigits: 1,
});
export function formattedRosterWeight(weight: number): string {
  return `${totalWeightFormat.format(weight / 1000)}k`;
}
export function totalRosterWeight(weight: number | null): string {
  return weight === null ? "Total —" : `Total ${formattedRosterWeight(weight)}`;
}
