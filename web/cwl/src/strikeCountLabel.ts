import { countLabel } from "./countLabel";
/** Keep singular and plural count labels consistent across strike views. */
export function strikeCountLabel(count: number, noun: string): string {
  return countLabel(count, noun);
}
