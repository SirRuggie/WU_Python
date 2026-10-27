export type ComparisonLocation = {
  current_clan_tag: string | null;
  current_clan_name: string | null;
  current_clan_checked_at?: string;
  current_clan_status?: string;
  outside_family?: boolean;
  location_updating?: boolean;
  arrival_status?: string;
};
export type LocationRecords = Record<string, ComparisonLocation>;

/** Background status is not a replacement for the last known location. */
export function mergeComparisonLocations(
  previous: LocationRecords,
  incoming: (ComparisonLocation & { tag: string })[],
): LocationRecords {
  const next = { ...previous };
  for (const account of incoming) {
    const checked = Date.parse(account.current_clan_checked_at || "");
    const old = previous[account.tag];
    if (!Number.isFinite(checked)) continue;
    if (old && checked <= Date.parse(old.current_clan_checked_at || ""))
      continue;
    next[account.tag] = {
      current_clan_tag: account.current_clan_tag,
      current_clan_name: account.current_clan_name,
      current_clan_checked_at: account.current_clan_checked_at,
      outside_family:
        !!account.current_clan_tag &&
        (account.current_clan_status === "current"
          ? !!account.outside_family
          : account.current_clan_tag === old?.current_clan_tag &&
            !!old?.outside_family),
    };
  }
  return next;
}
export function comparisonAge(
  checked: string | number | undefined,
  now: number,
): string {
  const timestamp =
    typeof checked === "number" ? checked : Date.parse(checked || "");
  if (!Number.isFinite(timestamp)) return "Checking…";
  const minutes = Math.max(0, Math.floor((now - timestamp) / 60000));
  if (!minutes) return "just now";
  return minutes < 60
    ? `${minutes}m ago`
    : `${Math.floor(minutes / 60)}h ${minutes % 60}m ago`;
}
export function comparisonLocation(
  location: ComparisonLocation | undefined,
  clanTag: string,
  now: number,
) {
  if (
    !location ||
    !Number.isFinite(Date.parse(location.current_clan_checked_at || ""))
  )
    return { state: "checking", label: "Checking…", detail: "" };
  const arrived = location.current_clan_tag === clanTag;
  const clan = location.current_clan_name || location.current_clan_tag;
  return {
    state: arrived ? "arrived" : "missing",
    label: arrived ? "In this clan" : "Not in this clan",
    detail: `${clan ? `Now in: ${clan}` : "No clan"} · ${comparisonAge(location.current_clan_checked_at, now)}`,
  };
}
export function comparisonTally(
  tags: string[],
  locations: LocationRecords,
  clanTag: string,
) {
  return tags.reduce(
    (count, tag) => {
      const record = locations[tag];
      if (!record) count.checking++;
      else {
        if (record.current_clan_tag === clanTag) count.arrived++;
        else count.elsewhere++;
        if (record.current_clan_tag && record.outside_family) count.outside++;
      }
      return count;
    },
    { arrived: 0, elsewhere: 0, checking: 0, outside: 0 },
  );
}
