import { useMemo } from "react";
import SearchPicker, { type PickerOption } from "./SearchPicker";
import { foldSearch, memberName } from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";

export type StrikeMemberOption = {
  id: string;
  name: string;
  username?: string;
  accounts: number;
};
/** Members that hold family accounts, listed by name or else Discord username. */
export function strikeMemberOptions(
  accounts: ActivityAccount[],
): StrikeMemberOption[] {
  const found = new Map<string, StrikeMemberOption>();
  for (const row of accounts) {
    const username = row.discord_username?.trim() || undefined;
    const name = memberName(row) || username;
    if (!row.discord_id || !name) continue;
    const old = found.get(row.discord_id);
    if (old) old.accounts++;
    else
      found.set(row.discord_id, {
        id: row.discord_id,
        name,
        username,
        accounts: 1,
      });
  }
  return [...found.values()].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
  );
}
/** Row: the name, then the username (when it differs) and account count. */
function memberOption(option: StrikeMemberOption): PickerOption {
  const username =
    option.username && foldSearch(option.username) !== foldSearch(option.name)
      ? option.username
      : "";
  const accounts = `${option.accounts} ${option.accounts === 1 ? "account" : "accounts"}`;
  return {
    value: option.id,
    label: option.name,
    detail: [username, accounts].filter(Boolean).join(" · "),
  };
}
const MEMBER_LIMIT = 30;
const DISCORD_ID = /^\d{17,20}$/;
/** Exact ID first, then names that start with the query, then other matches. */
function findMembers(options: StrikeMemberOption[], query: string) {
  const text = query.trim();
  const folded = foldSearch(text);
  if (!folded) return [];
  const exact = DISCORD_ID.test(text);
  const rank = (option: StrikeMemberOption) => {
    if (exact && option.id === text) return 0;
    const name = foldSearch(option.name);
    if (name.startsWith(folded)) return 1;
    if (
      name.includes(folded) ||
      foldSearch(option.username ?? "").includes(folded)
    )
      return 2;
    return 3;
  };
  return options
    .map((option) => ({ option, rank: rank(option) }))
    .filter((item) => item.rank < 3)
    .sort((a, b) => a.rank - b.rank)
    .map((item) => item.option);
}
/** Searchable Discord member choice from the loaded accounts; no request is made. */
export default function StrikeMemberSelect({
  options,
  value,
  onChange,
  disabled = false,
}: {
  options: StrikeMemberOption[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const pickerOptions = useMemo(() => options.map(memberOption), [options]);
  const byId = useMemo(
    () => new Map(pickerOptions.map((option) => [option.value, option])),
    [pickerOptions],
  );
  return (
    <div className="strike-member-select">
      <SearchPicker
        label="Discord member"
        value={value}
        options={pickerOptions}
        onChange={onChange}
        placeholder="Select a member"
        searchPlaceholder="Name or username"
        emptyText="No Discord member found."
        disabled={disabled}
        clearable
        fallback={{ value, label: "Selected member unavailable" }}
        search={(query) =>
          query.trim()
            ? findMembers(options, query).flatMap(
                (option) => byId.get(option.id) ?? [],
              )
            : pickerOptions
        }
        limit={MEMBER_LIMIT}
      />
    </div>
  );
}
