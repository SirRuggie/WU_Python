import { expect, it } from "vitest";
import { rosterMemberKey } from "./rosterGrouping";
import type { RosterAccount } from "./roster";
it("groups by exact Discord ID and keeps unrelated unlinked accounts separate", () => {
  const a = (tag: string, user_id: string) =>
    ({ tag, user_id }) as RosterAccount;
  expect(rosterMemberKey(a("#A", "111"))).toBe(rosterMemberKey(a("#B", "111")));
  expect(rosterMemberKey(a("#A", "111"))).not.toBe(
    rosterMemberKey(a("#B", "112")),
  );
  expect(rosterMemberKey(a("#A", ""))).not.toBe(rosterMemberKey(a("#B", "")));
});
