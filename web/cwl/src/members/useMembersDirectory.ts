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
            !/^[1-9][0-9]{14,21}$/.test(row.discord_id) ||
            typeof row.name !== "string" ||
            (row.nickname !== null && typeof row.nickname !== "string") ||
            typeof row.bot !== "boolean" ||
            !Array.isArray(row.role_ids) ||
            row.role_ids.some((id) => typeof id !== "string") ||
            (row.parsed !== null &&
              (!row.parsed ||
                typeof row.parsed.label !== "string" ||
                (row.parsed.offsetMinutes !== null &&
                  !Number.isFinite(row.parsed.offsetMinutes)))) ||
            (row.profile !== null &&
              (!row.profile ||
                !Number.isFinite(row.profile.utc_offset_minutes))),
        ) ||
        new Set(next.members.map((row) => row.discord_id)).size !==
          next.members.length ||
        !Array.isArray(next.roles) ||
        !Array.isArray(next.manageable_roles) ||
        [...next.roles, ...next.manageable_roles].some(
          (role) =>
            !role ||
            typeof role.id !== "string" ||
            typeof role.name !== "string",
        ) ||
        !Array.isArray(next.countries) ||
        !Array.isArray(next.zones)
      )
        throw new Error(t.roleUnavailable);
      setData(next);
    } catch (cause) {
      if (!alive.current || version !== generation.current) return;
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setData(null);
        denied.current();
      }
      setError(cause instanceof Error ? cause.message : t.roleUnavailable);
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
