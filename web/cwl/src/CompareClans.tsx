import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, RotateCw, X } from "lucide-react";
import RosterMenu from "./rosterUi/Menu";
import { Button } from "./rosterUi/primitives";
import { type Pool } from "./api";
import { useComparisonLocations } from "./useComparisonLocations";
import {
  FilterPicker,
  leagueValue,
  matchesLeague,
  matchesTownHall,
} from "./ClanFilters";
import { sortClans, clanSortOptions, type ClanSort } from "./clanSort";
import {
  compareClanAccounts,
  comparisonOrder,
  moveComparisonClan,
} from "./compare";
import ComparePlayerCard from "./ComparePlayerCard";
import CompareClanHeader from "./CompareClanHeader";
import {
  assignmentOptions,
  type RosterSnapshot,
  type RosterSort,
} from "./roster";
import "./CompareClans.css";

type Props = {
  pool: Pool;
  seasonId: string;
  roster: RosterSnapshot;
  busy: boolean;
  refreshKey?: number;
  onEdit: (tag: string) => void;
};

const playerSortOptions: { value: RosterSort; label: string }[] = [
  { value: "town_hall_desc", label: "Town Hall: high to low" },
  { value: "town_hall_asc", label: "Town Hall: low to high" },
  { value: "weight_desc", label: "Weight: high to low" },
  { value: "weight_asc", label: "Weight: low to high" },
  { value: "name", label: "Name A–Z" },
];

