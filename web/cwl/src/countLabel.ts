import { formatNumber } from "./format";

/** Format the count without changing the surrounding action's wording. */
export function countLabel(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${formatNumber(count)} ${countNoun(count, singular, plural)}`;
}

/** Keep noun selection shared when the count has separate responsive markup. */
export function countNoun(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return count === 1 ? singular : plural;
}
