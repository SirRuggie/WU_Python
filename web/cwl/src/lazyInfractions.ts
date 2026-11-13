import { api } from "./api";
import type { PreviewPart } from "./DiscordPreview";

export type LazyInfractionPlayer = {
  tag: string;
  player_name: string;
  town_hall: number | null;
  /** Labels in a fixed order: saved flags, then "Did not join". */
  infractions: string[];
};
export type LazyInfractionException = LazyInfractionPlayer & {
  clan_name: string;
  reason: string;
};
export type LazyInfractionsPreview = {
  cycle: string | null;
  label: string;
  clans: { tag: string; name: string; players: LazyInfractionPlayer[] }[];
  /** Players with a saved staff reason: listed here, never in the post. */
  exceptions: LazyInfractionException[];
  blockers: string[];
  pages: PreviewPart[][];
  player_count: number;
  clan_count: number;
  fingerprint: string;
};
export type LazyInfractionsResult = {
  status: "sent" | "failed" | "uncertain";
  failure: string | null;
  urls: string[];
  pages: number;
};

const url = (seasonId: string) =>
  `/seasons/${encodeURIComponent(seasonId)}/bonus-raffle/lazy-infractions`;

/** Read only. Stored results and saved reviews; it never calls Discord. */
export function loadLazyInfractions(seasonId: string, signal?: AbortSignal) {
  return api<LazyInfractionsPreview>(url(seasonId), "GET", undefined, {
    signal,
  });
}

/** Posts with no mentions. One request ID per Send, so a replay never posts twice. */
export function sendLazyInfractions(
  seasonId: string,
  preview: LazyInfractionsPreview,
  channelId: string,
  requestId: string,
) {
  return api<LazyInfractionsResult>(url(seasonId), "POST", {
    channel_id: channelId,
    request_id: requestId,
    fingerprint: preview.fingerprint,
  });
}
