// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  moderationRegistry,
  eventTypes,
  type SettingsResponse,
} from "./moderationSettingsModel";
import { moderationRoutingSummary } from "./ModerationCategoryCard";
import { openPicker, optionTexts, pickOption } from "./searchPickerTestUtils";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./ModerationDestinationPicker", () => ({
  default: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: { channel_id: string | null };
    onChange: (value: {
      channel_id: string | null;
      forum_tag_id: null;
    }) => void;
  }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value.channel_id || ""}
        onChange={(event) =>
          onChange({
            channel_id: event.target.value || null,
            forum_tag_id: null,
          })
        }
      >
        <option value="">None</option>
        <option value="main">Main</option>
        <option value="other">Other</option>
        <option value="forum">Forum</option>
      </select>
    </label>
  ),
}));
vi.mock("./ConfirmDialog", () => ({
  default: ({
    heading,
    text,
    confirmLabel,
    onConfirm,
    onCancel,
  }: {
    heading: string;
    text: string;
    confirmLabel: string;
    onConfirm: () => void;
    onCancel: () => void;
  }) => (
    <div role="dialog" aria-label={heading}>
      <p>{text}</p>
      <button onClick={onCancel}>Cancel</button>
      <button onClick={onConfirm}>{confirmLabel}</button>
    </div>
  ),
}));
import ModerationSettings from "./ModerationSettings";
import { ApiError } from "./api";
const fixture: SettingsResponse = {
  schema_version: 2,
  revision: 4,
  main: { channel_id: "main", forum_tag_id: null },
  categories: {
    members: { mode: "main", channel_id: null, forum_tag_id: null },
    moderation: { mode: "main", channel_id: null, forum_tag_id: null },
    roles: { mode: "main", channel_id: null, forum_tag_id: null },
    messages: { mode: "main", channel_id: null, forum_tag_id: null },
    channels: { mode: "main", channel_id: null, forum_tag_id: null },
    server: { mode: "main", channel_id: null, forum_tag_id: null },
    invites: { mode: "main", channel_id: null, forum_tag_id: null },
  },
  events: Object.fromEntries(
    [
      "join",
      "leave",
      "kick",
      "ban",
      "member_update",
      "timeout_add",
      "timeout_remove",
      "link",
      "invite_create",
      "invite_delete",
      "invite_use",
      "unban",
      "role_create",
      "role_update",
      "role_delete",
      "roles_added",
      "roles_removed",
      "message_delete",
      "message_edit",
      "message_bulk_delete",
      "channel_create",
      "channel_update",
      "channel_delete",
      "channel_permissions",
      "thread_delete",
      "thread_lock",
      "server_update",
      "emoji",
      "sticker",
      "app",
      "webhook",
      "automod",
    ].map((key) => [
      key,
      { enabled: true, channel_id: null, forum_tag_id: null },
    ]),
  ) as SettingsResponse["events"],
  ignores: { channel_ids: [], role_ids: [] },
  invite_names: {},
  channels_available: true,
  roles_available: true,
  roles: [
    {
      id: "100000000000000001",
      name: "Mods",
      color: 255,
      position: 3,
      managed: false,
    },
    {
      id: "100000000000000002",
      name: "Guests",
      color: 0,
      position: 1,
      managed: false,
    },
  ],
  channels: ["main", "other", "forum"].map((id) => ({
    id,
    name: id + "-logs",
    type: id === "forum" ? ("forum" as const) : ("text" as const),
    can_post: true,
    requires_tag: false,
    can_manage_threads: true,
    available_tags: [],
  })),
  preview_cards: {
    kick: {
      flags: 32768,
      components: [
        {
          type: 17,
          accent_color: 15112501,
          components: [{ type: 10, content: "### 👢 Member kicked" }],
        },
      ],
    },
  },
  forum_preview_cards: {
    kick: { embeds: [{ description: "Forum kick card", color: 15112501 }] },
  },
};
const invites = vi.hoisted(() => vi.fn());
const health = vi.hoisted(() => vi.fn());
let root: Root, host: HTMLDivElement;
const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  )!;
const settle = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  transport.mockReset();
  invites.mockReset();
  health.mockReset();
  health.mockResolvedValue({ items: [], backlog: 0, last_sent_at: null });
  invites.mockResolvedValue({
    invites: [
      {
        code: "abc123",
        name: null,
        inviter_id: "1",
        inviter_name: "Alice",
        channel_id: "9",
        channel_name: "welcome",
        uses: 3,
        max_uses: 10,
        expires_at: null,
        vanity: false,
      },
      {
        code: "wu",
        name: "Site",
        inviter_id: null,
        inviter_name: null,
        channel_id: null,
        channel_name: null,
        uses: 40,
        max_uses: null,
        expires_at: null,
        vanity: true,
      },
    ],
    updated_at: null,
  });
  transport.mockImplementation(
    async (path: string, method?: string, body?: SettingsResponse) => {
      // The PUT echoes the saved body with the next revision, like the backend.
      if (path === "/manage/member-events/settings" && method === "PUT")
        return { ...fixture, ...body, revision: body!.revision + 1 };
      if (path === "/manage/member-events/settings")
        return structuredClone(fixture);
      if (path === "/manage/member-events/test") return { sent: true };
      if (path === "/manage/member-events/health") return health();
      if (path === "/manage/member-events/invites") return invites();
      throw new Error(`Unexpected ${path}`);
    },
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("requires explicit save for an event override and supports discard", async () => {
  await openEvent("join");
  const override = host.querySelector<HTMLSelectElement>(
    '[aria-label="Joins channel override"]',
  )!;
  await act(async () => {
    override.value = "other";
    override.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("Posts to #other-logs");
  expect(button("Send test").hasAttribute("disabled")).toBe(true);
  expect(transport.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(
    0,
  );
  await act(async () => button("Discard").click());
  expect(host.textContent).toContain("Posts to #main-logs");
  expect(host.textContent).not.toContain("Unsaved changes");
  expect(transport.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(
    0,
  );
});
it("renders the payload preview and confirms a test without saving", async () => {
  await openEvent("kick");
  const kick = [...host.querySelectorAll(".moderation-event-row")].find((row) =>
    row.textContent?.includes("Kicks"),
  )!;
  await act(async () =>
    [...kick.querySelectorAll("button")]
      .find((item) => item.textContent === "Preview")!
      .click(),
  );
  expect(kick.textContent).toContain("Member kicked");
  await act(async () =>
    [...kick.querySelectorAll("button")]
      .find((item) => item.textContent === "Send test")!
      .click(),
  );
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain(
    "#main-logs",
  );
  expect(
    transport.mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(0);
  await act(async () => button("Send one test").click());
  expect(transport).toHaveBeenCalledWith("/manage/member-events/test", "POST", {
    event_type: "kick",
    revision: 4,
  });
  expect(transport.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(
    0,
  );
});
it("renders every supported event control and no placeholders", () => {
  expect(host.textContent).not.toContain("Nickname changes");
  expect(host.textContent).toContain("Roles added");
  expect(host.textContent).toContain("Channels created");
  expect(host.textContent).toContain("AutoMod rules");
  expect(host.querySelectorAll(".moderation-event-row")).toHaveLength(32);
});
it("puts the shared message ignores in Not logged after routing", () => {
  const card = [...host.querySelectorAll(".moderation-category-card")].find(
    (el) => el.querySelector("h3")?.textContent?.includes("Messages"),
  )!;
  const rows = card.querySelectorAll(".moderation-event-row");
  expect(rows).toHaveLength(4);
  const notLogged = host.querySelector(".moderation-not-logged")!;
  const note = notLogged.querySelector(".moderation-ignore-note")!;
  expect(note.textContent).toBe("Applies to all message logs.");
  expect(
    rows[3].compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    note.compareDocumentPosition(
      notLogged.querySelector(".moderation-ignore-lists")!,
    ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
it("saves new keys and categories in the payload", async () => {
  await act(async () =>
    host
      .querySelector<HTMLInputElement>('[aria-label="Emoji logging"]')!
      .click(),
  );
  await settle();
  const body = transport.mock.calls.find((call) => call[1] === "PUT")?.[2];
  expect(body.events.emoji.enabled).toBe(false);
  expect(Object.keys(body.events)).toHaveLength(32);
  expect(Object.keys(body.categories)).toHaveLength(7);
});
it("renders nothing for an empty health list", () => {
  expect(host.querySelector(".moderation-health")).toBeNull();
});
it("shows health items with error and warning styling", async () => {
  health.mockResolvedValue({
    items: [
      { key: "audit", level: "error", text: "View Audit Log needed" },
      { key: "backlog", level: "warning", text: "30 waiting" },
    ],
    backlog: 30,
    last_sent_at: null,
  });
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
  const items = [...host.querySelectorAll(".moderation-health li")];
  expect(items.map((item) => item.textContent)).toEqual([
    "⛔View Audit Log needed",
    "⚠️30 waiting",
  ]);
  expect(items[0].classList.contains("is-error")).toBe(true);
  expect(items[1].classList.contains("is-warning")).toBe(true);
});
it("renders no health line and keeps the form when the health read fails", async () => {
  health.mockRejectedValue(new Error("down"));
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
  expect(host.querySelector(".moderation-health")).toBeNull();
  expect(host.querySelector(".load-error")).toBeNull();
  expect(host.textContent).toContain("Main log channel");
});

it("uses accessible track-and-thumb switches for categories and events", () => {
  const categorySwitch = host.querySelector<HTMLInputElement>(
    '[aria-label="Members logging"]',
  )!;
  const joinSwitch = host.querySelector<HTMLInputElement>(
    '[aria-label="Joins logging"]',
  )!;
  expect(categorySwitch.getAttribute("role")).toBe("switch");
  expect(
    categorySwitch.nextElementSibling?.classList.contains(
      "moderation-category-track",
    ),
  ).toBe(true);
  expect(joinSwitch.getAttribute("role")).toBe("switch");
  expect(
    joinSwitch.nextElementSibling?.classList.contains(
      "moderation-event-pill-track",
    ),
  ).toBe(true);
});

it("keeps unsaved edits after a revision conflict", async () => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      throw new ApiError("Revision changed", 409);
    return structuredClone(fixture);
  });
  await pick(host.querySelector(".moderation-ignore-group")!, "#other-logs");
  await act(async () => button("Save changes").click());
  expect(host.textContent).toContain("#other-logs");
  expect(host.textContent).toContain("Your edits are preserved");
  expect(host.textContent).toContain("Unsaved changes");
});

const puts = () => transport.mock.calls.filter((call) => call[1] === "PUT");
const eventSwitch = (label: string) =>
  host.querySelector<HTMLInputElement>(`[aria-label="${label} logging"]`)!;

it("saves a switch at once with the saved revision and no Save step", async () => {
  expect(host.querySelector(".moderation-settings-save")).toBeNull();
  await act(async () => eventSwitch("Joins").click());
  await settle();
  expect(puts()).toHaveLength(1);
  expect(puts()[0][2]).toMatchObject({
    revision: 4,
    events: { join: { enabled: false }, leave: { enabled: true } },
  });
  expect(eventSwitch("Joins").checked).toBe(false);
  const row = host.querySelector('[data-event="join"]')!;
  expect(row.querySelector(".moderation-switch-feedback")?.textContent).toBe(
    "Saved",
  );
  expect(host.querySelector(".moderation-settings-save")).toBeNull();
  // The next switch uses the new revision from the response.
  await act(async () => eventSwitch("Leaves").click());
  await settle();
  expect(puts()[1][2]).toMatchObject({
    revision: 5,
    events: { leave: { enabled: false } },
  });
});

it("saves a category switch at once", async () => {
  await act(async () => eventSwitch("Members").click());
  await settle();
  expect(puts()).toHaveLength(1);
  expect(puts()[0][2].categories.members.mode).toBe("off");
  const card = host.querySelector(".moderation-category-card")!;
  expect(card.querySelector(".moderation-switch-feedback")?.textContent).toBe(
    "Saved",
  );
});

it("keeps other unsaved edits out of a switch save and in the draft", async () => {
  await pick(host.querySelector(".moderation-ignore-group")!, "#other-logs");
  expect(host.textContent).toContain("Unsaved changes");
  await act(async () => eventSwitch("Joins").click());
  await settle();
  expect(puts()).toHaveLength(1);
  expect(puts()[0][2].ignores.channel_ids).toEqual([]);
  expect(puts()[0][2].events.join.enabled).toBe(false);
  expect(host.textContent).toContain("#other-logs");
  expect(host.textContent).toContain("Unsaved changes");
  expect(eventSwitch("Joins").checked).toBe(false);
  await act(async () => button("Save changes").click());
  expect(puts()[1][2]).toMatchObject({
    revision: 5,
    ignores: { channel_ids: ["other"] },
    events: { join: { enabled: false } },
  });
});

it("blocks a second switch while one is saving", async () => {
  let release: (value: unknown) => void = () => {};
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      return new Promise((resolve) => {
        release = () =>
          resolve({
            ...fixture,
            events: {
              ...fixture.events,
              join: { ...fixture.events.join, enabled: false },
            },
            revision: 5,
          });
      });
    if (path === "/manage/member-events/settings")
      return structuredClone(fixture);
    if (path === "/manage/member-events/invites") return invites();
    return health();
  });
  await act(async () => eventSwitch("Joins").click());
  expect(eventSwitch("Joins").disabled).toBe(true);
  expect(eventSwitch("Leaves").disabled).toBe(true);
  expect(
    host.querySelector('[data-event="join"] .moderation-switch-feedback')
      ?.textContent,
  ).toBe("Saving…");
  await act(async () => eventSwitch("Joins").click());
  await act(async () => eventSwitch("Leaves").click());
  expect(puts()).toHaveLength(1);
  await act(async () => release(null));
  await settle();
  expect(eventSwitch("Joins").disabled).toBe(false);
  expect(eventSwitch("Joins").checked).toBe(false);
});

it("reverts a switch after a revision conflict and offers refresh", async () => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      throw new ApiError("Revision changed", 409);
    if (path === "/manage/member-events/invites") return invites();
    if (path === "/manage/member-events/health") return health();
    return structuredClone(fixture);
  });
  await act(async () => eventSwitch("Joins").click());
  await settle();
  expect(eventSwitch("Joins").checked).toBe(true);
  const feedback = host.querySelector(
    '[data-event="join"] .moderation-switch-feedback',
  )!;
  expect(feedback.getAttribute("role")).toBe("alert");
  expect(feedback.textContent).toContain("changed since you loaded them");
  expect(feedback.textContent).toContain("Refresh settings");
  expect(host.textContent).not.toContain("Unsaved changes");
});

it("reverts a switch after a network failure", async () => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      throw new Error("Network down");
    if (path === "/manage/member-events/invites") return invites();
    if (path === "/manage/member-events/health") return health();
    return structuredClone(fixture);
  });
  await act(async () => eventSwitch("Members").click());
  await settle();
  expect(eventSwitch("Members").checked).toBe(true);
  expect(host.textContent).toContain("Network down");
  expect(host.textContent).not.toContain("Unsaved changes");
});

