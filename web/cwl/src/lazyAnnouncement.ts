import { api } from "./api";
import type { PreviewPart } from "./DiscordPreview";

export type LazyAnnouncementScope = "all" | "one";
export type LazyAnnouncementClan = {
  tag: string;
  name: string;
  draw_state: string;
  ready: boolean;
};
export type LazyAnnouncementPreview = {
  cycle: string | null;
  scope: LazyAnnouncementScope;
  clan_tag: string | null;
  ping: boolean;
  clans: LazyAnnouncementClan[];
  blockers: string[];
  pages: PreviewPart[][];
  last_month_label: string | null;
  last_month_count: number;
  winner_count: number;
  clan_count: number;
  unlinked_count: number;
  fingerprint: string;
};
export type LazyAnnouncementResult = {
  status: "sent" | "failed" | "uncertain";
  failure: string | null;
  urls: string[];
  pages: number;
};

const url = (seasonId: string) =>
  `/seasons/${encodeURIComponent(seasonId)}/bonus-raffle/lazy-announcement`;

/** Read only. Stored winners and approved draws; it never calls Discord. */
export function loadLazyAnnouncement(
  seasonId: string,
  scope: LazyAnnouncementScope,
  clanTag: string,
  ping: boolean,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ scope, ping: ping ? "1" : "0" });
  if (scope === "one") query.set("clan_tag", clanTag);
  return api<LazyAnnouncementPreview>(
    `${url(seasonId)}?${query}`,
    "GET",
    undefined,
    {
      signal,
    },
  );
}

export function sendLazyAnnouncement(
  seasonId: string,
  preview: LazyAnnouncementPreview,
  channelId: string,
  requestId: string,
) {
  return api<LazyAnnouncementResult>(url(seasonId), "POST", {
    scope: preview.scope,
    clan_tag: preview.clan_tag,
    ping: preview.ping,
    channel_id: channelId,
    request_id: requestId,
    fingerprint: preview.fingerprint,
  });
}

/** 24 hex characters: one per Send, so a double tap or replay never posts twice. */
export function newRequestId() {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function readyCount(clans: { draw_state: string }[]) {
  return clans.filter(
    (c) => c.draw_state === "approved" || c.draw_state === "sent",
  ).length;
}
