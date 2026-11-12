import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { RaffleData } from "./bonusRaffle";
import type { BonusStatus } from "./bonusStatus";

export type InfractionsLock = "draw" | "locked" | null;
export type Infractions = {
  data: RaffleData | null;
  state: "idle" | "loading" | "failed";
  /** Reads the season's bonus data once; the overview never loads it on its own. */
  load: () => void;
  /** Same PATCH and revision check as the bonus steps; throws the server message. */
  save: (tag: string, flags: string[], reason: string) => Promise<void>;
  /** Why a Lazy clan's infractions cannot change, if they cannot. */
  lock: (clanTag: string | null | undefined) => InfractionsLock;
};

/**
 * Lazy infractions for the Results & bonuses list. The list loads only the
 * light bonus status; this reads the full bonus data when Details opens for a
 * Lazy player, keeps it while the page stays open, and replaces it after a save.
 */
export default function useInfractions(
  seasonId: string,
  canManage: boolean,
  archived: boolean,
  status: BonusStatus | null,
  /** Runs after a save, so the list can read the new eligibility counts. */
  onSaved?: () => void,
): Infractions {
  const [data, setData] = useState<RaffleData | null>(null);
  const [state, setState] = useState<Infractions["state"]>("idle");
  const saved = useRef(onSaved);
  saved.current = onSaved;
  const request = useRef(0);
  const current = useRef(seasonId);
  current.current = seasonId;
  const path = `/seasons/${encodeURIComponent(seasonId)}/bonus-raffle`;

  useEffect(() => {
    request.current += 1;
    setData(null);
    setState("idle");
  }, [seasonId]);

  const load = useCallback(async () => {
    if (!seasonId) return;
    const id = ++request.current;
    setState("loading");
    try {
      const result = await api<RaffleData>(path);
      if (id !== request.current || current.current !== seasonId) return;
      setData(result);
      setState("idle");
    } catch {
      if (id !== request.current || current.current !== seasonId) return;
      setState("failed");
    }
  }, [path, seasonId]);

  const save = useCallback(
    async (tag: string, flags: string[], reason: string) => {
      if (!data) throw new Error("Infractions are not loaded. Try again.");
      const sid = seasonId;
      try {
        const result = await api<RaffleData>(
          path + "/account-review",
          "PATCH",
          {
            tag,
            flags,
            override_reason: reason,
            revision: data.revision,
          },
        );
        if (current.current !== sid) return;
        request.current += 1;
        setData(result);
        setState("idle");
        saved.current?.();
      } catch (cause) {
        // A conflict means the data moved on; read the latest revision.
        if (cause instanceof ApiError && cause.status === 409) void load();
        throw cause;
      }
    },
    [data, load, path, seasonId],
  );

  const lock = (clanTag: string | null | undefined): InfractionsLock => {
    const drawn =
      status?.pools.lazy.some(
        (clan) =>
          clan.tag === clanTag &&
          ["saved", "approved", "sent"].includes(clan.draw_state),
      ) ||
      data?.draws.some(
        (draw) =>
          draw.pool === "lazy" &&
          draw.clan_tag === clanTag &&
          draw.cycle === data.cycle &&
          !draw.cancelled_at,
      );
    if (drawn) return "draw";
    return !canManage || archived || (!!data && data.season_status !== "draft")
      ? "locked"
      : null;
  };

  return { data, state, load: () => void load(), save, lock };
}
