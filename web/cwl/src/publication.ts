import type { Pool } from "./api";
import type { RosterAccount, RosterClan } from "./roster";
export type PublicationMeta = {
  version: number;
  revision: number;
  published_at: string;
  published_by: string;
  joining_instructions: string;
  assigned_count: number;
  unassigned_count: number;
};
export type PublicationPreview = {
  accounts: RosterAccount[];
  clans: RosterClan[];
  assigned_count: number;
  unassigned_count: number;
};
export type PublicationDraft = {
  draft_revision: number;
  draft_changed: boolean;
  preview: PublicationPreview;
  published: PublicationMeta | null;
  last_publication: {
    version: number;
    published_at: string;
    withdrawn_at: string | null;
    joining_instructions: string;
  } | null;
  next_version: number;
};
export type MemberAssignment = {
  current_clan_tag?: string | null;
  current_clan_name?: string | null;
  current_clan_checked_at?: string;
  current_clan_status?: string;
  arrival_status?: "arrived" | "missing" | "unknown" | "unassigned";
  tag: string;
  player_name: string;
  town_hall: number | null;
  pool: Pool;
  assigned_clan_tag: string | null;
  assigned_clan_name: string | null;
};
export type MemberPublicationMeta = Pick<
  PublicationMeta,
  "version" | "published_at" | "joining_instructions"
>;
export type MyAssignments = {
  published: MemberPublicationMeta | null;
  accounts: MemberAssignment[];
  visibility: "current";
  draft_changed: boolean;
};
export function clanDeepLink(tag: string): string {
  return `https://link.clashofclans.com/en?action=OpenClanProfile&tag=${encodeURIComponent(tag)}`;
}
export function draftPublicationStatus(
  draft: PublicationDraft,
): "unpublished" | "current" | "changed" {
  if (!draft.published) return "unpublished";
  return draft.draft_changed ? "changed" : "current";
}

export function memberPlacementStatus(
  assignments: MyAssignments,
): "provisional" | "official" {
  return assignments.published && !assignments.draft_changed
    ? "official"
    : "provisional";
}
