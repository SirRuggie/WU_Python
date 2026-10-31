import RosterFilterOptions from "./RosterFilterOptions";
import { useEffect, useState, type ReactNode } from "react";
import { Filter, Search, SlidersHorizontal } from "lucide-react";
import ActionPanel from "./ActionPanel";
import type { RosterSnapshot } from "./roster";
import { parseWeightK } from "./roster";
import {
  DEFAULT_ROSTER_RELEASE_PREFERENCES,
  ROSTER_RELEASE_STATUSES,
  deriveRosterRelease,
  type RosterReleaseFilters,
  type RosterReleaseStatus,
} from "./rosterReleaseModel";
import { Button, Chip, Input } from "./rosterUi/primitives";
import "./RosterFilters.css";

type Props = {
  roster: RosterSnapshot;
  value: RosterReleaseFilters;
  onChange: (next: RosterReleaseFilters) => void;
  disabled: boolean;
  children?: ReactNode;
  onOpenChange?: (open: boolean) => void;
};

const statusLabels: Record<RosterReleaseStatus, string> = {
  assigned: "Assigned",
  unassigned: "Unassigned",
  missing_weight: "Missing weight",
  over_capacity: "Over capacity",
  locked: "Locked placement",
  outside_family: "Outside family",
};

export function activeRosterFilterCount(value: RosterReleaseFilters): number {
  return (
    value.statuses.length +
    value.townHalls.length +
    value.assignedClanTags.length +
    Number(value.minWeight !== null) +
    Number(value.maxWeight !== null)
  );
}

export function clearRosterFiltersPreservingPool(
  value: RosterReleaseFilters,
): RosterReleaseFilters {
  return {
    ...DEFAULT_ROSTER_RELEASE_PREFERENCES,
    pool: value.pool,
    statuses: [],
    townHalls: [],
    assignedClanTags: [],
  };
}

function weightDraft(value: number | null): string {
  return value === null ? "" : String(value / 1000);
}

function parseWeightRange(minimum: string, maximum: string) {
  try {
    const minWeight = parseWeightK(minimum);
    const maxWeight = parseWeightK(maximum);
    if (minWeight !== null && maxWeight !== null && minWeight > maxWeight) {
      return {
        minWeight: null,
        maxWeight: null,
        error: "Maximum weight must be at least the minimum.",
      };
    }
    return { minWeight, maxWeight, error: "" };
  } catch (cause) {
    return {
      minWeight: null,
      maxWeight: null,
      error:
        cause instanceof Error
          ? cause.message
          : "Enter a valid weight in thousands.",
    };
  }
}

