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
  expect(result.other).toBe(true);
});
it("flags otherwise unexplained changes but not a pure placement move", () => {
  const simple = {
    ...draft,
    preview: { ...draft.preview, accounts: [account("Ann", "B")] },
  } as PublicationDraft;
  expect(publicationChanges(simple, [account("Ann", "A")] as never).other).toBe(
    false,
  );
  expect(
    publicationChanges(
      { ...simple, preview: { ...simple.preview, accounts: [] } },
      [],
    ).other,
  ).toBe(true);
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
    expect(markup).toContain("members can&#x27;t see placements yet");
    expect(markup).toContain(label);
  }
});
it("placement wording is explicit before and after first publish", () => {
  expect(placementMessage("Assigned.", true)).toBe(
    "Assigned. · Draft only, not published",
  );
  expect(placementMessage("Assigned.", false)).toBe("Assigned. · Draft only");
});
