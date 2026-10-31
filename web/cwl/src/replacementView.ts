export function compactWeight(value: number): string {
  return `${Number((value / 1000).toFixed(3))}k`;
}
export function enteredWeight(value: string): number {
  const amount = Number(value);
  return amount < 1000 ? amount * 1000 : amount;
}
