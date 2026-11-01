import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { DiscordProfile } from "./DiscordIdentity";
/** One bounded batch per page, never an identity request from each row. */
export default function useDiscordIdentities(
  ids: (string | null | undefined)[],
  enabled = true,
  endpoint = "/staff-signup-members",
) {
  const signature = [
    ...new Set(
      ids.filter((id): id is string => !!id && /^[1-9][0-9]{14,21}$/.test(id)),
    ),
  ]
    .sort()
    .slice(0, 1000)
    .join(",");
  const [members, setMembers] = useState<Record<string, DiscordProfile>>({});
  const [loading, setLoading] = useState(false);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setMembers({});
    setDenied(false);
    setLoading(enabled && !!signature);
    if (!enabled || !signature) return;
    const values = signature.split(","),
      chunks: string[][] = [];
    for (let i = 0; i < values.length; i += 100)
      chunks.push(values.slice(i, i + 100));
    void Promise.all(
      chunks.map((chunk) =>
        api<{ options: DiscordProfile[] }>(
          `${endpoint}?ids=${encodeURIComponent(chunk.join(","))}`,
          "GET",
          undefined,
          { signal: controller.signal },
        ),
      ),
    )
      .then((pages) => {
        if (active)
          setMembers(
            Object.fromEntries(
              pages.flatMap((page) =>
                page.options
                  .filter((member) => values.includes(member.id))
                  .map((member) => [member.id, member]),
              ),
            ),
          );
      })
      .catch((error) => {
        if (
          active &&
          error instanceof ApiError &&
          [401, 403].includes(error.status)
        )
          setDenied(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [signature, enabled, endpoint]);
  return { members, loading, denied };
}