it("clears settings when a switch save is denied", async () => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      throw new ApiError("Forbidden", 403);
    if (path === "/manage/member-events/invites") return invites();
    if (path === "/manage/member-events/health") return health();
    return structuredClone(fixture);
  });
  await act(async () => eventSwitch("Joins").click());
  await settle();
  expect(host.querySelector('[aria-label="Joins logging"]')).toBeNull();
  expect(host.textContent).toContain("Your staff access has changed");
});

it("keeps a switch in the draft when it needs a channel first", async () => {
  await remount({
    main: { channel_id: null, forum_tag_id: null },
    events: {
      ...structuredClone(fixture.events),
      join: { enabled: false, channel_id: null, forum_tag_id: null },
    },
  });
  await act(async () => eventSwitch("Joins").click());
  await settle();
  expect(puts()).toHaveLength(0);
  expect(eventSwitch("Joins").checked).toBe(true);
  const row = host.querySelector('[data-event="join"]')!;
  expect(row.querySelector(".moderation-switch-feedback")?.textContent).toBe(
    "Not saved. Select a channel, then select Save changes.",
  );
  expect(row.querySelector(".moderation-event-editor")).not.toBeNull();
  expect(host.textContent).toContain("Unsaved changes");
});

it("keeps a switch in the draft when its own event has unsaved edits", async () => {
  await openEvent("join");
  await change(
    host.querySelector<HTMLSelectElement>(
      '[aria-label="Joins channel override"]',
    )!,
    "other",
  );
  await act(async () => eventSwitch("Joins").click());
  await settle();
  expect(puts()).toHaveLength(0);
  expect(
    host.querySelector('[data-event="join"] .moderation-switch-feedback')
      ?.textContent,
  ).toBe("Not saved. Select Save changes to apply.");
  await act(async () => button("Save changes").click());
  expect(puts()[0][2].events.join).toMatchObject({
    enabled: false,
    channel_id: "other",
  });
});

