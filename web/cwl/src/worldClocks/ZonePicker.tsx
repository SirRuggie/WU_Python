import { useEffect, useId, useState } from "react";
import { api } from "../api";
import FilterChips from "../FilterChips";
import {
  API_BASE,
  searchZones,
  zoneCity,
  type ZoneChip,
  type ZoneRow,
} from "./worldClocksModel";

let zoneCache: Promise<ZoneRow[]> | null = null;

function loadZones() {
  zoneCache ??= api<{ zones: ZoneRow[] }>(`${API_BASE}/zones`)
    .then((result) => (Array.isArray(result?.zones) ? result.zones : []))
    .catch((error) => {
      zoneCache = null;
      throw error;
    });
  return zoneCache;
}

/** Quick city chips plus a search over every time zone. */
export default function ZonePicker({
  value,
  onChange,
  chips,
  usedZones,
  disabled,
}: {
  value: string;
  onChange: (zone: string, flag: string) => void;
  chips: ZoneChip[];
  usedZones: Set<string>;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [zones, setZones] = useState<ZoneRow[]>([]);
  const [loadError, setLoadError] = useState("");
  const searchId = useId();
  const listId = useId();

  useEffect(() => {
    if (!query.trim() || zones.length) return;
    let current = true;
    loadZones()
      .then((rows) => current && setZones(rows))
      .catch(
        () =>
          current &&
          setLoadError("Zone search is unavailable. Use the city buttons."),
      );
    return () => {
      current = false;
    };
  }, [query, zones.length]);

  const matches = searchZones(
    zones,
    query,
    8,
    chips.map((chip) => chip.zone),
  );
  const chipValue = chips.some((chip) => chip.zone === value) ? value : null;

  return (
    <div className="world-clock-zone">
      <label className="world-clock-label" htmlFor={searchId}>
        Time zone
      </label>
      <input
        id={searchId}
        className="world-clock-input"
        type="search"
        value={query}
        disabled={disabled}
        placeholder="Search a city, country or code (EST)"
        autoComplete="off"
        aria-controls={listId}
        onChange={(event) => setQuery(event.target.value)}
      />
      {query.trim() && (
        <ul
          id={listId}
          className="world-clock-zone-results"
          aria-label="Matching time zones"
        >
          {matches.map((row) => (
            <li key={row.zone}>
              <button
                type="button"
                aria-pressed={row.zone === value}
                disabled={disabled}
                onClick={() => {
                  onChange(row.zone, row.flag);
                  setQuery("");
                }}
              >
                <span aria-hidden="true">{row.flag}</span>
                <span className="world-clock-zone-city">{row.city}</span>
                <small>
                  {row.region} · {row.offset}
                  {row.codes?.length ? ` · ${row.codes.join("/")}` : ""}
                </small>
              </button>
            </li>
          ))}
          {!matches.length && !loadError && zones.length > 0 && (
            <li className="world-clock-help">
              No zone matches. Try a bigger city nearby.
            </li>
          )}
          {loadError && <li className="world-clock-help">{loadError}</li>}
        </ul>
      )}
      <FilterChips
        label="Common time zones"
        className="world-clock-chips"
        variant="pill"
        value={chipValue}
        disabled={disabled}
        options={chips.map((chip) => ({
          value: chip.zone,
          label: (
            <>
              <span aria-hidden="true">{chip.flag} </span>
              {chip.label}
              {usedZones.has(chip.zone) && chip.zone !== value && (
                <small> · has a clock</small>
              )}
            </>
          ),
          ariaLabel: `${chip.label}${usedZones.has(chip.zone) && chip.zone !== value ? ", has a clock" : ""}`,
        }))}
        onChange={(zone) =>
          onChange(zone, chips.find((chip) => chip.zone === zone)?.flag || "")
        }
      />
      {value && (
        <p className="world-clock-help">
          Selected: <strong>{zoneCity(value)}</strong> ({value}). Summer time
          changes by itself.
        </p>
      )}
    </div>
  );
}
