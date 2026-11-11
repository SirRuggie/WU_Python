// Types and small helpers for Bot → World clocks. The server builds every
// channel name, so the page never guesses a name the bot will not write.

export type ClockStatus = "ok" | "waiting" | "problem";

export type WorldClock = {
  id: string;
  zone: string;
  flag: string;
  code: string | null;
  code_auto: string | null;
  flag_auto: string;
  needs_code: boolean;
  channel_id: string | null;
  channel_name: string | null;
  channel_missing: boolean;
  enabled: boolean;
  revision: string;
  last_name: string | null;
  last_renamed_at: string | null;
  status: ClockStatus;
  status_detail: string;
  name_now: string | null;
  name_other: string | null;
  offset_minutes: number;
};

export type ClockSettings = {
  category_id: string | null;
  time_format: "12h" | "24h";
  interval_minutes: 6 | 10;
  revision: string;
};

export type VoiceChannel = {
  id: string;
  name: string;
  category: string;
  used: boolean;
};

export type ClockRun = {
  at: string;
  renamed?: number;
  unchanged?: number;
  waited?: number;
  problem?: number;
  moved?: boolean;
  discord_unavailable?: boolean;
};

export type ZoneChip = { label: string; zone: string; flag: string };

export type WorldClocksData = {
  settings: ClockSettings;
  clocks: WorldClock[];
  channels_available: boolean;
  categories: { id: string; name: string }[];
  voice_channels: VoiceChannel[];
  chips: ZoneChip[];
  now: string;
  next_update: string;
  runs: ClockRun[];
  max_clocks: number;
};

export type ZoneRow = {
  zone: string;
  city: string;
  region: string;
  flag: string;
  offset: string;
  /** Letter codes now and in the other half of the year, e.g. ["CST", "CDT"]. */
  codes?: string[];
};

export type ClockPreview = {
  code_auto: string | null;
  flag_auto: string;
  needs_code: boolean;
  name_now: string | null;
  name_other: string | null;
};

export type ClockDraft = {
  zone: string;
  flag: string;
  code: string;
  channel_id: string;
};

export const API_BASE = "/manage/world-clocks";

/** A clock with a problem is the only state that needs staff action. */
export function hasProblem(clock: WorldClock) {
  return clock.enabled && (clock.status === "problem" || clock.channel_missing);
}

export function problemText(clock: WorldClock) {
  if (clock.channel_missing)
    return "Channel missing. Select another voice channel.";
  return clock.status_detail || "Check this clock.";
}

export function statusCounts(clocks: WorldClock[]) {
  let updating = 0,
    problems = 0,
    off = 0;
  for (const clock of clocks) {
    if (!clock.enabled) off += 1;
    else if (hasProblem(clock)) problems += 1;
    else updating += 1;
  }
  return { updating, problems, off };
}

/** A voice channel as a picker row: name, then its category. */
export function voiceOption(channel: VoiceChannel, note = "") {
  return {
    value: channel.id,
    label: channel.name,
    detail: channel.category || undefined,
    icon: "🔊",
    disabledNote: note || undefined,
  };
}

export function zoneCity(zone: string) {
  const parts = zone.split("/");
  return (parts[parts.length - 1] || zone).replace(/_/g, " ");
}

export function localTime(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** The name members see now: the last name the bot wrote, else the preview. */
export function discordName(clock: WorldClock) {
  return clock.last_name || clock.channel_name || clock.name_now || clock.zone;
}

export function draftFrom(clock: WorldClock): ClockDraft {
  return {
    zone: clock.zone,
    flag: clock.flag,
    code: clock.code || "",
    channel_id: clock.channel_id || "",
  };
}

export function sameDraft(a: ClockDraft, b: ClockDraft) {
  return (
    a.zone === b.zone &&
    a.flag === b.flag &&
    a.code.trim().toUpperCase() === b.code.trim().toUpperCase() &&
    a.channel_id === b.channel_id
  );
}

/**
 * Search by city, region, offset or code (EST, CDT, PHT …).
 *
 * Zones whose code equals a typed word come first, and among those the common
 * cities (`preferred`, the city chips) lead, so "CST" shows Chicago before
 * the other Central zones and before China Standard Time.
 */
export function searchZones(
  rows: ZoneRow[],
  query: string,
  limit = 8,
  preferred: string[] = [],
) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const rank = (row: ZoneRow) => {
    const codes = (row.codes || []).map((code) => code.toLowerCase());
    const codeHit = words.some((word) => codes.includes(word));
    const chip = preferred.indexOf(row.zone);
    return (
      (codeHit ? 0 : 2) + (chip >= 0 ? 0 : 1) + (chip >= 0 ? chip / 100 : 0)
    );
  };
  return rows
    .filter((row) => {
      const text =
        `${row.city} ${row.region} ${row.zone} ${row.offset} ${(row.codes || []).join(" ")}`.toLowerCase();
      return words.every((word) => text.includes(word));
    })
    .map((row, index) => ({ row, index, rank: rank(row) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .slice(0, limit)
    .map((item) => item.row);
}

export function newRequestId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID();
  // Fallback for old browsers: RFC 4122 version 4 layout.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = (Math.random() * 16) | 0;
    return (char === "x" ? value : (value & 0x3) | 0x8).toString(16);
  });
}

/**
 * Split "🇺🇸 EST (GMT-5) · 9:30pm · Wed 11" at the first dot, so the time and
 * day stay together and never wrap on their own.
 */
export function nameParts(name: string) {
  const index = name.indexOf(" · ");
  return index < 0
    ? { label: name, time: "" }
    : { label: name.slice(0, index), time: name.slice(index + 3) };
}