it("restores the last active mode despite a retained own channel", async () => {
  await openCategory("members");
  const card = host.querySelector(".moderation-category-card")!;
  const mode = card.querySelector<HTMLSelectElement>(
    ".moderation-category-routing select",
  )!;
  const change = async (select: HTMLSelectElement, value: string) => {
    await act(async () => {
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
  };
  await change(mode, "own");
  await change(
    card.querySelector<HTMLSelectElement>('[aria-label="Members channel"]')!,
    "other",
  );
  const toggle = card.querySelector<HTMLInputElement>(
    '[aria-label="Members logging"]',
  )!;
  await act(async () => toggle.click());
  await act(async () => toggle.click());
  expect(mode.value).toBe("own");
  await change(mode, "main");
  await act(async () => toggle.click());
  await act(async () => toggle.click());
  expect(mode.value).toBe("main");
  expect(card.textContent).toContain("Posts to #main-logs");
  await change(mode, "own");
  expect(
    card.querySelector<HTMLSelectElement>('[aria-label="Members channel"]')!
      .value,
  ).toBe("other");
  await act(async () => button("Discard").click());
  await act(async () => toggle.click());
  await act(async () => toggle.click());
  expect(mode.value).toBe("main");
});
it("shows the missing effective channel without changing enabled settings", async () => {
  transport.mockImplementation(async () => ({
    ...structuredClone(fixture),
    main: { channel_id: null, forum_tag_id: null },
  }));
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
  const card = [...host.querySelectorAll(".moderation-category-card")].find(
    (el) => el.textContent?.includes("Kicks"),
  )!;
  expect(card.querySelector(".moderation-category-switch")?.textContent).toBe(
    "On",
  );
  expect(
    card.querySelector(".moderation-category-title small")?.textContent,
  ).toBe("Not posting");
  expect(card.querySelectorAll(".moderation-event-row")).toHaveLength(5);
  for (const row of card.querySelectorAll(".moderation-event-row")) {
    expect(row.querySelector(".moderation-event-status")?.textContent).toBe(
      "Not posting",
    );
    await openEvent(row.getAttribute("data-event")!);
    const test = [...row.querySelectorAll("button")].find(
      (b) => b.textContent === "Send test",
    )!;
    expect(test.disabled).toBe(true);
    expect(test.title).toBe("Select a channel first");
    expect(row.textContent).toContain("Select a channel first");
  }
  expect(
    card.querySelector<HTMLInputElement>('[aria-label="Moderation logging"]')
      ?.checked,
  ).toBe(true);
  expect(
    transport.mock.calls.filter(([, method]) => method === "PUT"),
  ).toHaveLength(0);
});

const change = async (element: HTMLElement, value: string) => {
  const select = element instanceof HTMLSelectElement;
  const proto = select
    ? HTMLSelectElement.prototype
    : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(element, value);
    element.dispatchEvent(
      new Event(select ? "change" : "input", { bubbles: true }),
    );
  });
};
const pick = async (scope: Element, text: string) => {
  await act(async () =>
    scope.querySelector<HTMLButtonElement>(".search-picker-trigger")!.click(),
  );
  const option = [
    ...scope.querySelectorAll<HTMLElement>('[role="option"]'),
  ].find((item) => item.textContent?.includes(text))!;
  await act(async () => option.click());
};
it("renders all seven categories", () => {
  const titles = [...host.querySelectorAll(".moderation-category-name")].map(
    (item) => item.textContent?.trim(),
  );
  expect(titles).toEqual([
    "👥 Members",
    "🛡️ Moderation",
    "🏷️ Roles",
    "💬 Messages",
    "📚 Channels",
    "🏰 Server",
    "📨 Invites",
  ]);
  expect(host.textContent).toContain("Profile changes");
  expect(host.textContent).toContain("Timeout removals");
  expect(host.textContent).toContain("Invite uses");
});
it("saves link ignores with the draft and flags them as unsaved", async () => {
  await pick(host.querySelector(".moderation-ignore-group")!, "#other-logs");
  expect(host.textContent).toContain("#other-logs");
  expect(host.textContent).toContain("Unsaved changes");
  await pickOption(
    ignoredRoles().querySelector<HTMLElement>(".search-picker")!,
    "Guests",
  );
  expect(host.textContent).toContain("@Guests");
  expect(host.textContent).not.toContain("100000000000000002");
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2],
  ).toMatchObject({
    ignores: { channel_ids: ["other"], role_ids: ["100000000000000002"] },
  });
});
// Re-render the same instance on another tab; the draft is shared.
const showView = async (view: "channels" | "invites") => {
  await act(async () => root.render(<ModerationSettings view={view} />));
  await settle();
};
it("lists invites with uses and saves edited names; clearing removes", async () => {
  await showView("invites");
  expect(host.textContent).toContain("3 / 10 uses");
  expect(host.textContent).toContain("40 uses");
  expect(
    host.querySelector('a[href="https://discord.gg/wu"]')?.textContent,
  ).toBe("discord.gg/wu");
  await openInvite("abc123");
  const input = host.querySelector<HTMLInputElement>(
    '[aria-label="Name for abc123"]',
  )!;
  await change(input, "  Spring ad ");
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2].invite_names,
  ).toEqual({ abc123: "Spring ad" });
  await openInvite("abc123");
  await change(
    host.querySelector<HTMLInputElement>('[aria-label="Name for abc123"]')!,
    "",
  );
  // The saved name is now an edit until Save changes removes it.
  expect(host.textContent).toContain("Unsaved changes");
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.filter((call) => call[1] === "PUT").at(-1)?.[2]
      .invite_names,
  ).toEqual({});
  expect(host.textContent).not.toContain("Unsaved changes");
});
it("lists stale saved names, removes them from the draft only, and validates names", async () => {
  const stale = structuredClone(fixture);
  stale.invite_names = { gone: "Old", abc123: "Ok" };
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      return { ...stale, revision: 5 };
    if (path === "/manage/member-events/settings")
      return structuredClone(stale);
    if (path === "/manage/member-events/invites") return invites();
    throw new Error(`Unexpected ${path}`);
  });
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings view="invites" />));
  await settle();
  expect(host.textContent).toContain("No longer active");
  const before = transport.mock.calls.filter((call) => call[1] === "PUT");
  expect(before).toHaveLength(0);
  await act(async () => button("Remove").click());
  expect(host.textContent).not.toContain("No longer active");
  expect(button("Save changes").disabled).toBe(false);
  await openInvite("abc123");
  await change(
    host.querySelector<HTMLInputElement>('[aria-label="Name for abc123"]')!,
    "👨\u200d👩\u200d👧 fam",
  );
  expect(host.textContent).not.toContain("Remove control");
  await change(
    host.querySelector<HTMLInputElement>('[aria-label="Name for abc123"]')!,
    "bad\u200bname",
  );
  expect(host.textContent).toContain("Remove control or invisible characters.");
  expect(button("Save changes").disabled).toBe(true);
  await change(
    host.querySelector<HTMLInputElement>('[aria-label="Name for abc123"]')!,
    "👨\u200d👩\u200d👧 fam",
  );
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2].invite_names,
  ).toEqual({ abc123: "👨\u200d👩\u200d👧 fam" });
});
it("shows invite load failure without blocking the settings form", async () => {
  await showView("invites");
  invites.mockRejectedValue(new Error("Invite list down"));
  await act(async () => button("Refresh invites").click());
  await settle();
  expect(host.textContent).toContain("Invite list down");
  await showView("channels");
  const join = host.querySelector<HTMLInputElement>(
    '[aria-label="Joins logging"]',
  )!;
  await act(async () => join.click());
  await settle();
  expect(transport.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(
    1,
  );
  expect(join.checked).toBe(false);
});
it("shows the empty invite state", async () => {
  await showView("invites");
  invites.mockResolvedValue({ invites: [], updated_at: null });
  await act(async () => button("Refresh invites").click());
  await settle();
  expect(host.textContent).toContain("No invites recorded yet.");
});
it("saves only the open tab's fields and keeps the other tab's edits in the draft", async () => {
  await openEvent("join");
  await change(
    host.querySelector('[aria-label="Joins channel override"]')!,
    "other",
  );
  await showView("invites");
  // The channel edit is not this tab's change.
  expect(host.textContent).not.toContain("Unsaved changes");
  await openInvite("abc123");
  await change(
    host.querySelector<HTMLInputElement>('[aria-label="Name for abc123"]')!,
    "Reddit",
  );
  await act(async () => button("Save changes").click());
  const first = transport.mock.calls.filter((call) => call[1] === "PUT");
  expect(first).toHaveLength(1);
  expect(first[0][2].invite_names).toEqual({ abc123: "Reddit" });
  expect(first[0][2].events.join.channel_id).toBe(
    fixture.events.join.channel_id,
  );
  await showView("channels");
  expect(host.textContent).toContain("Unsaved changes");
  await act(async () => button("Save changes").click());
  const writes = transport.mock.calls.filter((call) => call[1] === "PUT");
  expect(writes).toHaveLength(2);
  expect(writes[1][2].events.join.channel_id).toBe("other");
  expect(writes[1][2].invite_names).toEqual({ abc123: "Reddit" });
  expect(writes[1][2].revision).toBe(first[0][2].revision + 1);
  expect(host.textContent).not.toContain("Unsaved changes");
});
it("lets Log channels send a test while only invite names are unsaved, and says which tab has edits", async () => {
  const dirtyStates: boolean[] = [];
  await act(async () =>
    root.render(
      <ModerationSettings
        view="invites"
        onDirty={(value) => dirtyStates.push(value)}
      />,
    ),
  );
  await settle();
  await openInvite("abc123");
  await change(
    host.querySelector<HTMLInputElement>('[aria-label="Name for abc123"]')!,
    "Reddit",
  );
  // The leave guard sees edits made only on Invites.
  expect(dirtyStates.at(-1)).toBe(true);
  await act(async () =>
    root.render(
      <ModerationSettings
        view="channels"
        onDirty={(value) => dirtyStates.push(value)}
      />,
    ),
  );
  await settle();
  expect(host.querySelector(".moderation-other-tab-dirty")?.textContent).toBe(
    "Invites has unsaved changes.",
  );
  expect(host.textContent).not.toContain("Unsaved changes");
  expect(host.textContent).not.toContain("Save changes first");
  await openEvent("kick");
  const kick = [...host.querySelectorAll(".moderation-event-row")].find((row) =>
    row.textContent?.includes("Kicks"),
  )!;
  const send = [...kick.querySelectorAll("button")].find(
    (item) => item.textContent === "Send test",
  )!;
  expect(send.disabled).toBe(false);
  await act(async () => send.click());
  await act(async () => button("Send one test").click());
  expect(transport).toHaveBeenCalledWith("/manage/member-events/test", "POST", {
    event_type: "kick",
    revision: 4,
  });
  expect(transport.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(
    0,
  );
  expect(dirtyStates.at(-1)).toBe(true);
});
it("keeps blocking a test while Log channels has its own unsaved edit", async () => {
  await openEvent("join");
  await change(
    host.querySelector('[aria-label="Joins channel override"]')!,
    "other",
  );
  expect(host.textContent).toContain("Save changes first");
});
it("loads an old response that lacks the new keys", async () => {
  const old = structuredClone(fixture) as Partial<SettingsResponse>;
  delete old.invite_names;
  old.ignores = {} as SettingsResponse["ignores"];
  delete (old.categories as Record<string, unknown>).messages;
  delete (old.categories as Record<string, unknown>).invites;
  transport.mockImplementation(async (path: string) =>
    path === "/manage/member-events/invites" ? invites() : structuredClone(old),
  );
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
  expect(host.textContent).toContain("Ignored channels");
  expect(host.textContent).not.toContain("Unsaved changes");
});

const remount = async (changes: Record<string, unknown>) => {
  await act(async () => root.unmount());
  const body = { ...structuredClone(fixture), ...changes };
  transport.mockImplementation(async (path: string) => {
    if (path === "/manage/member-events/settings") return structuredClone(body);
    if (path === "/manage/member-events/invites") return invites();
    throw new Error(`Unexpected ${path}`);
  });
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
};
const ignoredRoles = () =>
  host.querySelectorAll(".moderation-ignore-group")[1] as HTMLElement;
it("names ignored roles, removes them, and never shows numeric ids", async () => {
  await remount({
    ignores: { channel_ids: [], role_ids: ["100000000000000001"] },
  });
  expect(ignoredRoles().textContent).toContain("@Mods");
  const rolePicker =
    ignoredRoles().querySelector<HTMLElement>(".search-picker")!;
  await openPicker(rolePicker);
  expect(optionTexts(rolePicker)).toEqual(["Guests"]);
  expect(host.textContent).not.toMatch(/\d{15,}/);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Remove @Mods"]')!
      .click(),
  );
  expect(ignoredRoles().textContent).toContain("None");
  await act(async () => button("Save changes").click());
  const put = transport.mock.calls.find((call) => call[1] === "PUT");
  expect(put?.[2].ignores.role_ids).toEqual([]);
});
it("shows a removable Deleted role chip for a role missing from the list", async () => {
  await remount({
    ignores: { channel_ids: [], role_ids: ["300000000000000009"] },
  });
  expect(ignoredRoles().textContent).toContain("Deleted role");
  expect(host.textContent).not.toContain("300000000000000009");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Remove Deleted role"]')!
      .click(),
  );
  expect(ignoredRoles().textContent).toContain("None");
});
it("keeps chips removable but blocks adding when roles are unavailable", async () => {
  await remount({
    roles: null,
    roles_available: false,
    ignores: { channel_ids: [], role_ids: ["100000000000000001"] },
  });
  expect(ignoredRoles().textContent).toContain("Roles unavailable.");
  expect(ignoredRoles().textContent).toContain("Unknown role");
  expect(host.textContent).not.toContain("100000000000000001");
  expect(ignoredRoles().querySelector(".search-picker")).toBeNull();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Remove Unknown role"]')!
      .click(),
  );
  expect(ignoredRoles().textContent).toContain("None");
});
it("handles an older response without roles", async () => {
  const { roles: _roles, roles_available: _flag, ...old } = fixture;
  await remount({
    ...old,
    roles: undefined,
    roles_available: undefined,
    ignores: { channel_ids: [], role_ids: ["100000000000000001"] },
  });
  expect(ignoredRoles().textContent).toContain("Unknown role");
  expect(ignoredRoles().textContent).not.toContain("Deleted role");
  expect(ignoredRoles().querySelector(".search-picker")).toBeNull();
  expect(host.textContent).not.toContain("100000000000000001");
});
it("names a saved managed role that is hidden from the add list", async () => {
  await remount({
    roles: [
      ...fixture.roles!,
      {
        id: "100000000000000003",
        name: "Bots",
        color: 0,
        position: 2,
        managed: true,
      },
    ],
    ignores: { channel_ids: [], role_ids: ["100000000000000003"] },
  });
  expect(ignoredRoles().textContent).toContain("@Bots");
  expect(ignoredRoles().textContent).not.toContain("Deleted role");
});

