const totalWeightFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
});
export function totalRosterWeight(weight: number | null): string {
  return weight === null
    ? "Total —"
    : `Total ${totalWeightFormat.format(weight / 1000)}k`;
}
