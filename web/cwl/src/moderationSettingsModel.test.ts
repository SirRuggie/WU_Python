import { beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));

import { ApiError } from "./api";
import {
  changedSettings,
  cloneSettings,
  effectiveDestination,
  eventTypes,
  hasInvalidDestination,
  moderationRegistry,
  moderationSettingsError,
  normalizeRoleId,
  saveModerationSettings,
  type Destination,
  type SettingsResponse,
} from "./moderationSettingsModel";

const channels: Destination[] = [
  {
    id: "main",
    name: "logs",
    type: "text",
    can_post: true,
    requires_tag: false,
    can_manage_threads: false,
    available_tags: [],
  },
  {
    id: "members",
    name: "member-logs",
    type: "text",
    can_post: true,
    requires_tag: false,
    can_manage_threads: false,
    available_tags: [],
  },
  {
    id: "override",
    name: "join-logs",
    type: "text",
    can_post: true,
    requires_tag: false,
    can_manage_threads: false,
    available_tags: [],
  },
];
const settings: SettingsResponse = {
  schema_version: 2,
  revision: 7,
  main: { channel_id: "main", forum_tag_id: null },
  categories: {
    members: { mode: "main", channel_id: null, forum_tag_id: null },
    moderation: { mode: "main", channel_id: null, forum_tag_id: null },
    messages: { mode: "main", channel_id: null, forum_tag_id: null },
    invites: { mode: "main", channel_id: null, forum_tag_id: null },
  },
  events: {
    join: { enabled: true, channel_id: null, forum_tag_id: null },
    leave: { enabled: true, channel_id: null, forum_tag_id: null },
    kick: { enabled: true, channel_id: null, forum_tag_id: null },
    ban: { enabled: true, channel_id: null, forum_tag_id: null },
    member_update: { enabled: false, channel_id: null, forum_tag_id: null },
    timeout_add: { enabled: false, channel_id: null, forum_tag_id: null },
    timeout_remove: { enabled: false, channel_id: null, forum_tag_id: null },
    link: { enabled: false, channel_id: null, forum_tag_id: null },
    invite_create: { enabled: false, channel_id: null, forum_tag_id: null },
    invite_delete: { enabled: false, channel_id: null, forum_tag_id: null },
    invite_use: { enabled: false, channel_id: null, forum_tag_id: null },
  },
  ignores: { channel_ids: [], role_ids: [] },
  invite_names: {},
  channels_available: true,
  channels,
};

beforeEach(() => transport.mockReset());

it("saves the complete layered draft with the loaded revision", async () => {
  const draft = cloneSettings(settings);
  draft.categories.members.mode = "own";
  draft.categories.members.channel_id = "members";
  transport.mockResolvedValue({ ...settings, revision: 8, ...draft });
  await saveModerationSettings(settings, draft);
  expect(transport).toHaveBeenCalledWith(
    "/manage/member-events/settings",
    "PUT",
    {
      revision: 7,
      ...draft,
    },
  );
  expect(changedSettings(settings, draft)).toBe(true);
});

it("resolves event, category and main inheritance, with category off dominant", () => {
  const draft = cloneSettings(settings);
  expect(effectiveDestination(draft, "join")).toMatchObject({
    source: "main",
    target: { channel_id: "main" },
  });
  draft.categories.members = {
    mode: "own",
    channel_id: "members",
    forum_tag_id: null,
  };
  expect(effectiveDestination(draft, "join")).toMatchObject({
    source: "category",
    target: { channel_id: "members" },
  });
  draft.events.join.channel_id = "override";
  expect(effectiveDestination(draft, "join")).toMatchObject({
    source: "event",
    target: { channel_id: "override" },
  });
  draft.categories.members.mode = "off";
  expect(effectiveDestination(draft, "join")).toEqual({
    source: "off",
    target: null,
  });
  expect(effectiveDestination(draft, "kick")).toMatchObject({ source: "main" });
});

it("validates active destinations, posting rights, forum tags and inventory", () => {
  expect(hasInvalidDestination(settings, channels)).toBe(false);
  const forum: Destination = {
    id: "forum",
    name: "forum",
    type: "forum",
    can_post: true,
    requires_tag: true,
    can_manage_threads: false,
    available_tags: [{ id: "tag", name: "Moderated", moderated: true }],
  };
  const draft = cloneSettings(settings);
  draft.main.channel_id = "forum";
  expect(hasInvalidDestination(draft, [...channels, forum])).toBe(true);
  draft.main.forum_tag_id = "tag";
  expect(hasInvalidDestination(draft, [...channels, forum])).toBe(true);
  expect(
    hasInvalidDestination(draft, [
      ...channels,
      { ...forum, can_manage_threads: true },
    ]),
  ).toBe(false);
  expect(
    hasInvalidDestination(draft, [...channels, { ...forum, can_post: false }]),
  ).toBe(true);
  expect(hasInvalidDestination(draft, channels, false)).toBe(true);
  draft.categories.members.mode = "off";
  draft.categories.moderation.mode = "off";
  expect(hasInvalidDestination(draft, channels)).toBe(false);
});

