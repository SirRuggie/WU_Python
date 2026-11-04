import { useEffect, useRef } from "react";
import { api, ApiError } from "./api";
import type { ActivityAccount } from "./strikeActivityView";
export type IdentitySnapshot = {
  accounts: ActivityAccount[];
  identity_warning?: string | null;
  identity_updating?: boolean;
  activity_updating?: boolean;
  activity_checked_at?: string | null;
  activity_as_of?: string | null;
  activity_warning?: string | null;
  history_warning?: string | null;
  weight_warning?: string | null;
  clans?: { tag: string; name: string }[];
};
export function mergeIdentityAccounts(
  current: ActivityAccount[],
  incoming: ActivityAccount[],
) {
  const indexed = new Map(incoming.map((row) => [row.player_tag, row]));
  return current.map((row) => {
    const live = indexed.get(row.player_tag);
    return live
      ? { ...row, discord_id: live.discord_id, discord_name: live.discord_name }
      : row;
  });
}
export default function useActivityIdentityRefresh({
  enabled,
  generation,
  busy,
  onResult,
  onDenied,
  readVersion = () => 0,
}: {
  enabled: boolean;
  generation: number;
  busy: () => boolean;
  onResult: (result: IdentitySnapshot) => void;
  onDenied: () => void;
  readVersion?: () => string | number;
}) {
  const callbacks = useRef({ busy, onResult, onDenied, readVersion });
  callbacks.current = { busy, onResult, onDenied, readVersion };
  useEffect(() => {
    if (!enabled) return;
    let alive = true,
      attempts = 0,
      timer: ReturnType<typeof setTimeout>;
    const schedule = (delay = 2000) => {
      if (alive) timer = setTimeout(poll, delay);
    };
    const poll = async () => {
      if (!alive) return;
      if (document.hidden || callbacks.current.busy()) {
        schedule();
        return;
      }
      attempts++;
      const version = callbacks.current.readVersion();
      try {
        const result = await api<IdentitySnapshot>(
          "/strikes/accounts?activity=true",
        );
        if (!alive || !Array.isArray(result.accounts)) return;
        if (callbacks.current.busy() || version !== callbacks.current.readVersion()) {
          schedule();
          return;
        }
        callbacks.current.onResult(result);
        if (result.identity_updating || result.identity_warning || result.activity_updating) {
          schedule((result.identity_updating || result.activity_updating) && attempts < 6 ? 2000 : 120_000);
          if (attempts >= 6) attempts = 0;
        }
      } catch (cause) {
        if (
          alive &&
          cause instanceof ApiError &&
          [401, 403].includes(cause.status)
        )
          callbacks.current.onDenied();
        else if (alive) schedule(120_000);
      }
    };
    schedule();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [enabled, generation]);
}
