import { useState } from "react";
import { api } from "../api";
import FilterChips from "../FilterChips";
import SearchPicker, { type PickerOption } from "../SearchPicker";
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

const HAS_CLOCK = "has a clock";

/** Time zone search plus quick city chips. */
export default function ZonePicker({
  value,
  flag,
  onChange,
  chips,
  usedZones,
  disabled,
}: {
  value: string;
  flag: string;
  onChange: (zone: string, flag: string) => void;
  chips: ZoneChip[];
  usedZones: Set<string>;
  disabled?: boolean;
}) {
  const [zones, setZones] = useState<ZoneRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const chipZones = chips.map((chip) => chip.zone);
  const used = (zone: string) =>
    usedZones.has(zone) && zone !== value ? HAS_CLOCK : "";

  const chipOptions: PickerOption[] = chips.map((chip) => ({
    value: chip.zone,
    label: chip.label,
    detail: [chip.zone, used(chip.zone)].filter(Boolean).join(" · "),
    icon: chip.flag,
  }));

  function search(query: string): PickerOption[] {
    if (!query.trim()) return chipOptions;
    return searchZones(zones, query, 30, chipZones).map((row) => ({
      value: row.zone,
      label: row.city,
      detail: [
        row.region,
        row.offset,
        row.codes?.length ? row.codes.join("/") : "",
        used(row.zone),
      ]
        .filter(Boolean)
        .join(" · "),
      icon: row.flag,
    }));
  }

  function open() {
    if (zones.length || loading) return;
    setLoading(true);
    setLoadError("");
    loadZones()
      .then(setZones)
      .catch(() =>
        setLoadError("Zone search is unavailable. Use the city buttons."),
      )
      .finally(() => setLoading(false));
  }

  function choose(zone: string) {
    const row =
      zones.find((item) => item.zone === zone) ||
      chips.find((chip) => chip.zone === zone);
    onChange(zone, row?.flag || "");
  }

  const chipValue = chips.some((chip) => chip.zone === value) ? value : null;

  return (
    <div className="world-clock-zone">
      <SearchPicker
        label="Time zone"
        value={value}
        options={chipOptions}
        search={search}
        fallback={
          value
            ? { value, label: zoneCity(value), detail: value, icon: flag }
            : undefined
        }
        placeholder="Select a time zone"
        searchPlaceholder="City, country or code (EST)"
        emptyText="No zone matches. Try a bigger city nearby."
        status={loadError || (loading ? "Loading time zones…" : "")}
        disabled={disabled}
        onOpen={open}
        onChange={choose}
      />
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
              {used(chip.zone) && <small> · {HAS_CLOCK}</small>}
            </>
          ),
          ariaLabel: `${chip.label}${used(chip.zone) ? `, ${HAS_CLOCK}` : ""}`,
        }))}
        onChange={(zone) =>
          onChange(zone, chips.find((chip) => chip.zone === zone)?.flag || "")
        }
      />
      {value && (
        <p className="world-clock-help">Summer time changes by itself.</p>
      )}
    </div>
  );
}