const mountWith = async (response: SettingsResponse) => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      return { ...response, revision: 5 };
    if (path === "/manage/member-events/settings")
      return structuredClone(response);
    if (path === "/manage/member-events/invites") return invites();
    throw new Error(`Unexpected ${path}`);
  });
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
};
const botBlock = () => host.querySelector(".moderation-ignored-bots")!;
const withBots = (): SettingsResponse => ({
  ...structuredClone(fixture),
  ignored_bot_ids: ["900000000000000001", "900000000000000009"],
  bot_actors: [
    { id: "900000000000000001", name: "Helper", last_seen: null },
    { id: "900000000000000002", name: "Counter", last_seen: null },
  ],
});
it("shows ignored bots by name, adds and removes, and saves the ids", async () => {
  await mountWith(withBots());
  expect(botBlock().textContent).toContain(
    "Changes made by these bots are not logged.",
  );
  expect(botBlock().textContent).toContain("@Helper");
  expect(botBlock().textContent).toContain("Unknown bot");
  expect(host.textContent).not.toContain("900000000000000001");
  expect(host.textContent).not.toContain("900000000000000009");
  await act(async () =>
    botBlock()
      .querySelector<HTMLButtonElement>(".search-picker-trigger")!
      .click(),
  );
  const options = [...botBlock().querySelectorAll('[role="option"]')].map(
    (item) => item.textContent,
  );
  expect(options).toEqual(["@Counter"]);
  await act(async () =>
    botBlock().querySelector<HTMLElement>('[role="option"]')!.click(),
  );
  // Add mode: the field stays empty after the bot is appended.
  expect(
    botBlock().querySelector(".search-picker-trigger")!.textContent,
  ).toContain("Add a bot");
  expect(botBlock().textContent).toContain("@Counter");
  expect(host.textContent).toContain("Unsaved changes");
  await act(async () =>
    botBlock()
      .querySelector<HTMLButtonElement>('[aria-label="Remove @Helper"]')!
      .click(),
  );
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2].ignored_bot_ids,
  ).toEqual(["900000000000000009", "900000000000000002"]);
});
it("shows the bot list as unavailable and omits it from the save", async () => {
  expect(botBlock().textContent).toContain("Bot list unavailable.");
  expect(botBlock().querySelector(".search-picker")).toBeNull();
  await openEvent("join");
  const override = host.querySelector<HTMLSelectElement>(
    '[aria-label="Joins channel override"]',
  )!;
  await change(override, "other");
  await act(async () => button("Save changes").click());
  const body = transport.mock.calls.find((call) => call[1] === "PUT")?.[2];
  expect(body).toBeDefined();
  expect("ignored_bot_ids" in body).toBe(false);
});

