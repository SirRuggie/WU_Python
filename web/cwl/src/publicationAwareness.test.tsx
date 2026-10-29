import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import PublicationAwarenessBanner from "./PublicationAwarenessBanner";
import { placementMessage, publicationChanges } from "./publicationAwareness";
import type { PublicationDraft } from "./publication";
const account = (
  tag: string,
  clan: string,
  pool = "main",
  weight = 170000,
) => ({
  tag,
  player_name: tag,
  pool,
  assigned_clan_tag: clan,
  effective_weight: weight,
});
const draft = {
  draft_changed: true,
  preview: {
    accounts: [
      account("Ann", "B"),
      account("Bob", "B"),
      account("Dee", "A", "lazy"),
      account("Weight", "A", "main", 160000),
    ],
    clans: [
      { tag: "A", name: "Clan A" },
      { tag: "B", name: "Clan B" },
    ],
  },
} as unknown as PublicationDraft;
it("lists moved, added, removed, pool and mixed weight changes", () => {
  const result = publicationChanges(draft, [
    account("Ann", "A"),
    account("Cal", "A"),
    account("Dee", "A"),
    account("Weight", "A"),
  ] as never);
  expect(result.lines.map((x) => x.text)).toEqual([
    "Clan A → Clan B",
    "added (Clan B)",
    "Main → Lazy",
    "removed",
  ]);
});
it("shows exact first-publish wording and permission based review actions", () => {
  for (const [publish, review, label] of [
    [true, true, "Review and publish →"],
    [false, true, "Review changes →"],
    [false, false, "Ask a staff member with publish access."],
  ] as const) {
    const markup = renderToStaticMarkup(
      <PublicationAwarenessBanner
        published={null}
        changed={false}
        canPublish={publish}
        onReview={review ? () => {} : undefined}
      />,
    );
    expect(markup).toContain("Draft · not published yet");
    expect(markup).toContain(label);
    if (review) expect(markup).toContain("Review ›");
  }
});
it("placement wording is explicit before and after first publish", () => {
  expect(placementMessage("Assigned.", true)).toBe(
    "Assigned. · Draft only, not published",
  );
  expect(placementMessage("Assigned.", false)).toBe("Assigned. · Draft only");
});

it("shows the Finalize hidden wording for a withdrawn publication", () => {
  const lastPublication = {
    version: 1,
    published_at: "2026-10-15T19:58:00Z",
    withdrawn_at: "2026-10-28T12:00:00Z",
    joining_instructions: "",
  };
  const html = renderToStaticMarkup(
    <PublicationAwarenessBanner
      published={null}
      lastPublication={lastPublication}
      changed
      canPublish
      onReview={() => {}}
    />,
  );
  expect(html).toContain("Hidden from members · v1 Oct 15");
  expect(html).not.toContain("Draft ·");
});
it("shows current published status and honest unpublished changes", () => {
  const published = {
    version: 3,
    published_at: "2026-10-28T12:00:00Z",
  } as PublicationDraft["published"];
  const current = renderToStaticMarkup(
    <PublicationAwarenessBanner
      published={published}
      changed={false}
      canPublish
      onReview={() => {}}
    />,
  );
  expect(current).toContain("Published · v3 · Oct 28 · Members can see it");
  expect(current).not.toContain("Review ›");
  const changed = renderToStaticMarkup(
    <PublicationAwarenessBanner
      published={published}
      changed
      canPublish
      onReview={() => {}}
    />,
  );
  expect(changed).toContain(
    "Members see v3 Oct 28 · Draft changes unpublished",
  );
  expect(changed).toContain("Review ›");
});
