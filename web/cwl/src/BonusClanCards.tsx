import { useState } from "react";
import type { Pool } from "./api";
import useChoiceRail from "./useChoiceRail";
import { bonusClanCardText, type BonusStatus } from "./bonusStatus";
import "./BonusClanCards.css";

type Props = {
  clans: { tag: string; name: string }[];
  /** The open clan; empty means the season overview. */
  selected: string;
  pool: Pool;
  status: BonusStatus | null;
  statusFailed: boolean;
  disabled: boolean;
  onSelect: (tag: string) => void;
  /** Back to the overview with every clan. */
  onAll: () => void;
};

const CLAN_SEARCH_MIN = 8;

/** Hosting clan cards with their bonus state; the first card is All clans. */
export default function BonusClanCards({
  clans,
  selected,
  pool,
  status,
  statusFailed,
  disabled,
  onSelect,
  onAll,
}: Props) {
  const [query, setQuery] = useState("");
  const rail = useChoiceRail<HTMLDivElement>(selected);
  return (
    <>
      {clans.length >= CLAN_SEARCH_MIN && (
        <label className="bonus-clan-search">
          Find a clan
          <input
            type="search"
            name="clan-search"
            autoComplete="off"
            spellCheck={false}
            placeholder="Clan name…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      )}
      <div
        {...rail.fadeProps}
        ref={rail.ref}
        className="bonus-clan-cards has-horizontal-fades"
        role="group"
        aria-label="Hosting clan"
      >
        <button
          type="button"
          className="bonus-clan-card bonus-clan-all"
          aria-pressed={!selected}
          disabled={disabled}
          onClick={onAll}
        >
          <strong>All clans</strong>
          <small>
            {clans.length} {clans.length === 1 ? "clan" : "clans"}
          </small>
        </button>
        {clans
          .filter(
            (clan) =>
              clan.tag === selected ||
              clan.name.toLowerCase().includes(query.trim().toLowerCase()),
          )
          .map((clan) => {
            const state = status?.pools[pool].find(
              (item) => item.tag === clan.tag,
            );
            return (
              <button
                type="button"
                key={clan.tag}
                className="bonus-clan-card"
                aria-pressed={clan.tag === selected}
                disabled={disabled}
                onClick={() => onSelect(clan.tag)}
              >
                <strong>{clan.name}</strong>
                <small>
                  {state
                    ? bonusClanCardText(state)
                    : statusFailed
                      ? clan.tag
                      : "…"}
                </small>
              </button>
            );
          })}
      </div>
    </>
  );
}
