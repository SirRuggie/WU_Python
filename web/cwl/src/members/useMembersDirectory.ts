import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Directory } from "../memberTimezones/types";
import type { RoleChoice } from "../CommandExtras";
import type { DirectoryMember } from "./model";
import { membersText as t } from "./strings";
export type MembersDirectory = Omit<Directory, "members"> & {
  members: DirectoryMember[];
  roles: RoleChoice[];
  manageable_roles: RoleChoice[];
};
const discordId = (value: unknown) =>
  typeof value === "string" && /^[1-9][0-9]{14,21}$/.test(value);
const zoneChoice = (value: { id: string; label: string }) =>
  !!value && typeof value.id === "string" && typeof value.label === "string";
export default function useMembersDirectory(
  onDenied: () => void,
  enabled = true,
) {
  const [data, setData] = useState<MembersDirectory | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const generation = useRef(0),
    alive = useRef(true),
    controller = useRef<AbortController | null>(null),
    denied = useRef(onDenied);
  denied.current = onDenied;
  function clear() {
    generation.current++;
    controller.current?.abort();
    setData(null);
  }
  async function load() {
    if (!enabled) return;
    const version = ++generation.current;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true);
    setError("");
    const timer = window.setTimeout(() => abort.abort(), 45000);
    try {
      const next = await api<MembersDirectory>(
        "/manage/members",
        "GET",
        undefined,
        { signal: abort.signal },
      );
      if (!alive.current || version !== generation.current) return;
      if (
        !next ||
        !Array.isArray(next.members) ||
        next.members.length > 10000 ||
        next.members.some(
          (row) =>
            !row ||
            !discordId(row.discord_id) ||
            typeof row.name !== "string" ||
            (row.nickname !== null && typeof row.nickname !== "string") ||
            typeof row.bot !== "boolean" ||
            typeof row.status !== "string" ||
            (row.username !== undefined && typeof row.username !== "string") ||
            (row.skip_reason !== null && typeof row.skip_reason !== "string") ||
            !Array.isArray(row.role_ids) ||
            row.role_ids.some((id) => !discordId(id)) ||
            new Set(row.role_ids).size !== row.role_ids.length ||
            (row.parsed !== null &&
              (!row.parsed ||
                typeof row.parsed.label !== "string" ||
                (row.parsed.offsetMinutes !== null &&
                  !Number.isFinite(row.parsed.offsetMinutes)))) ||
            (row.profile !== null &&
              (!row.profile ||
                !Number.isFinite(row.profile.utc_offset_minutes) ||
                typeof row.profile.zone_id !== "string" ||
                typeof row.profile.gmt_label !== "string" ||
                typeof row.profile.source !== "string" ||
                !Number.isSafeInteger(row.profile.revision) ||
                row.profile.revision < 0 ||
                (row.profile.country !== null &&
                  typeof row.profile.country !== "string") ||
                (row.profile.flag !== null &&
                  typeof row.profile.flag !== "string") ||
                (row.profile.name_source_tag !== null &&
                  typeof row.profile.name_source_tag !== "string"))),
        ) ||
        new Set(next.members.map((row) => row.discord_id)).size !==
          next.members.length ||
        !Array.isArray(next.roles) ||
        !Array.isArray(next.manageable_roles) ||
        [...next.roles, ...next.manageable_roles].some(
          (role) =>
            !role || !discordId(role.id) || typeof role.name !== "string",
        ) ||
        new Set(next.roles.map((role) => role.id)).size !== next.roles.length ||
        new Set(next.manageable_roles.map((role) => role.id)).size !==
          next.manageable_roles.length ||
        next.manageable_roles.some(
          (role) => !next.roles.some((known) => known.id === role.id),
        ) ||
        !Array.isArray(next.countries) ||
        next.countries.some(
          (country) =>
            !country ||
            typeof country.code !== "string" ||
            typeof country.label !== "string" ||
            typeof country.flag !== "string" ||
            (country.zones !== undefined &&
              (!Array.isArray(country.zones) ||
                country.zones.some((zone) => !zoneChoice(zone)))),
        ) ||
        !Array.isArray(next.zones) ||
        next.zones.some((zone) => !zoneChoice(zone))
      )
        throw new Error(t.membersUnavailable);
      setData(next);
    } catch (cause) {
      if (!alive.current || version !== generation.current) return;
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setData(null);
        denied.current();
      }
      setError(cause instanceof Error ? cause.message : t.membersUnavailable);
    } finally {
      window.clearTimeout(timer);
      if (alive.current && version === generation.current) setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    if (enabled) void load();
    else {
      setData(null);
      setLoading(false);
    }
    return () => {
      alive.current = false;
      generation.current++;
      controller.current?.abort();
    };
  }, [enabled]);
  return { data, loading, error, load, clear };
}
