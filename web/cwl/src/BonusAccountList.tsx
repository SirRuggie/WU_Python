import { useMemo, useState } from "react";
import BonusAccountCard from "./BonusAccountCard";
import type { BonusListMode, RaffleAccount } from "./bonusRaffle";

/** A list of bonus players in the shared card; optionally searchable. */
export default function BonusAccountList({
  accounts,
  onReview,
  busy,
  searchable = false,
  mode = "candidates",
  minimum = null,
}: {
  accounts: RaffleAccount[];
  onReview?: (account: RaffleAccount, opener: HTMLElement) => void;
  busy?: boolean;
  searchable?: boolean;
  mode?: BonusListMode;
  minimum?: number | null;
}) {
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(20);
  const matching = useMemo(
    () =>
      accounts.filter((account) =>
        `${account.player_name} ${account.tag}`
          .toLowerCase()
          .includes(query.trim().toLowerCase()),
      ),
    [accounts, query],
  );

  return (
    <div className="bonus-account-results">
      {searchable && (
        <label className="bonus-account-search">
          Find an account
          <input
            type="search"
            name="account-search"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setVisibleCount(20);
            }}
            placeholder="Name or #TAG…"
          />
        </label>
      )}
      <ul className="bonus-account-list">
        {matching
          .slice(0, searchable ? visibleCount : matching.length)
          .map((account) => (
            <li key={account.tag}>
              <BonusAccountCard
                account={account}
                mode={mode}
                minimum={minimum}
                onReview={onReview}
                busy={busy}
              />
            </li>
          ))}
      </ul>
      {searchable && matching.length > visibleCount && (
        <button
          type="button"
          className="bonus-show-more"
          onClick={() => setVisibleCount((count) => count + 20)}
        >
          Show 20 more · {matching.length - visibleCount} remaining
        </button>
      )}
      {!matching.length && (
        <p className="bonus-empty">
          {query
            ? "No accounts match this search."
            : "No accounts in this group."}
        </p>
      )}
    </div>
  );
}
