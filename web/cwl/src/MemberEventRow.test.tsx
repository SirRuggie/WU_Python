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

it("shows what changed on profile rows, three at most", () => {
  const change = (
    field: string,
    before: string | null,
    after: string | null,
  ) => ({
    field,
    before,
    after,
  });
  const html = render({
    ...base,
    event_type: "member_update",
    details: {
      changes: [
        change("nickname", "A", "B"),
        change("username", "ace", "ace2"),
        change("avatar", null, null),
        change("global_name", "G", "H"),
        change("discriminator", "1", "2"),
      ],
    },
  });
  expect(html).toContain("Nickname: A → B");
  expect(html).toContain("Username: ace → ace2");
  expect(html).toContain("Avatar: changed");
  expect(html).toContain("+2 more");
  expect(html).not.toContain("Display name");
  expect(
    render({ ...base, event_type: "member_update", details: null }),
  ).not.toContain("→");
});

it("shows the invite name or code and omits the line when missing", () => {
  const invite = { ...base, event_type: "invite_use" };
  expect(
    render({ ...invite, details: { name: "Reddit", code: "abc" } }),
  ).toContain("via Reddit");
  expect(render({ ...invite, details: { name: null, code: "abc" } })).toContain(
    "via abc",
  );
  expect(render({ ...invite, details: {} })).not.toContain("via ");
});

it("shows timeout duration and expiry and omits missing parts", () => {
  const timeout = { ...base, event_type: "timeout_add" };
  const html = render({
    ...timeout,
    details: { duration_seconds: 3600, until: "2026-11-06T11:00:00Z" },
  });
  expect(html).toContain("For 1 hour · until ");
  expect(
    render({ ...timeout, details: { duration_seconds: 604800 } }),
  ).toContain("For 7 days");
  expect(render({ ...timeout, details: {} })).not.toContain("For ");
});

it("renders the moderator and the quoted reason on separate lines", () => {
  const html = render({
    ...base,
    event_type: "kick",
    reason: "Spam",
    moderator_id: null,
  });
  expect(html).toContain(
    '<p class="member-activity-by">by an unknown moderator</p>',
  );
  expect(html).toContain('<p class="member-activity-reason">“Spam”</p>');
  expect(html).not.toContain("· “");
});

it("puts the moderator block and the detail line in one body, in order", () => {
  const html = render({
    ...base,
    event_type: "timeout_add",
    reason: "Cool off",
    moderator_id: null,
    details: { duration_seconds: 3600 },
  });
  const body = html.indexOf('class="member-activity-body"');
  const moderation = html.indexOf('class="member-activity-moderation"');
  const detail = html.indexOf('class="member-activity-roles"');
  expect(body).toBeGreaterThan(-1);
  expect(moderation).toBeGreaterThan(body);
  expect(detail).toBeGreaterThan(moderation);
  expect(html.match(/member-activity-body/g)).toHaveLength(1);
  expect(html.indexOf("member-activity-meta")).toBeGreaterThan(detail);
  expect(render({ ...base, event_type: "join", details: null })).not.toContain(
    "member-activity-body",
  );
});