export default function RosterFilters({
  roster,
  value,
  onChange,
  disabled,
  children,
  onOpenChange,
}: Props) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    onOpenChange?.(open);
    return () => onOpenChange?.(false);
  }, [open, onOpenChange]);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const [draft, setDraft] = useState<RosterReleaseFilters>(value);
  const [minText, setMinText] = useState(weightDraft(value.minWeight));
  const [maxText, setMaxText] = useState(weightDraft(value.maxWeight));
  const [clanSearch, setClanSearch] = useState("");

  const openPanel = (element: HTMLElement) => {
    setDraft({
      ...value,
      statuses: [...value.statuses],
      townHalls: [...value.townHalls],
      assignedClanTags: [...value.assignedClanTags],
    });
    setMinText(weightDraft(value.minWeight));
    setMaxText(weightDraft(value.maxWeight));
    setClanSearch("");
    setTrigger(element);
    setOpen(true);
  };
  const range = parseWeightRange(minText, maxText);
  const preview = {
    ...draft,
    minWeight: range.minWeight,
    maxWeight: range.maxWeight,
  };
  const result = deriveRosterRelease(roster.accounts, roster.clans, preview);
  const availableTownHalls = [
    ...new Set(roster.accounts.map((account) => account.town_hall)),
  ]
    .filter((value): value is number => value !== null)
    .sort((left, right) => right - left);
  const assignedTags = new Set(
    roster.accounts.map((account) => account.assigned_clan_tag),
  );
  const availableClans = roster.clans
    .filter(
      (clan) =>
        !clan.archived ||
        assignedTags.has(clan.tag) ||
        draft.assignedClanTags.includes(clan.tag),
    )
    .filter((clan) =>
      `${clan.name} ${clan.tag}`
        .toLocaleLowerCase()
        .includes(clanSearch.trim().toLocaleLowerCase()),
    )
    .sort((left, right) => left.name.localeCompare(right.name));
  const clanNames = new Map(roster.clans.map((clan) => [clan.tag, clan.name]));
  const count = activeRosterFilterCount(value);
  const apply = () => {
    if (range.error || disabled) return;
    onChange(preview);
    setOpen(false);
  };

  return (
    <div className="roster-filters roster-ui">
      <div className="roster-filters-toolbar">
        <Input
          label="Search accounts"
          type="search"
          icon={Search}
          value={value.search}
          disabled={disabled}
          placeholder="Name, player tag or Discord ID"
          onChange={(event) =>
            onChange({ ...value, search: event.target.value })
          }
        />
        <Button
          icon={SlidersHorizontal}
          disabled={disabled}
          onClick={(event) => openPanel(event.currentTarget)}
        >
          Filters{count ? ` (${count})` : ""}
        </Button>
        {children}
      </div>
      {(count > 0 || !!value.search.trim()) && (
        <div
          className="roster-filters-active"
          aria-label="Active roster filters"
        >
          {value.search.trim() && (
            <Chip
              onRemove={() => onChange({ ...value, search: "" })}
              removeLabel="Remove search filter"
            >
              Search: {value.search.trim()}
            </Chip>
          )}
          {value.statuses.map((status) => (
            <Chip
              key={status}
              onRemove={() =>
                onChange({
                  ...value,
                  statuses: value.statuses.filter((item) => item !== status),
                })
              }
              removeLabel={`Remove ${statusLabels[status]} filter`}
            >
              {statusLabels[status]}
            </Chip>
          ))}
          {value.minWeight !== null && (
            <Chip
              onRemove={() => onChange({ ...value, minWeight: null })}
              removeLabel="Remove minimum weight filter"
            >
              From {weightDraft(value.minWeight)}k
            </Chip>
          )}
          {value.maxWeight !== null && (
            <Chip
              onRemove={() => onChange({ ...value, maxWeight: null })}
              removeLabel="Remove maximum weight filter"
            >
              To {weightDraft(value.maxWeight)}k
            </Chip>
          )}
          {value.townHalls.map((level) => (
            <Chip
              key={level}
              onRemove={() =>
                onChange({
                  ...value,
                  townHalls: value.townHalls.filter((item) => item !== level),
                })
              }
              removeLabel={`Remove Town Hall ${level} filter`}
            >
              TH {level}
            </Chip>
          ))}
          {value.assignedClanTags.map((tag) => (
            <Chip
              key={tag}
              onRemove={() =>
                onChange({
                  ...value,
                  assignedClanTags: value.assignedClanTags.filter(
                    (item) => item !== tag,
                  ),
                })
              }
              removeLabel={`Remove ${clanNames.get(tag) || tag} clan filter`}
            >
              {clanNames.get(tag) || tag}
            </Chip>
          ))}
          <Button
            className="roster-filters-clear"
            disabled={disabled}
            onClick={() => onChange(clearRosterFiltersPreservingPool(value))}
          >
            Clear all
          </Button>
        </div>
      )}
      {open && (
        <ActionPanel
          title="Filter roster"
          variant="side"
          className="roster-ui roster-filters-panel"
          trigger={trigger}
          busy={disabled}
          onClose={() => setOpen(false)}
          footer={
            <div className="roster-filters-footer">
              <Button
                disabled={disabled}
                onClick={() => {
                  const cleared = clearRosterFiltersPreservingPool(draft);
                  setDraft(cleared);
                  setMinText("");
                  setMaxText("");
                }}
              >
                Reset
              </Button>
              <Button
                variant="primary"
                icon={Filter}
                disabled={disabled || !!range.error}
                onClick={apply}
              >
                Show {result.matches.length} accounts
              </Button>
            </div>
          }
        >
          <div className="roster-filters-fields">
            <p>
              Choose any status within a section. Different sections narrow the
              result together.
            </p>
            <RosterFilterOptions
              title="Status"
              options={ROSTER_RELEASE_STATUSES.map((status) => ({
                value: status,
                label: statusLabels[status],
                count: result.facets.status[status],
              }))}
              selected={draft.statuses}
              disabled={disabled}
              onChange={(statuses) =>
                setDraft((current) => ({
                  ...current,
                  statuses: statuses as RosterReleaseStatus[],
                }))
              }
            />
            <fieldset>
              <legend>Weight range (k)</legend>
              <div className="roster-filters-weight">
                <Input
                  label="Minimum"
                  type="number"
                  min="0"
                  step="any"
                  value={minText}
                  disabled={disabled}
                  placeholder="Any"
                  onChange={(event) => setMinText(event.target.value)}
                />
                <Input
                  label="Maximum"
                  type="number"
                  min="0"
                  step="any"
                  value={maxText}
                  disabled={disabled}
                  placeholder="Any"
                  onChange={(event) => setMaxText(event.target.value)}
                />
              </div>
              <small>
                Missing weights are excluded when a range is set.{" "}
                {result.facets.weightRangeCount} match the other filters.
              </small>
              {range.error && (
                <p role="alert" className="roster-filters-error">
                  {range.error}
                </p>
              )}
            </fieldset>
            <fieldset>
              <legend>Town Hall</legend>
              <div className="roster-filters-options roster-filters-th">
                {availableTownHalls.map((level) => (
                  <label key={level}>
                    <input
                      type="checkbox"
                      checked={draft.townHalls.includes(level)}
                      disabled={disabled}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          townHalls: event.target.checked
                            ? [...current.townHalls, level]
                            : current.townHalls.filter(
                                (item) => item !== level,
                              ),
                        }))
                      }
                    />
                    <span>TH {level}</span>
                    <small>{result.facets.townHall[String(level)] || 0}</small>
                  </label>
                ))}
              </div>
              {!availableTownHalls.length && (
                <p>No Town Hall levels are recorded.</p>
              )}
            </fieldset>
            <fieldset>
              <legend>Assigned clan</legend>
              <Input
                label="Find a hosting clan"
                type="search"
                value={clanSearch}
                disabled={disabled}
                placeholder="Clan name or tag"
                onChange={(event) => setClanSearch(event.target.value)}
              />
              <div className="roster-filters-options roster-filters-clans">
                {availableClans.map((clan) => (
                  <label key={clan.tag}>
                    <input
                      type="checkbox"
                      checked={draft.assignedClanTags.includes(clan.tag)}
                      disabled={disabled}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          assignedClanTags: event.target.checked
                            ? [...current.assignedClanTags, clan.tag]
                            : current.assignedClanTags.filter(
                                (item) => item !== clan.tag,
                              ),
                        }))
                      }
                    />
                    <span>
                      {clan.name}{" "}
                      <small>
                        {clan.tag}
                        {clan.archived ? " · Archived" : ""}
                      </small>
                    </span>
                    <small>{result.facets.assignedClan[clan.tag] || 0}</small>
                  </label>
                ))}
              </div>
              {!availableClans.length && <p>No clans match this search.</p>}
            </fieldset>
          </div>
        </ActionPanel>
      )}
    </div>
  );
}
