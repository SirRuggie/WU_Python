import { useEffect, useRef, useState } from 'react';
import { api, type Pool } from './api';
import { FilterPicker, leagueValue, matchesLeague, matchesTownHall } from './ClanFilters';
import { sortClans, clanSortOptions, type ClanSort } from './clanSort';
import { clanSummary, compareClanAccounts, comparisonOrder, moveComparisonClan } from './compare';
import { comparisonLocation, type ComparisonLocation } from './comparisonLocation';
import DiscordContact from './DiscordContact';
import { assignmentOptions, weightText, type RosterSnapshot, type RosterSort } from './roster';
import './CompareClans.css';

type Props = {
  pool: Pool;
  seasonId: string;
  roster: RosterSnapshot;
  busy: boolean;
  onEdit: (tag: string) => void;
};

const playerSortOptions: { value: RosterSort; label: string }[] = [
  { value: 'town_hall_desc', label: 'Town Hall: high to low' },
  { value: 'town_hall_asc', label: 'Town Hall: low to high' },
  { value: 'weight_desc', label: 'Weight: high to low' },
  { value: 'weight_asc', label: 'Weight: low to high' },
  { value: 'name', label: 'Name A–Z' },
];

function averageText(value: number | null) {
  return value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function totalWeightText(value: number | null) {
  return value === null ? '—' : value.toLocaleString('en-US');
}

export default function CompareClans({ pool, seasonId, roster, busy, onEdit }: Props) {
  const [locations, setLocations] = useState<Record<string, ComparisonLocation>>({});
  const [checking, setChecking] = useState(false);
  const [locationError, setLocationError] = useState('');
  const [refreshLocations, setRefreshLocations] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [clanSort, setClanSort] = useState<ClanSort>('name');
  const [leagues, setLeagues] = useState<string[]>([]);
  const [townHalls, setTownHalls] = useState<string[]>([]);
  const [clans, setClans] = useState<string[]>([]);
  const [choosing, setChoosing] = useState(false);
  const [clanSearch, setClanSearch] = useState('');
  const [sort, setSort] = useState<RosterSort>('town_hall_desc');
  const [focusedClan, setFocusedClan] = useState('');
  const loadedPreference = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const chooseButton = useRef<HTMLButtonElement>(null);
  const clanSearchInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setLocations({});
    setChecking(true);
    setLocationError('');
    async function check(force = false) {
      try {
        const suffix = force ? '&refresh=1' : '';
        const result = await api<{ updating: boolean; accounts: (ComparisonLocation & { tag: string })[] }>(
          `/seasons/${encodeURIComponent(seasonId)}/arrival-check?background=1&source=draft${suffix}`,
        );
        if (cancelled) return;
        setLocations(Object.fromEntries(result.accounts.map(account => [account.tag, account])));
        setChecking(result.updating);
        setNow(Date.now());
        if (result.updating) timer = setTimeout(() => void check(), 2000);
      } catch {
        if (!cancelled) {
          setChecking(false);
          setLocationError('Could not update locations. Try again.');
          setLocations({});
        }
      }
    }
    void check(true);
    const clock = setInterval(() => setNow(Date.now()), 30000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearInterval(clock);
    };
  }, [seasonId, refreshLocations]);

  const allClans = sortClans(assignmentOptions(roster.clans).filter(clan => clan.pool === pool), clanSort);
  const available = allClans.filter(clan => matchesLeague(clan.cwl_league, leagues));
  const activeTags = allClans.map(clan => clan.tag).sort().join('|');
  const visibleClans = clans.filter(tag => available.some(clan => clan.tag === tag));
  const matchingClans = available.filter(clan =>
    `${clan.name} ${clan.tag}`.toLowerCase().includes(clanSearch.trim().toLowerCase()),
  );
  const selectedFocus = visibleClans.includes(focusedClan) ? focusedClan : visibleClans[0];

  useEffect(() => {
    // Main and Lazy have separate saved choices, even within the same season.
    const preferenceKey = `${seasonId}:${pool}`;
    const changedPreference = loadedPreference.current !== preferenceKey;
    let saved: unknown = null;
    if (changedPreference) {
      try {
        saved = JSON.parse(localStorage.getItem(`wu-compare-clans:${preferenceKey}`) || 'null');
      } catch {
        // Saved comparison order is optional.
      }
      loadedPreference.current = preferenceKey;
    }
    setClans(current => comparisonOrder(
      changedPreference ? saved : current,
      allClans.map(clan => clan.tag),
    ));
  }, [seasonId, pool, activeTags]);

  useEffect(() => {
    if (choosing) clanSearchInput.current?.focus({ preventScroll: true });
  }, [choosing]);

  function closeChooser() {
    setChoosing(false);
    requestAnimationFrame(() => chooseButton.current?.focus({ preventScroll: true }));
  }

  function updateClans(next: string[]) {
    setClans(next);
    try {
      localStorage.setItem(`wu-compare-clans:${seasonId}:${pool}`, JSON.stringify(next));
    } catch {
      // Comparison choices still work for this session.
    }
  }

  function moveTo(index: number) {
    const container = scroller.current;
    const column = container?.children[index] as HTMLElement | undefined;
    if (!container || !column) return;
    container.scrollTo({
      left: container.scrollLeft + column.getBoundingClientRect().left - container.getBoundingClientRect().left,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
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
          <p>{pool === 'main' ? 'Main' : 'Lazy'} CWL · {visibleClans.length} shown</p>
        </div>
        <button
          ref={chooseButton}
          className="primary"
          aria-expanded={choosing}
          aria-controls={choosing ? "comparison-clan-picker" : undefined}
          disabled={busy || !allClans.length}
          onClick={() => setChoosing(value => !value)}
        >
          Choose clans ({clans.length}/10)
        </button>
      </header>

      {roster.clans.some(clan => !clan.archived && !clan.pool) && (
        <p className="inline-reason">Some hosting clans need a Main or Lazy CWL group in Clan settings before they can be compared.</p>
      )}

      <div className="compare-toolbar" role="group" aria-label="Comparison filters and status">
        <FilterPicker
          label="CWL leagues"
          options={[...new Set(sortClans(allClans, 'league_desc').map(clan => leagueValue(clan.cwl_league)))]}
          selected={leagues}
          onChange={setLeagues}
          disabled={busy}
        />
        <FilterPicker
          label="Town Halls"
          options={[...new Set(roster.accounts.map(account => account.town_hall))]
            .sort((a, b) => (b ?? -1) - (a ?? -1))
            .map(value => value == null ? 'Unknown TH' : `TH ${value}`)}
          selected={townHalls}
          onChange={setTownHalls}
          disabled={busy}
        />
        <label>
          Sort players
          <select value={sort} disabled={busy} onChange={event => setSort(event.target.value as RosterSort)}>
            {playerSortOptions.map(option => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <button disabled={busy || (!leagues.length && !townHalls.length)} onClick={() => { setLeagues([]); setTownHalls([]); }}>
          Clear filters
        </button>
        <button disabled={busy || checking} onClick={() => setRefreshLocations(value => value + 1)}>
          {checking ? 'Updating locations…' : 'Refresh locations'}
        </button>
      </div>
      <div className="compare-toolbar-note">
        <span>{available.length} clans match filters · Location: green in clan, red elsewhere, gray unchecked.</span>
        <details>
          <summary>How totals work</summary>
          <p>Town Hall filters hide players from view; clan totals still include every assigned account.</p>
        </details>
      </div>
      {locationError && <p className="notice error" role="alert">{locationError}</p>}

      {choosing && (
        <div
          id="comparison-clan-picker"
          className="compare-picker"
          onKeyDown={event => {
            if (event.key !== 'Escape') return;
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
              onChange={event => setClanSearch(event.target.value)}
            />
          </label>
          <div className="compare-picker-list">
            {matchingClans.map(clan => (
              <label key={clan.tag}>
                <input
                  type="checkbox"
                  checked={clans.includes(clan.tag)}
                  disabled={busy || (!clans.includes(clan.tag) && clans.length >= 10)}
                  onChange={() => updateClans(
                    clans.includes(clan.tag)
                      ? clans.filter(tag => tag !== clan.tag)
                      : [...clans, clan.tag],
                  )}
                />
                <span><strong>{clan.name}</strong><small>{clan.cwl_league || 'League unavailable'} · {clan.tag}</small></span>
              </label>
            ))}
          </div>
          {!matchingClans.length && <p>No clans match. Change the search or league filter.</p>}
          <div className="compare-picker-actions">
            <button disabled={busy || !clans.length} onClick={() => updateClans([])}>Clear choices</button>
            <button onClick={closeChooser}>Done</button>
          </div>
        </div>
      )}

      {!!clans.length && (
        <details className="compare-arrange">
          <summary>Order and change chosen clans</summary>
          <label>
            Sort chosen clans
            <select
              value=""
              disabled={busy}
              onChange={event => {
                const value = event.target.value as ClanSort;
                setClanSort(value);
                updateClans(sortClans(allClans.filter(clan => clans.includes(clan.tag)), value).map(clan => clan.tag));
              }}
            >
              <option value="" disabled>Choose order…</option>
              {clanSortOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <ol>
            {clans.map((tag, index) => {
              const clan = allClans.find(item => item.tag === tag);
              if (!clan) return null;
              return (
                <li key={tag}>
                  <span>{clan.name}</span>
                  <div>
                    <button aria-label={`Move ${clan.name} left`} disabled={busy || index === 0} onClick={() => updateClans(moveComparisonClan(clans, tag, clans[index - 1]))}>←</button>
                    <button aria-label={`Move ${clan.name} right`} disabled={busy || index === clans.length - 1} onClick={() => updateClans(moveComparisonClan(clans, tag, clans[index + 1]))}>→</button>
                    <button aria-label={`Remove ${clan.name} from comparison`} disabled={busy} onClick={() => updateClans(clans.filter(value => value !== tag))}>Remove</button>
                  </div>
                </li>
              );
            })}
          </ol>
        </details>
      )}

      {visibleClans.length < clans.length && (
        <p className="inline-reason">{clans.length - visibleClans.length} chosen clans are hidden by the league filter. Clear filters to show them.</p>
      )}
      {!allClans.length && <p className="inline-reason">No active {pool === 'main' ? 'Main' : 'Lazy'} hosting clans. Assign a CWL group in Clan settings.</p>}
      {!!allClans.length && !available.length && <p className="inline-reason">No hosting clans match. Clear filters to see your choices.</p>}
      {!!available.length && !visibleClans.length && <p className="inline-reason">Choose clans above to start comparing.</p>}

      {!!visibleClans.length && (
        <>
          <div className="compare-navigation">
            <label className="compare-desktop-jump">
              Jump to clan
              <select value="" disabled={busy} onChange={event => moveTo(Number(event.target.value))}>
                <option value="" disabled>Choose a clan…</option>
                {visibleClans.map((tag, index) => (
                  <option key={tag} value={index}>{available.find(clan => clan.tag === tag)?.name}</option>
                ))}
              </select>
            </label>
            <div className="compare-mobile-focus">
              <button aria-label="Previous clan" disabled={busy || visibleClans.indexOf(selectedFocus) === 0} onClick={() => focusAt(visibleClans.indexOf(selectedFocus) - 1)}>←</button>
              <label>
                Clan {visibleClans.indexOf(selectedFocus) + 1} of {visibleClans.length}
                <select value={selectedFocus} disabled={busy} onChange={event => setFocusedClan(event.target.value)}>
                  {visibleClans.map(tag => (
                    <option key={tag} value={tag}>{available.find(clan => clan.tag === tag)?.name}</option>
                  ))}
                </select>
              </label>
              <button aria-label="Next clan" disabled={busy || visibleClans.indexOf(selectedFocus) === visibleClans.length - 1} onClick={() => focusAt(visibleClans.indexOf(selectedFocus) + 1)}>→</button>
            </div>
            <small className="compare-desktop-hint">Scroll sideways within the comparison to view more clans.</small>
          </div>
          <div
            className="compare-pan"
            ref={scroller}
            tabIndex={0}
            role="region"
            aria-label="Clan comparison"
            style={{ gridTemplateColumns: `repeat(${visibleClans.length}, minmax(280px, 1fr))` }}
          >
            {visibleClans.map(clanTag => {
              const clan = available.find(item => item.tag === clanTag);
              if (!clan) return null;
              const members = compareClanAccounts(roster.accounts, clanTag, sort)
                .filter(account => matchesTownHall(account.town_hall, townHalls));
              const summary = clanSummary(roster.accounts, clanTag);
              const unknownWeights = summary.count - summary.knownWeights;
              return (
                <section
                  className={`compare-side ${clanTag === selectedFocus ? 'mobile-current' : ''}`}
                  key={clanTag}
                  aria-label={`${clan.name} comparison`}
                >
                  <header className="compare-clan-summary">
                    <div>
                      <h3>{clan.name}</h3>
                      <small>{clan.cwl_league || 'League unavailable'}{clan.cwl_league_stale && clan.cwl_league ? ' · last known' : ''} · {clan.tag}</small>
                    </div>
                    <div className="compare-clan-stats">
                      <span>{summary.count}/{clan.effective_capacity} occupied</span>
                      <span title={summary.totalWeight === null ? 'No weights known' : `${summary.totalWeight.toLocaleString()} exact total weight`}>Total weight {totalWeightText(summary.totalWeight)}</span>
                      <span>{unknownWeights ? `${unknownWeights} unknown weight${unknownWeights === 1 ? '' : 's'}` : 'All weights known'}</span>
                      <span>Avg TH {averageText(summary.averageTownHall)} · {summary.knownTownHalls}/{summary.count} known</span>
                    </div>
                  </header>
                  <details className="compare-column-change">
                    <summary>Change clan in this column</summary>
                    <select
                      aria-label={`Change ${clan.name} column to clan`}
                      value={clanTag}
                      disabled={busy}
                      onChange={event => {
                        const destination = event.target.value;
                        updateClans(clans.map(tag => tag === clanTag ? destination : tag === destination ? clanTag : tag));
                        setFocusedClan(destination);
                      }}
                    >
                      {available.map(item => (
                        <option value={item.tag} key={item.tag}>{item.name} · {item.cwl_league || 'League unavailable'} · {item.tag}</option>
                      ))}
                    </select>
                  </details>
                  <div className="compare-player-list">
                    {members.length ? members.map(account => {
                      const location = comparisonLocation(locations[account.tag], clanTag, now);
                      return (
                        <div key={account.tag} className={`compare-account compare-account-${location.state}`}>
                          <div className="compare-player-info">
                            <strong>{account.player_name}</strong>
                            <small>{account.tag} · TH {account.town_hall ?? '—'} · {weightText(account.effective_weight)}</small>
                            <span title={location.detail}>{location.label}</span>
                          </div>
                          <button type="button" className="compare-details" disabled={busy} onClick={() => onEdit(account.tag)} aria-label={`Details for ${account.player_name}`}>
                            Details
                          </button>
                          <DiscordContact userId={account.user_id} compact />
                        </div>
                      );
                    }) : <p>No accounts match in this clan.</p>}
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