it("accepts an authorized existing forum post and hides unsupported future events", () => {
  const post: Destination = {
    id: "post",
    name: "existing-post",
    type: "forum_post",
    can_post: true,
    requires_tag: false,
    can_manage_threads: false,
    available_tags: [],
  };
  const draft = cloneSettings(settings);
  draft.main.channel_id = "post";
  expect(hasInvalidDestination(draft, [post])).toBe(false);
  expect(eventTypes.map((event) => event.key)).toEqual([
    "join",
    "leave",
    "member_update",
    "kick",
    "ban",
    "timeout_add",
    "timeout_remove",
    "link",
    "invite_create",
    "invite_delete",
    "invite_use",
  ]);
  expect(
    moderationRegistry.map((category) => [
      category.key,
      category.events.map((event) => event.key),
    ]),
  ).toEqual([
    [
      "members",
      ["join", "leave", "member_update", "roles_added", "roles_removed"],
    ],
    ["moderation", ["kick", "ban", "unban", "timeout_add", "timeout_remove"]],
    ["messages", ["link", "delete", "edit", "bulk_delete"]],
    ["invites", ["invite_create", "invite_delete", "invite_use"]],
    [
      "server",
      [
        "channel_create",
        "channel_delete",
        "channel_change",
        "role_create",
        "role_delete",
        "role_change",
      ],
    ],
  ]);
  expect(
    moderationRegistry.flatMap((category) =>
      category.events.filter((event) => !event.supported),
    ),
  ).toHaveLength(12);
});

it("preserves edits on conflict and distinguishes uncertain test delivery", () => {
  expect(
    moderationSettingsError(new ApiError("Revision changed", 409), "save"),
  ).toMatchObject({ stale: true, denied: false });
  expect(
    moderationSettingsError(new ApiError("No access", 403), "save"),
  ).toMatchObject({ denied: true });
  expect(moderationSettingsError(null, "test").message).toContain(
    "Check Discord before trying again",
  );
});

it("round-trips ignores and invite names through clone and save", async () => {
  const draft = cloneSettings(settings);
  draft.ignores.channel_ids.push("123456789012345678");
  draft.ignores.role_ids.push("223456789012345678");
  draft.invite_names = { abc123: " Spring ad ", gone: "  ", vanity: "Site" };
  const copy = cloneSettings(draft);
  expect(copy.invite_names).toEqual({ abc123: "Spring ad", vanity: "Site" });
  expect(copy.ignores).not.toBe(draft.ignores);
  expect(changedSettings(settings, draft)).toBe(true);
  transport.mockResolvedValue({ ...settings, revision: 8 });
  await saveModerationSettings(settings, draft);
  const body = transport.mock.calls[0][2];
  expect(body.ignores).toEqual({
    channel_ids: ["123456789012345678"],
    role_ids: ["223456789012345678"],
  });
  expect(body.invite_names).toEqual({ abc123: "Spring ad", vanity: "Site" });
});

it("fills missing keys when an old response lacks the new fields", () => {
  const old = {
    ...settings,
    categories: {
      members: settings.categories.members,
      moderation: settings.categories.moderation,
    },
    events: {
      join: settings.events.join,
      leave: settings.events.leave,
      kick: settings.events.kick,
      ban: settings.events.ban,
    },
    ignores: {},
    invite_names: undefined,
  } as unknown as SettingsResponse;
  const copy = cloneSettings(old);
  expect(copy.ignores).toEqual({ channel_ids: [], role_ids: [] });
  expect(copy.invite_names).toEqual({});
  expect(copy.categories.invites).toEqual({
    mode: "main",
    channel_id: null,
    forum_tag_id: null,
  });
  expect(copy.events.invite_use).toEqual({
    enabled: false,
    channel_id: null,
    forum_tag_id: null,
  });
  expect(changedSettings(settings, old)).toBe(false);
  expect(effectiveDestination(copy, "link")).toMatchObject({ source: "main" });
  copy.categories.messages.mode = "off";
  expect(effectiveDestination(copy, "link")).toMatchObject({ source: "off" });
});

it("accepts only valid role ids for the ignore list", () => {
  expect(normalizeRoleId(" 123456789012345678 ")).toBe("123456789012345678");
  expect(normalizeRoleId("12345")).toBeNull();
  expect(normalizeRoleId("12345678901234567890123")).toBeNull();
  expect(normalizeRoleId("abc")).toBeNull();
});
