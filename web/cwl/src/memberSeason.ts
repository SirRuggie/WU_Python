import type { Season } from "./api";

/** Shared member signup availability; a published/closed season is never open. */
export function memberSignupsOpen(season: Season | undefined): boolean {
  return !!season?.signup_open && season.status === "draft";
}
