import { useMemo, useState } from "react";
import DiscordIdentity from "./DiscordIdentity";
import { memberName } from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";

export type StrikeMemberOption = { id: string; name: string; accounts: number };
/** Members that hold family accounts, named only when a name is known. */
export function strikeMemberOptions(
  accounts: ActivityAccount[],
): StrikeMemberOption[] {
  const found = new Map<string, StrikeMemberOption>();
  for (const row of accounts) {
    const name = memberName(row);
    if (!row.discord_id || !name) continue;
    const old = found.get(row.discord_id);
    if (old) old.accounts++;
    else found.set(row.discord_id, { id: row.discord_id, name, accounts: 1 });
  }
  return [...found.values()].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
  );
}
/** Searchable member choice from the loaded accounts; no request is made. */
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
  const folded = search.trim().normalize("NFKC").toLocaleLowerCase();
  const matches = useMemo(
    () =>
      folded
        ? options
            .filter((option) =>
              option.name.toLocaleLowerCase().includes(folded),
            )
            .slice(0, 8)
        : [],
    [options, folded],
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
        Find member
        <input
          type="search"
          value={search}
          maxLength={80}
          disabled={disabled}
          placeholder="Name"
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {folded && !matches.length && <p role="status">No member found.</p>}
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
                @{option.name}
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
