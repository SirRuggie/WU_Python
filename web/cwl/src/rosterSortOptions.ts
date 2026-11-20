export const rosterSortOptions = [
  ["unassigned_first", "Unplaced first"],
  ["weight_desc", "Weight: highest first"],
  ["weight_asc", "Weight: lowest first"],
  ["name", "Name A–Z"],
  ["town_hall_desc", "TH: highest first"],
  ["town_hall_asc", "TH: lowest first"],
  ["assigned_clan", "Assigned clan"],
  ["signed_up_desc", "Signup: newest first"],
  ["signed_up_asc", "Signup: oldest first"],
] as const;

export type RosterSortValue = (typeof rosterSortOptions)[number][0];
export const rosterSortShortLabels: Record<RosterSortValue, string> = {
  unassigned_first: "Unplaced first",
  weight_desc: "Weight ↓",
  weight_asc: "Weight ↑",
  name: "Name A–Z",
  town_hall_desc: "TH ↓",
  town_hall_asc: "TH ↑",
  assigned_clan: "Clan",
  signed_up_desc: "Newest",
  signed_up_asc: "Oldest",
};