export default function CompareClans({
  pool,
  seasonId,
  roster,
  busy,
  onEdit,
  refreshKey = 0,
}: Props) {
  const [clanSort, setClanSort] = useState<ClanSort>("name");
  const [leagues, setLeagues] = useState<string[]>([]);
  const [townHalls, setTownHalls] = useState<string[]>([]);
  const [clans, setClans] = useState<string[]>([]);
  const [choosing, setChoosing] = useState(false);
  const [clanSearch, setClanSearch] = useState("");
  const [sort, setSort] = useState<RosterSort>("town_hall_desc");
  const [focusedClan, setFocusedClan] = useState("");
  const loadedPreference = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const chooseButton = useRef<HTMLButtonElement>(null);
  const clanSearchInput = useRef<HTMLInputElement>(null);

  const allClans = sortClans(
    assignmentOptions(roster.clans).filter((clan) => clan.pool === pool),
    clanSort,
  );
  const available = allClans.filter((clan) =>
    matchesLeague(clan.cwl_league, leagues),
  );
  const activeTags = allClans
    .map((clan) => clan.tag)
    .sort()
    .join("|");
  const visibleClans = clans.filter((tag) =>
    available.some((clan) => clan.tag === tag),
  );
  const {
    records: locations,
    checking,
    error: locationError,
    now,
    published,
    refresh,
  } = useComparisonLocations(
    seasonId,
    pool,
    clans.length > 0,
    roster.revision,
    refreshKey,
  );
  const matchingClans = available.filter((clan) =>
    `${clan.name} ${clan.tag}`
      .toLowerCase()
      .includes(clanSearch.trim().toLowerCase()),
  );
  const selectedFocus = visibleClans.includes(focusedClan)
    ? focusedClan
    : visibleClans[0];

  useEffect(() => {
    // Main and Lazy have separate saved choices, even within the same season.
    const preferenceKey = `${seasonId}:${pool}`;
    const changedPreference = loadedPreference.current !== preferenceKey;
    let saved: unknown = null;
    if (changedPreference) {
      try {
        saved = JSON.parse(
          localStorage.getItem(`wu-compare-clans:${preferenceKey}`) || "null",
        );
      } catch {
        // Saved comparison order is optional.
      }
      loadedPreference.current = preferenceKey;
    }
    setClans((current) =>
      comparisonOrder(
        changedPreference ? saved : current,
        allClans.map((clan) => clan.tag),
      ),
    );
  }, [seasonId, pool, activeTags]);

  useEffect(() => {
    if (choosing) clanSearchInput.current?.focus({ preventScroll: true });
  }, [choosing]);

  function closeChooser() {
    setChoosing(false);
    requestAnimationFrame(() =>
      chooseButton.current?.focus({ preventScroll: true }),
    );
  }

  function updateClans(next: string[]) {
    setClans(next);
    try {
      localStorage.setItem(
        `wu-compare-clans:${seasonId}:${pool}`,
        JSON.stringify(next),
      );
    } catch {
      // Comparison choices still work for this session.
    }
  }

  function moveTo(index: number) {
    const container = scroller.current;
    const column = container?.children[index] as HTMLElement | undefined;
    if (!container || !column) return;
    container.scrollTo({
      left:
        container.scrollLeft +
        column.getBoundingClientRect().left -
        container.getBoundingClientRect().left,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }

  function focusAt(index: number) {
    const tag = visibleClans[index];
    if (!tag) return;
    setFocusedClan(tag);
    moveTo(index);
  }

  return (
    <section className="compare-workspace card" aria-labelledby="compare-title">
      <header className="compare-header">
        <div>
          <h2 id="compare-title">Compare clans</h2>
          <p>
            {pool === "main" ? "Main" : "Lazy"} CWL · {visibleClans.length}{" "}
            shown
          </p>
        </div>
        <button
          ref={chooseButton}
          className="primary"
          aria-expanded={choosing}
          aria-controls={choosing ? "comparison-clan-picker" : undefined}
          disabled={busy || !allClans.length}
          onClick={() => setChoosing((value) => !value)}
        >
          Choose clans ({clans.length}/10)
        </button>
      </header>

      {roster.clans.some((clan) => !clan.archived && !clan.pool) && (
        <p className="inline-reason">
          Some hosting clans need a Main or Lazy CWL group in Clan settings
          before they can be compared.
        </p>
      )}

      <div
        className="compare-toolbar"
        role="group"
        aria-label="Comparison filters and status"
      >
        <FilterPicker
          label="CWL leagues"
          options={[
            ...new Set(
              sortClans(allClans, "league_desc").map((clan) =>
                leagueValue(clan.cwl_league),
              ),
            ),
          ]}
          selected={leagues}
          onChange={setLeagues}
          disabled={busy}
        />
        <FilterPicker
          label="Town Halls"
          options={[
            ...new Set([
              ...roster.accounts
                .filter((account) =>
                  allClans.some(
                    (clan) => clan.tag === account.assigned_clan_tag,
                  ),
                )
                .map((account) =>
                  account.town_hall == null
                    ? "Unknown TH"
                    : `TH ${account.town_hall}`,
                ),
              ...townHalls,
            ]),
          ].sort(
            (a, b) =>
              (Number(b.replace("TH ", "")) || -1) -
              (Number(a.replace("TH ", "")) || -1),
          )}
          selected={townHalls}
          onChange={setTownHalls}
          disabled={busy}
        />
        <RosterMenu
          label="Sort players"
          value={sort}
          disabled={busy}
          onValueChange={(value) => setSort(value as RosterSort)}
          options={playerSortOptions}
        />
        <Button
          icon={X}
          disabled={busy || (!leagues.length && !townHalls.length)}
          onClick={() => {
            setLeagues([]);
            setTownHalls([]);
          }}
        >
          Clear filters
        </Button>
        <Button icon={RotateCw} disabled={busy || checking} onClick={refresh}>
          {checking ? "Updating locations…" : "Refresh locations"}
        </Button>
      </div>
      <div className="compare-toolbar-note">
        <span>
          {available.length} clans match filters · Location: green in clan, red
          elsewhere, gray unchecked.
        </span>
        <details>
          <summary>How totals work</summary>
          <p>
            Town Hall filters hide players from view; clan totals still include
            every assigned account.
          </p>
        </details>
      </div>
      {locationError && (
        <p className="compare-toolbar-note" role="status">
          {locationError}
        </p>
      )}

      {choosing && (
        <div
          id="comparison-clan-picker"
          className="compare-picker"
          onKeyDown={(event) => {
            // A nested menu is portaled outside this chooser's DOM subtree.
            if (!event.currentTarget.contains(event.target as Node)) return;
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            closeChooser();
          }}
        >
          <label>
            Find a clan
            <input
              ref={clanSearchInput}
              type="search"
              placeholder="Clan name or tag"
              value={clanSearch}
              onChange={(event) => setClanSearch(event.target.value)}
            />
          </label>
          <div className="compare-picker-list">
            {matchingClans.map((clan) => (
              <label key={clan.tag}>
                <input
                  type="checkbox"
                  checked={clans.includes(clan.tag)}
                  disabled={
                    busy || (!clans.includes(clan.tag) && clans.length >= 10)
                  }
                  onChange={() =>
                    updateClans(
                      clans.includes(clan.tag)
                        ? clans.filter((tag) => tag !== clan.tag)
                        : [...clans, clan.tag],
                    )
                  }
                />
                <span>
                  <strong>{clan.name}</strong>
                  <small>
                    {clan.cwl_league || "League unavailable"} · {clan.tag}
                  </small>
                </span>
              </label>
            ))}
          </div>
          {!matchingClans.length && (
            <p>No clans match. Change the search or league filter.</p>
          )}
          <div className="compare-picker-actions">
            <Button
              icon={X}
              disabled={busy || !clans.length}
              onClick={() => updateClans([])}
            >
              Clear choices
            </Button>
            <Button variant="primary" onClick={closeChooser}>
              Done
            </Button>
          </div>
        </div>
      )}

      {!!clans.length && (
        <details className="compare-arrange">
          <summary>Order and change chosen clans</summary>
          <RosterMenu
            label="Sort chosen clans"
            value=""
            disabled={busy}
            options={[
              { value: "", label: "Choose order…", disabled: true },
              ...clanSortOptions.map((option) => ({
                value: option.value,
                label: option.label,
              })),
            ]}
            onValueChange={(value) => {
              const nextSort = value as ClanSort;
              setClanSort(nextSort);
              updateClans(
                sortClans(
                  allClans.filter((clan) => clans.includes(clan.tag)),
                  nextSort,
                ).map((clan) => clan.tag),
              );
            }}
          />
          <ol>
            {clans.map((tag, index) => {
              const clan = allClans.find((item) => item.tag === tag);
              if (!clan) return null;
              return (
                <li key={tag}>
                  <span>{clan.name}</span>
                  <div>
                    <Button
                      variant="icon"
                      icon={ArrowLeft}
                      label={`Move ${clan.name} left`}
                      disabled={busy || index === 0}
                      onClick={() =>
                        updateClans(
                          moveComparisonClan(clans, tag, clans[index - 1]),
                        )
                      }
                    />
                    <Button
                      variant="icon"
                      icon={ArrowRight}
                      label={`Move ${clan.name} right`}
                      disabled={busy || index === clans.length - 1}
                      onClick={() =>
                        updateClans(
                          moveComparisonClan(clans, tag, clans[index + 1]),
                        )
                      }
                    />
                    <Button
                      icon={X}
                      label={`Remove ${clan.name} from comparison`}
                      disabled={busy}
                      onClick={() =>
                        updateClans(clans.filter((value) => value !== tag))
                      }
                    >
                      Remove
                    </Button>
                  </div>
                </li>
              );
            })}
          </ol>
        </details>
      )}

      {visibleClans.length < clans.length && (
        <p className="inline-reason">
          {clans.length - visibleClans.length} chosen clans are hidden by the
          league filter. Clear filters to show them.
        </p>
      )}
      {!allClans.length && (
        <p className="inline-reason">
          No active {pool === "main" ? "Main" : "Lazy"} hosting clans. Assign a
          CWL group in Clan settings.
        </p>
      )}
      {!!allClans.length && !available.length && (
        <p className="inline-reason">
          No hosting clans match. Clear filters to see your choices.
        </p>
      )}
      {!!available.length && !visibleClans.length && (
        <p className="inline-reason">Choose clans above to start comparing.</p>
      )}

      {!!visibleClans.length && (
        <>
          <div className="compare-navigation">
            <div className="compare-desktop-jump">
              <RosterMenu
                label="Jump to clan"
                value=""
                disabled={busy}
                options={[
                  { value: "", label: "Choose a clan…", disabled: true },
                  ...visibleClans.map((tag, index) => ({
                    value: String(index),
                    label:
                      available.find((clan) => clan.tag === tag)?.name || tag,
                  })),
                ]}
                onValueChange={(value) => moveTo(Number(value))}
              />
            </div>
            <div className="compare-mobile-focus">
              <Button
                variant="icon"
                icon={ArrowLeft}
                label="Previous clan"
                disabled={busy || visibleClans.indexOf(selectedFocus) === 0}
                onClick={() => focusAt(visibleClans.indexOf(selectedFocus) - 1)}
              />
              <RosterMenu
                label={`Clan ${visibleClans.indexOf(selectedFocus) + 1} of ${visibleClans.length}`}
                value={selectedFocus}
                disabled={busy}
                options={visibleClans.map((tag) => ({
                  value: tag,
                  label:
                    available.find((clan) => clan.tag === tag)?.name || tag,
                }))}
                onValueChange={setFocusedClan}
              />
              <Button
                variant="icon"
                icon={ArrowRight}
                label="Next clan"
                disabled={
                  busy ||
                  visibleClans.indexOf(selectedFocus) ===
                    visibleClans.length - 1
                }
                onClick={() => focusAt(visibleClans.indexOf(selectedFocus) + 1)}
              />
            </div>
            <small className="compare-desktop-hint">
              Scroll sideways within the comparison to view more clans.
            </small>
          </div>
          <div
            className="compare-pan"
            ref={scroller}
            tabIndex={0}
            role="region"
            aria-label="Clan comparison"
            style={{
              gridTemplateColumns: `repeat(${visibleClans.length}, minmax(280px, 1fr))`,
            }}
          >
            {visibleClans.map((clanTag) => {
              const clan = available.find((item) => item.tag === clanTag);
              if (!clan) return null;
              const members = compareClanAccounts(
                roster.accounts,
                clanTag,
                sort,
              ).filter((account) =>
                matchesTownHall(account.town_hall, townHalls),
              );
              return (
                <section
                  className={`compare-side ${clanTag === selectedFocus ? "mobile-current" : ""}`}
                  key={clanTag}
                  aria-label={`${clan.name} comparison`}
                >
                  <CompareClanHeader
                    clan={clan}
                    accounts={roster.accounts}
                    locations={locations}
                  />
                  <details className="compare-column-change">
                    <summary>Change clan in this column</summary>
                    <RosterMenu
                      label={`Change ${clan.name} column to clan`}
                      value={clanTag}
                      disabled={busy}
                      options={available.map((item) => ({
                        value: item.tag,
                        label: `${item.name} · ${item.cwl_league || "League unavailable"} · ${item.tag}`,
                      }))}
                      onValueChange={(destination) => {
                        updateClans(
                          clans.map((tag) =>
                            tag === clanTag
                              ? destination
                              : tag === destination
                                ? clanTag
                                : tag,
                          ),
                        );
                        setFocusedClan(destination);
                      }}
                    />
                  </details>
                  <div className="compare-player-list">
                    {members.length ? (
                      members.map((account) => (
                        <ComparePlayerCard
                          key={account.tag}
                          account={account}
                          clan={clan}
                          record={locations[account.tag]}
                          now={now}
                          published={published}
                          busy={busy}
                          onDetails={() => onEdit(account.tag)}
                        />
                      ))
                    ) : (
                      <p>No accounts match in this clan.</p>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
