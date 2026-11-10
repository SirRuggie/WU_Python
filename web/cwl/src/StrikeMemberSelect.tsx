import { useMemo, useState } from "react";
import DiscordIdentity from "./DiscordIdentity";
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
    .slice(0, 8)
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
  const [search, setSearch] = useState("");
  const matches = useMemo(
    () => findMembers(options, search),
    [options, search],
  );
  const selected = options.find((option) => option.id === value);
  return (
    <div className="strike-member-select">
      {value && (
        <div className="strike-member-selected">
          <DiscordIdentity
            userId={value}
            displayName={selected?.name}
            resolvedMember={null}
            variant="compact"
            contact={false}
            username={false}
          />
          <button
            type="button"
            disabled={disabled}
            aria-label="Remove member"
            onClick={() => onChange("")}
          >
            ×
          </button>
        </div>
      )}
      <label>
        Discord member
        <input
          type="search"
          value={search}
          maxLength={80}
          disabled={disabled}
          placeholder="Name, username or ID…"
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {search.trim() && !matches.length && (
        <p role="status">No Discord member found.</p>
      )}
      {matches.length > 0 && (
        <ul className="strike-member-options" aria-label="Members">
          {matches.map((option) => (
            <li key={option.id}>
              <button
                type="button"
                disabled={disabled}
                aria-pressed={option.id === value}
                onClick={() => {
                  onChange(option.id);
                  setSearch("");
                }}
              >
                <span>
                  @{option.name}
                  {option.username &&
                    foldSearch(option.username) !== foldSearch(option.name) && (
                      <small className="strike-member-username">
                        {option.username}
                      </small>
                    )}
                </span>
                <small>
                  {option.accounts}{" "}
                  {option.accounts === 1 ? "account" : "accounts"}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
