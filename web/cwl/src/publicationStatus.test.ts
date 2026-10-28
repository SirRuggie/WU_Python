import { expect, it } from "vitest";
import {
  capacityWarnings,
  finalizeStatus,
  publicationDate,
} from "./publicationStatus";
import type { PublicationDraft } from "./publication";
const draft = {
  published: null,
  last_publication: null,
  next_version: 1,
  draft_changed: false,
  preview: { accounts: [], clans: [] },
} as unknown as PublicationDraft;
it("distinguishes never published, current, changed and hidden with the shared short date", () => {
  const published = {
    version: 4,
    published_at: "2026-10-27T21:10:00Z",
  } as NonNullable<PublicationDraft["published"]>;
  expect(finalizeStatus(draft)).toBe(
    "Draft · members can't see placements yet",
  );
  expect(finalizeStatus({ ...draft, published })).toBe(
    `Members see roster version 4 · Published ${publicationDate(published.published_at)}`,
  );
  expect(
    finalizeStatus({ ...draft, published, draft_changed: true }),
  ).toContain("Members still see roster version 4");
  expect(
    finalizeStatus({
      ...draft,
      last_publication: { ...published, withdrawn_at: "later" },
    }),
  ).toBe(
    `Hidden from members · last published version 4 on ${publicationDate(published.published_at)}`,
  );
});
it("counts over-full clans and excess players across both pools, not all their players", () => {
  const preview = {
    accounts: ["A", "A", "A", "B", "B", "C", null].map((assigned_clan_tag) => ({
      assigned_clan_tag,
    })),
    clans: [
      { tag: "A", effective_capacity: 1 },
      { tag: "B", effective_capacity: 1 },
      { tag: "C", effective_capacity: 1 },
    ],
  } as PublicationDraft["preview"];
  expect(capacityWarnings({ ...draft, preview })).toEqual({
    clans: 2,
    players: 3,
  });
});