async function openCategory(category: string) {
  const card = host.querySelector<HTMLDetailsElement>(
    `details:has(#moderation-${category}-title)`,
  )!;
  const toggle = card.querySelector<HTMLButtonElement>(
    ".moderation-category-head > button",
  )!;
  if (toggle.getAttribute("aria-expanded") !== "true")
    await act(async () => toggle.click());
  return card;
}
async function openEvent(kind: string) {
  const row = host.querySelector<HTMLElement>(`[data-event="${kind}"]`)!;
  const group = row.closest("details")!;
  if (!group.open)
    await act(async () => group.querySelector("summary")!.click());
  const toggle = row.querySelector<HTMLButtonElement>(
    ".moderation-event-head > button",
  )!;
  if (toggle.getAttribute("aria-expanded") !== "true")
    await act(async () => toggle.click());
  return row;
}
async function openInvite(code: string) {
  const row = [
    ...host.querySelectorAll<HTMLElement>("[data-invite-code]"),
  ].find((node) => node.dataset.inviteCode === code)!;
  const group = row.closest("details");
  if (group && !group.open)
    await act(async () => group.querySelector("summary")!.click());
  const action = row.querySelector<HTMLButtonElement>("[data-invite-action]")!;
  if (action.getAttribute("aria-expanded") !== "true")
    await act(async () => action.click());
}

