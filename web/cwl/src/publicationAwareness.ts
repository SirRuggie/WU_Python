import type { PublicationDraft } from "./publication";
import type { RosterAccount } from "./roster";
export function placementMessage(message: string, published: boolean) {
  return `${message} · Draft only${published ? ", not published" : ""}`;
}
export function publicationReviewLabel(
  canPublish: boolean,
  canReview: boolean,
) {
  return canPublish && canReview
    ? "Review and publish →"
    : canReview
      ? "Review changes →"
      : null;
}
export type PublishedAccount = Partial<RosterAccount> & {
  tag: string;
  assigned_clan_name?: string | null;
};
export function publicationChanges(
  draft: PublicationDraft,
  published: PublishedAccount[],
) {
  const before = new Map(published.map((account) => [account.tag, account]));
  const current = new Map(
    draft.preview.accounts.map((account) => [account.tag, account]),
  );
  const clans = new Map(
    draft.preview.clans.map((clan) => [clan.tag, clan.name]),
  );
  const lines: { tag: string; name: string; text: string }[] = [];
  let other = false;
  const name = (tag: string | null | undefined, saved?: string | null) =>
    saved || (tag ? clans.get(tag) || tag : "Unassigned");
  const detailFields = [
    "user_id",
    "player_name",
    "town_hall",
    "signup_clan_tag",
    "signup_clan_name",
    "source_weight",
    "manual_weight",
    "effective_weight",
    "source_status",
    "source_checked_at",
    "source_modified_at",
    "kept",
  ] as const;
  for (const account of current.values()) {
    const old = before.get(account.tag);
    const changes: string[] = [];
    if (!old) changes.push(`added (${name(account.assigned_clan_tag)})`);
    else {
      if (old.assigned_clan_tag !== account.assigned_clan_tag)
        changes.push(
          `${name(old.assigned_clan_tag, old.assigned_clan_name)} → ${name(account.assigned_clan_tag)}`,
        );
      if (old.pool !== account.pool)
        changes.push(
          `${old.pool === "lazy" ? "Lazy" : "Main"} → ${account.pool === "lazy" ? "Lazy" : "Main"}`,
        );
      if (
        detailFields.some(
          (field) =>
            ((old as unknown as Record<string, unknown>)[field] ?? null) !==
            ((account as unknown as Record<string, unknown>)[field] ?? null),
        )
      )
        other = true;
    }
    if (changes.length)
      lines.push({
        tag: account.tag,
        name: account.player_name,
        text: changes.join(" · "),
      });
  }
  for (const old of before.values())
    if (!current.has(old.tag))
      lines.push({
        tag: old.tag,
        name: old.player_name || old.tag,
        text: "removed",
      });
  return { lines, other: draft.draft_changed && (other || lines.length === 0) };
}
