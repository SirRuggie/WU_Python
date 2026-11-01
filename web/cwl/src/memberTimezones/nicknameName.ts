import { ownerTimeZone } from "../compareTimeZone";
/** Reuse recognition only; profile import applies its separate standard-time mapping. */
export function nicknameName(nickname: string | null, fallback: string) {
  const value = (nickname || fallback).trim();
  const parsed = ownerTimeZone(value);
  const marker = value.lastIndexOf("|");
  return marker >= 0 && parsed?.offsetMinutes != null
    ? { name: value.slice(0, marker).trim(), needsReview: false }
    : { name: value, needsReview: true };
}
