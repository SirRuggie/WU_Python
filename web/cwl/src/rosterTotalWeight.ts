const totalWeightFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
});
export function formattedRosterWeight(weight: number): string {
  return `${totalWeightFormat.format(weight / 1000)}k`;
}
export function totalRosterWeight(weight: number | null): string {
  return weight === null ? "Total —" : `Total ${formattedRosterWeight(weight)}`;
}
