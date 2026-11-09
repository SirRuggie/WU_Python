export function compactWeight(value: number): string {
  return `${Number((value / 1000).toFixed(3))}k`;
}
export function enteredWeight(value: string): number {
  const amount = Number(value);
  return amount < 1000 ? amount * 1000 : amount;
}
export const maxSlotWeights = 5;
/** "143, 173k 150000" -> raw weights. The error names the first value that cannot be read. */
export function parseWeights(text: string): {
  weights: number[];
  error: string;
} {
  const tokens = text.split(/[\s,;]+/).filter(Boolean);
  if (!tokens.length) return { weights: [], error: "Enter a weight." };
  if (tokens.length > maxSlotWeights)
    return { weights: [], error: `Enter up to ${maxSlotWeights} weights.` };
  const weights: number[] = [];
  for (const token of tokens) {
    const match = /^(\d+(?:\.\d+)?)(k?)$/i.exec(token);
    const amount = match
      ? match[2]
        ? Number(match[1]) * 1000
        : enteredWeight(match[1])
      : NaN;
    if (!Number.isFinite(amount) || amount <= 0 || amount > 10_000_000)
      return {
        weights: [],
        error: `“${token.slice(0, 20)}” is not a weight. Use 143, 143k or 143000.`,
      };
    weights.push(Math.round(amount));
  }
  return { weights, error: "" };
}
/** Weights as typed back into the field: 143000 -> 143. */
export function weightsText(weights: number[]): string {
  return weights
    .map((value) => String(Number((value / 1000).toFixed(3))))
    .join(", ");
}