it("starts valid groups closed and hides destination, preview and test controls", () => {
  expect(
    [
      ...host.querySelectorAll<HTMLDetailsElement>(".moderation-category-card"),
    ].every((group) => !group.open),
  ).toBe(true);
  expect(host.querySelector(".moderation-category-routing")).toBeNull();
  expect(host.querySelector(".moderation-event-editor")).toBeNull();
  expect(button("Preview")).toBeUndefined();
  expect(button("Send test")).toBeUndefined();
});
it("starts the other-invites group closed on the Invites tab", async () => {
  await showView("invites");
  expect(
    host.querySelector(".moderation-other-invites")?.hasAttribute("open"),
  ).toBe(false);
});
it.each([
  ["all", "Posts to #main-logs"],
  ["none", "Not posting"],
  ["mixed", "Posts to #main-logs · 1 not posting"],
  ["dead", "Posts to #main-logs · 1 not posting"],
  ["different", "Posts to 2 channels"],
  ["different-mixed", "Posts to 2 channels · 1 not posting"],
  ["cannot-post", "Posts to #main-logs · 1 not posting"],
  ["inventory", "Not posting"],
])(
  "summarizes %s routes without hiding nonposting notices",
  (scenario, expected) => {
    const draft = structuredClone(fixture);
    const channels = structuredClone(fixture.channels!);
    if (scenario === "none") draft.categories.members.mode = "off";
    if (scenario === "mixed" || scenario === "different-mixed")
      draft.events.join.enabled = false;
    if (scenario === "dead") draft.events.join.channel_id = "gone";
    if (scenario === "different" || scenario === "different-mixed")
      draft.events.leave.channel_id = "other";
    if (scenario === "cannot-post") {
      draft.events.join.channel_id = "other";
      channels.find((channel) => channel.id === "other")!.can_post = false;
    }
    expect(
      moderationRoutingSummary(
        ["join", "leave", "member_update"],
        draft,
        channels,
        scenario !== "inventory",
      ),
    ).toBe(expected);
  },
);
it("starts a dead-channel group open and preserves enabled switches and test guards", async () => {
  const broken = structuredClone(fixture);
  broken.events.join.channel_id = "gone";
  transport.mockImplementation(async (path) =>
    path === "/manage/member-events/settings"
      ? broken
      : path.endsWith("invites")
        ? invites()
        : health(),
  );
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<ModerationSettings />));
  await settle();
  const row = host.querySelector('[data-event="join"]')!;
  expect(row.closest("details")!.open).toBe(true);
  expect(
    row
      .querySelector(".moderation-event-status")
      ?.classList.contains("is-unavailable"),
  ).toBe(true);
  expect(row.textContent).toContain("Channel unavailable · not posting");
  await openEvent("join");
  expect(
    [...row.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent === "Send test",
    )!.disabled,
  ).toBe(true);
  expect(
    host.querySelector<HTMLInputElement>('[aria-label="Joins logging"]')!
      .checked,
  ).toBe(true);
});

