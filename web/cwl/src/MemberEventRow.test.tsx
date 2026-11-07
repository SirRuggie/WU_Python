import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import MemberEventRow, { type MemberEvent } from "./MemberEventRow";

const base: MemberEvent = {
  id: "1",
  user_id: "123456789012345678",
  event_type: "roles_added",
  display_name: "Ace",
  username: "ace",
  occurred_at: "2026-11-06T10:00:00Z",
};

function render(item: MemberEvent) {
  return renderToStaticMarkup(createElement(MemberEventRow, { item }));
}

it("shows role names on role rows", () => {
  const html = render({
    ...base,
    details: { roles: ["CWL player", "Member"] },
  });
  expect(html).toContain("CWL player, Member");
  expect(
    render({
      ...base,
      event_type: "roles_removed",
      details: { roles: ["Recruit"] },
    }),
  ).toContain("Recruit");
});

it("caps role names at five with a count", () => {
  const html = render({
    ...base,
    details: { roles: ["A", "B", "C", "D", "E", "F", "G"] },
  });
  expect(html).toContain("A, B, C, D, E +2 more");
  expect(html).not.toContain("F,");
});

it("shows no role line for other kinds or missing names", () => {
  expect(
    render({ ...base, event_type: "join", details: { roles: ["X"] } }),
  ).not.toContain("member-activity-roles");
  expect(render({ ...base, details: null })).not.toContain(
    "member-activity-roles",
  );
});
