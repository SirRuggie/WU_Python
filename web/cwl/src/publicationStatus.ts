import type { PublicationDraft } from "./publication";

export function publicationDate(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function hiddenPublicationStatus(
  last: NonNullable<PublicationDraft["last_publication"]>,
): string {
  return `Hidden from members · last published version ${last.version} on ${publicationDate(last.published_at)}`;
}

export function finalizeStatus(draft: PublicationDraft): string {
  if (draft.published) {
    return `Members ${draft.draft_changed ? "still see" : "see"} roster version ${draft.published.version} · Published ${publicationDate(draft.published.published_at)}`;
  }
  if (draft.last_publication?.withdrawn_at) {
    return hiddenPublicationStatus(draft.last_publication);
  }
  return "Draft · members can't see placements yet";
}

export function capacityWarnings(draft: PublicationDraft) {
  const assigned = new Map<string, number>();
  for (const account of draft.preview.accounts) {
    if (account.assigned_clan_tag && !account.roster_filler)
      assigned.set(
        account.assigned_clan_tag,
        (assigned.get(account.assigned_clan_tag) || 0) + 1,
      );
  }
  const excess = draft.preview.clans.map((clan) =>
    Math.max(0, (assigned.get(clan.tag) || 0) - clan.effective_capacity),
  );
  return {
    clans: excess.filter((count) => count > 0).length,
    players: excess.reduce((sum, count) => sum + count, 0),
  };
}