function baselineWire(settings: SettingsResponse) {
  return {
    revision: settings.revision,
    main: structuredClone(settings.main),
    categories: Object.fromEntries(
      moderationRegistry.map(({ key }) => [
        key,
        structuredClone(settings.categories[key]),
      ]),
    ),
    events: Object.fromEntries(
      eventTypes.map(({ key }) => [key, structuredClone(settings.events[key])]),
    ),
    ignores: structuredClone(settings.ignores),
    invite_names: Object.fromEntries(
      Object.entries(settings.invite_names)
        .map(([code, name]) => [code, name.trim()])
        .filter(([, name]) => name),
    ),
    ...(Array.isArray(settings.ignored_bot_ids)
      ? { ignored_bot_ids: [...settings.ignored_bot_ids] }
      : {}),
  };
}
it.each([
  "notice-own",
  "group-main",
  "group-off",
  "invite-name",
  "bot-add",
  "bot-remove",
])(
  "keeps the baseline save body byte-equal for %s and Discard restores it",
  async (scenario) => {
    const settings = structuredClone(fixture);
    settings.ignored_bot_ids = ["900000000000000001"];
    settings.bot_actors = [
      { id: "900000000000000001", name: "Helper", last_seen: null },
      { id: "900000000000000002", name: "Other", last_seen: null },
    ];
    if (scenario === "group-main")
      settings.categories.members = {
        mode: "own",
        channel_id: "other",
        forum_tag_id: null,
      };
    transport.mockImplementation(async (path, method, body) => {
      if (path.endsWith("/settings"))
        return method === "PUT"
          ? { ...settings, ...body, revision: 5 }
          : structuredClone(settings);
      if (path.endsWith("/invites")) return invites();
      if (path.endsWith("/health")) return health();
      throw Error(`Unexpected ${path}`);
    });
    if (scenario === "invite-name") await showView("invites");
    await act(async () => button("Refresh settings").click());
    await settle();
    const expected = baselineWire(settings);
    if (scenario === "notice-own") expected.events.join.channel_id = "other";
    if (scenario === "group-main") expected.categories.members.mode = "main";
    if (scenario === "group-off") expected.categories.members.mode = "off";
    if (scenario === "invite-name")
      expected.invite_names = { abc123: "Reddit" };
    if (scenario === "bot-add")
      expected.ignored_bot_ids!.push("900000000000000002");
    if (scenario === "bot-remove") expected.ignored_bot_ids = [];
    const edit = async () => {
      if (scenario === "notice-own") {
        await openEvent("join");
        await change(
          host.querySelector('[aria-label="Joins channel override"]')!,
          "other",
        );
      }
      if (scenario.startsWith("group-")) {
        const card = await openCategory("members");
        await change(
          card.querySelector(".moderation-category-routing select")!,
          scenario === "group-main" ? "main" : "off",
        );
      }
      if (scenario === "invite-name") {
        await openInvite("abc123");
        const input = host.querySelector<HTMLInputElement>(
          '[aria-label="Name for abc123"]',
        )!;
        await change(input, " Reddit ");
        await act(async () =>
          input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })),
        );
      }
      if (scenario === "bot-add") await pick(botBlock(), "@Other");
      if (scenario === "bot-remove")
        await act(async () =>
          botBlock()
            .querySelector<HTMLButtonElement>('[aria-label="Remove @Helper"]')!
            .click(),
        );
    };
    await edit();
    expect(button("Save changes").disabled).toBe(false);
    await act(async () => button("Discard").click());
    expect(host.querySelector(".moderation-settings-save")).toBeNull();
    expect(
      transport.mock.calls.filter(([, method]) => method === "PUT"),
    ).toHaveLength(0);
    await edit();
    await act(async () => button("Save changes").click());
    const writes = transport.mock.calls.filter(
      ([, method]) => method === "PUT",
    );
    expect(writes).toHaveLength(1);
    expect(JSON.stringify(writes[0][2])).toBe(JSON.stringify(expected));
  },
);
