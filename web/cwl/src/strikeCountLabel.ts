/** Keep singular and plural count labels consistent across strike views. */
export function strikeCountLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}
