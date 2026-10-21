import ClanCategories, { clanCategory } from "./ClanCategories";
import { useEffect, useRef } from "react";

type Row = { tag: string; name: string; type: string; logo: string };
type Props<T extends Row> = {
  clans: T[];
  types: string[];
  selected: T | null;
  query: string;
  onQuery: (value: string) => void;
  clanType: string;
  onType: (value: string) => void;
  expanded: boolean;
  onExpanded: (value: boolean) => void;
  disabled: boolean;
  loading: boolean;
  error: string;
  onRetry: () => void;
  onSelect: (row: T) => void;
};

export default function ClanDirectory<T extends Row>({
  clans,
  types: _types,
  selected,
  query,
  onQuery,
  clanType,
  onType,
  expanded,
  onExpanded,
  disabled,
  loading,
  error,
  onRetry,
  onSelect,
}: Props<T>) {
  const search = useRef<HTMLInputElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const filtered = clans.filter(
    (clan) =>
      (!clanType || clanCategory(clan.type) === clanType) &&
      `${clan.name} ${clan.tag} ${clan.type}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  useEffect(() => {
    if (expanded) search.current?.focus();
  }, [expanded]);
  return (
    <aside
      className="card"
      aria-label="Family clan directory"
      aria-busy={loading}
    >
      <button
        ref={toggle}
        className="clan-mobile-switch"
        disabled={disabled}
        aria-controls="clan-directory-picker"
        aria-expanded={!selected || expanded}
        onClick={() => onExpanded(!expanded)}
      >
        {selected ? `Change clan · ${selected.name}` : "Choose a clan"}
      </button>
      <div
        id="clan-directory-picker"
        className={selected && !expanded ? "clan-picker-closed" : ""}
        onKeyDown={(event) => {
          if (event.key === "Escape" && selected && expanded) {
            onExpanded(false);
            toggle.current?.focus();
          }
        }}
      >
        <label>
          Find a clan
          <input
            ref={search}
            type="search"
            placeholder="Name, tag or type"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
          />
        </label>
        <ClanCategories clans={clans} value={clanType} onChange={onType} />
        {loading ? (
          <p role="status">Loading clans…</p>
        ) : error ? (
          <p role="alert">
            {error} <button onClick={onRetry}>Retry</button>
          </p>
        ) : (
          <>
            <p className="small" role="status">
              {filtered.length} of {clans.length} clans
            </p>
            <div className="clan-directory">
              {filtered.map((row) => (
                <button
                  disabled={disabled}
                  key={row.tag}
                  aria-pressed={selected?.tag === row.tag}
                  onClick={() => onSelect(row)}
                >
                  {row.logo && (
                    <img src={row.logo} alt="" width={36} height={36} />
                  )}
                  <span>
                    <strong>{row.name}</strong>
                    <small>
                      {row.tag} · {clanCategory(row.type) || "Type not set"}
                    </small>
                  </span>
                </button>
              ))}
            </div>
            {!filtered.length && (
              <p>
                {clans.length
                  ? "No clans match these filters."
                  : "No family clans yet. Add a clan by tag to get started."}
              </p>
            )}
            {(query || clanType) && (
              <button
                onClick={() => {
                  onQuery("");
                  onType("");
                  search.current?.focus();
                }}
              >
                Clear filters
              </button>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
