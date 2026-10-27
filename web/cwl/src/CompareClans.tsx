import type { ComparisonMemory } from "./comparisonMemory";
import SortTrigger from "./rosterUi/SortTrigger";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  RotateCw,
  SlidersHorizontal,
} from "lucide-react";
import RosterMenu from "./rosterUi/Menu";
import ActionMenu from "./rosterUi/ActionMenu";
import ActionPanel from "./ActionPanel";
import { Menu as AriaMenu, MenuItem } from "react-aria-components";
import { Button } from "./rosterUi/primitives";
import { type Pool } from "./api";
import { useComparisonLocations } from "./useComparisonLocations";
import { comparisonAge } from "./comparisonLocation";
import { matchesLeague, matchesTownHall } from "./ClanFilters";
import { sortClans } from "./clanSort";
import { compareClanAccounts, comparisonOrder } from "./compare";
import ComparePlayerCard from "./ComparePlayerCard";
import CompareClanHeader from "./CompareClanHeader";
import CompareFilterPanel from "./CompareFilterPanel";
import CompareClanPicker from "./CompareClanPicker";
import {
  assignmentOptions,
  type RosterSnapshot,
  type RosterSort,
} from "./roster";
import "./CompareClans.css";

type Props = {
  memory: ComparisonMemory;
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
  memory,
  pool,
  seasonId,
  roster,
  busy,
  onEdit,
  refreshKey = 0,
}: Props) {
  const [leagues, setLeagues] = useState<string[]>([]),
    [townHalls, setTownHalls] = useState<string[]>([]);
  const [clans, setClans] = useState<string[]>([]),
    [sort, setSort] = useState<RosterSort>("town_hall_desc");
  const [focusedClan, setFocusedClan] = useState("");
  const [panel, setPanel] = useState<"filters" | "clans" | "sort" | null>(null);
  const [replacing, setReplacing] = useState<string>();
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const [overflow, setOverflow] = useState(false),
    [edges, setEdges] = useState({ left: false, right: false });
  const [columnHeight, setColumnHeight] = useState(500);
  const loadedPreference = useRef<string | null>(null),
    scroller = useRef<HTMLDivElement>(null),
    rail = useRef<HTMLDivElement>(null);
  const swiped = useRef(false);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const allClans = sortClans(
    assignmentOptions(roster.clans).filter((clan) => clan.pool === pool),
    "name",
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
  const selectedFocus = visibleClans.includes(focusedClan)
    ? focusedClan
    : visibleClans[0];
  const {
    records: locations,
    checking,
    error: locationError,
    now,
    checkedAt,
    published,
    refresh,
  } = useComparisonLocations(
    memory,
    seasonId,
    pool,
    clans.length > 0,
    roster.revision,
    refreshKey,
  );
  useEffect(() => {
    const key = `${seasonId}:${pool}`,
      changed = loadedPreference.current !== key;
    let saved: unknown = null;
    if (changed) {
      try {
        saved = JSON.parse(
          localStorage.getItem(`wu-compare-clans:${key}`) || "null",
        );
      } catch {}
      loadedPreference.current = key;
    }
    setClans((current) =>
      comparisonOrder(
        changed ? saved : current,
        allClans.map((clan) => clan.tag),
      ),
    );
  }, [seasonId, pool, activeTags]);
  // Pool switches reset view controls without discarding per-tag location records.
  useEffect(() => {
    setLeagues([]);
    setTownHalls([]);
    setSort("town_hall_desc");
    setFocusedClan("");
    setPanel(null);
  }, [pool]);

  function updateClans(next: string[]) {
    setClans(next);
    try {
      localStorage.setItem(
        `wu-compare-clans:${seasonId}:${pool}`,
        JSON.stringify(next),
      );
    } catch {}
  }
  function openPanel(
    next: "filters" | "clans" | "sort",
    element: HTMLElement,
    replace?: string,
  ) {
    setTrigger(element);
    setReplacing(replace);
    setPanel(next);
  }
  const updateEdges = () => {
    const el = scroller.current;
    if (el)
      setEdges({
        left: el.scrollLeft > 2,
        right: el.scrollLeft + el.clientWidth < el.scrollWidth - 2,
      });
  };
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => {
      setOverflow(el.scrollWidth > el.clientWidth + 2);
      updateEdges();
      const top =
        document.querySelector(".topbar")?.getBoundingClientRect().height ?? 74;
      setColumnHeight(Math.max(280, window.innerHeight - top - 24));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [visibleClans.join("|"), roster.revision]);
  function moveTo(index: number) {
    const el = scroller.current,
      col = el?.children[index] as HTMLElement | undefined;
    if (!el || !col) return;
    el.scrollTo({
      left:
        el.scrollLeft +
        col.getBoundingClientRect().left -
        el.getBoundingClientRect().left,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }
  function stepDesktop(direction: number) {
    const el = scroller.current;
    if (!el) return;
    const children = Array.from(el.children) as HTMLElement[];
    const nearest = children.reduce(
      (best, child, i) =>
        Math.abs(
          child.getBoundingClientRect().left - el.getBoundingClientRect().left,
        ) <
        Math.abs(
          children[best].getBoundingClientRect().left -
            el.getBoundingClientRect().left,
        )
          ? i
          : best,
      0,
    );
    moveTo(Math.max(0, Math.min(children.length - 1, nearest + direction)));
  }
  function focusAt(index: number) {
    const tag = visibleClans[index];
    if (!tag) return;
    setFocusedClan(tag);
    const el = rail.current,
      card = el?.children[index] as HTMLElement | undefined;
    if (el && card)
      el.scrollTo({
        left:
          el.scrollLeft +
          card.getBoundingClientRect().left -
          el.getBoundingClientRect().left,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
  }
  const filterCount = leagues.length + townHalls.length;
  return (
    <section
      className="compare-workspace card roster-ui"
      aria-labelledby="compare-title"
    >
      <header className="compare-header">
        <div>
          <h2 id="compare-title">Compare clans</h2>
          <small>
            {pool === "main" ? "Main" : "Lazy"} CWL · {visibleClans.length}{" "}
            shown
          </small>
        </div>
        <Button
          disabled={busy || !allClans.length}
          onClick={(event) => openPanel("clans", event.currentTarget)}
        >
          Choose clans ({clans.length})
        </Button>
      </header>
      <div
        className="compare-toolbar"
        role="group"
        aria-label="Comparison filters and status"
      >
        <Button
          icon={SlidersHorizontal}
          disabled={busy}
          onClick={(event) => openPanel("filters", event.currentTarget)}
        >
          Filters{filterCount ? ` (${filterCount})` : ""}
        </Button>
        <SortTrigger
          disabled={busy}
          label={
            playerSortOptions.find((option) => option.value === sort)!.label
          }
          onClick={(event) => openPanel("sort", event.currentTarget)}
        />
        <Button
          icon={RotateCw}
          label="Refresh locations"
          disabled={busy || checking}
          onClick={refresh}
        >
          {checking
            ? "Checking…"
            : checkedAt
              ? comparisonAge(new Date(checkedAt).toISOString(), now)
              : "Refresh"}
        </Button>
      </div>
      {locationError && (
        <p className="compare-toolbar-note" role="status">
          {locationError}
        </p>
      )}
      {roster.clans.some((clan) => !clan.archived && !clan.pool) && (
        <p className="inline-reason">
          Some hosting clans need a Main or Lazy CWL pool in Clan settings
          before they can be compared.
        </p>
      )}
      {panel === "filters" && (
        <CompareFilterPanel
          accounts={roster.accounts}
          clans={allClans}
          chosen={clans}
          leagues={leagues}
          townHalls={townHalls}
          trigger={trigger}
          onClose={() => setPanel(null)}
          onApply={(nextLeagues, halls) => {
            setLeagues(nextLeagues);
            setTownHalls(halls);
            setPanel(null);
          }}
        />
      )}
      {panel === "clans" && (
        <CompareClanPicker
          clans={available}
          chosen={clans}
          trigger={trigger}
          replace={replacing}
          onClose={() => setPanel(null)}
          onChange={updateClans}
        />
      )}
      {panel === "sort" && (
        <ActionPanel
          title="Sort players"
          trigger={trigger}
          onClose={() => setPanel(null)}
          className="roster-ui"
        >
          <AriaMenu aria-label="Sort players" className="roster-menu-list">
            {playerSortOptions.map((option) => (
              <MenuItem
                key={option.value}
                id={option.value}
                textValue={option.label}
                className="roster-menu-item"
                aria-label={`${option.label}${sort === option.value ? ", selected" : ""}`}
                onAction={() => {
                  setSort(option.value);
                  setPanel(null);
                }}
              >
                {option.label}
                {sort === option.value ? " ✓" : ""}
              </MenuItem>
            ))}
          </AriaMenu>
        </ActionPanel>
      )}
      {visibleClans.length < clans.length && (
        <p className="inline-reason">
          {clans.length - visibleClans.length} chosen clans are hidden by
          filters.
        </p>
      )}
      {!allClans.length && (
        <p>No active {pool === "main" ? "Main" : "Lazy"} hosting clans.</p>
      )}
      {!!allClans.length && !visibleClans.length && (
        <p>Choose clans or reset filters to start comparing.</p>
      )}
      {!!visibleClans.length && (
        <>
          <div
            className="compare-mobile-rail"
            ref={rail}
            aria-label="Choose a clan to view"
          >
            {visibleClans.map((tag) => {
              const clan = available.find((c) => c.tag === tag)!;
              return (
                <button
                  key={tag}
                  type="button"
                  className={`compare-mobile-card${tag === selectedFocus ? " is-active" : ""}`}
                  aria-pressed={tag === selectedFocus}
                  onClick={() => setFocusedClan(tag)}
                >
                  <CompareClanHeader
                    clan={clan}
                    accounts={roster.accounts}
                    locations={locations}
                    compact
                  />
                </button>
              );
            })}
          </div>
          <div className="compare-mobile-navigation">
            <Button
              icon={ArrowLeft}
              variant="icon"
              label="Previous clan"
              disabled={visibleClans.indexOf(selectedFocus) === 0}
              onClick={() => focusAt(visibleClans.indexOf(selectedFocus) - 1)}
            />
            <span>
              {visibleClans.indexOf(selectedFocus) + 1} of {visibleClans.length}
            </span>
            <Button
              icon={ArrowRight}
              variant="icon"
              label="Next clan"
              disabled={
                visibleClans.indexOf(selectedFocus) === visibleClans.length - 1
              }
              onClick={() => focusAt(visibleClans.indexOf(selectedFocus) + 1)}
            />
          </div>
          {overflow && (
            <div className="compare-navigation">
              <Button
                icon={ArrowLeft}
                variant="icon"
                label="Scroll to previous clan"
                disabled={!edges.left}
                onClick={() => stepDesktop(-1)}
              />
              <Button
                icon={ArrowRight}
                variant="icon"
                label="Scroll to next clan"
                disabled={!edges.right}
                onClick={() => stepDesktop(1)}
              />
              <RosterMenu
                label="Jump to clan"
                value=""
                options={visibleClans.map((tag, i) => ({
                  value: String(i),
                  label: available.find((c) => c.tag === tag)!.name,
                }))}
                onValueChange={(value) => moveTo(Number(value))}
              />
            </div>
          )}
          <div
            className={`compare-pan-frame${edges.left ? " has-left" : ""}${edges.right ? " has-right" : ""}`}
          >
            <div
              className="compare-pan"
              ref={scroller}
              onScroll={updateEdges}
              tabIndex={0}
              role="region"
              aria-label="Clan comparison"
              style={
                {
                  gridTemplateColumns: `repeat(${visibleClans.length}, minmax(300px, 1fr))`,
                  "--compare-column-height": `${columnHeight}px`,
                } as CSSProperties
              }
            >
              {visibleClans.map((clanTag) => {
                const clan = available.find((c) => c.tag === clanTag)!;
                const members = compareClanAccounts(
                  roster.accounts,
                  clanTag,
                  sort,
                ).filter((account) =>
                  matchesTownHall(account.town_hall, townHalls),
                );
                return (
                  <section
                    key={clanTag}
                    className={`compare-side${clanTag === selectedFocus ? " mobile-current" : ""}`}
                    aria-label={`${clan.name} comparison`}
                  >
                    <CompareClanHeader
                      clan={clan}
                      accounts={roster.accounts}
                      locations={locations}
                      menu={
                        <ActionMenu
                          name={clan.name}
                          disabled={busy}
                          items={[
                            {
                              id: "change",
                              label: "Change clan in this column",
                              onAction: (element) =>
                                openPanel("clans", element, clanTag),
                            },
                          ]}
                        />
                      }
                    />
                    <div
                      className="compare-player-list"
                      onClickCapture={(event) => {
                        if (swiped.current) {
                          swiped.current = false;
                          event.preventDefault();
                          event.stopPropagation();
                        }
                      }}
                      onTouchStart={(event) => {
                        const point = event.touches[0];
                        swiped.current = false;
                        touch.current = { x: point.clientX, y: point.clientY };
                      }}
                      onTouchEnd={(event) => {
                        const start = touch.current;
                        touch.current = null;
                        if (!start) return;
                        const point = event.changedTouches[0],
                          dx = point.clientX - start.x,
                          dy = point.clientY - start.y;
                        if (
                          Math.abs(dx) > 70 &&
                          Math.abs(dx) > Math.abs(dy) * 1.5
                        ) {
                          swiped.current = true;
                          focusAt(
                            visibleClans.indexOf(selectedFocus) +
                              (dx < 0 ? 1 : -1),
                          );
                        }
                      }}
                    >
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
          </div>
        </>
      )}
    </section>
  );
}
