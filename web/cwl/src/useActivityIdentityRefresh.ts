import { useEffect, useRef } from "react";
import { api, ApiError } from "./api";
import type { ActivityAccount } from "./strikeActivityView";
export type IdentitySnapshot = {
  accounts: ActivityAccount[];
  identity_warning?: string | null;
  identity_updating?: boolean;
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
}: {
  enabled: boolean;
  generation: number;
  busy: () => boolean;
  onResult: (result: IdentitySnapshot) => void;
  onDenied: () => void;
}) {
  const callbacks = useRef({ busy, onResult, onDenied });
  callbacks.current = { busy, onResult, onDenied };
  useEffect(() => {
    if (!enabled) return;
    let alive = true,
      attempts = 0,
      timer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 90_000;
    const schedule = () => {
      if (alive) timer = setTimeout(poll, 2000);
    };
    const poll = async () => {
      if (!alive || Date.now() >= deadline || attempts >= 6) return;
      if (document.hidden || callbacks.current.busy()) {
        schedule();
        return;
      }
      attempts++;
      try {
        const result = await api<IdentitySnapshot>(
          "/strikes/accounts?activity=true",
        );
        if (!alive || !Array.isArray(result.accounts)) return;
        callbacks.current.onResult(result);
        if (result.identity_updating) schedule();
      } catch (cause) {
        if (
          alive &&
          cause instanceof ApiError &&
          [401, 403].includes(cause.status)
        )
          callbacks.current.onDenied();
      }
    };
    schedule();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [enabled, generation]);
}
