// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SettingsResponse } from "./moderationSettingsModel";
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
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      return { ...fixture, revision: 5 };
    if (path === "/manage/member-events/settings")
      return structuredClone(fixture);
    if (path === "/manage/member-events/test") return { sent: true };
    if (path === "/manage/member-events/health") return health();
    if (path === "/manage/member-events/invites") return invites();
    throw new Error(`Unexpected ${path}`);
  });
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
it("requires explicit save and supports discard of an event override", async () => {
  await act(async () => button("Change").click());
  const override = host.querySelector<HTMLSelectElement>(
    '[aria-label="Joins channel override"]',
  )!;
  await act(async () => {
    override.value = "other";
    override.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("Uses its own channel · #other-logs");
  expect(button("Send test").hasAttribute("disabled")).toBe(true);
  expect(transport.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(
    0,
  );
  await act(async () => button("Discard").click());
  expect(host.textContent).toContain("Uses the main channel · #main-logs");
  const joinSwitch = host.querySelector<HTMLInputElement>(
    '[aria-label="Joins logging"]',
  )!;
  await act(async () => joinSwitch.click());
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2],
  ).toMatchObject({ revision: 4, events: { join: { enabled: false } } });
});
it("renders the payload preview and confirms a test without saving", async () => {
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
it("puts the shared ignore note after the message rows", () => {
  const card = [...host.querySelectorAll(".moderation-category-card")].find(
    (el) => el.querySelector("h3")?.textContent?.includes("Messages"),
  )!;
  const rows = card.querySelectorAll(".moderation-event-row");
  expect(rows).toHaveLength(4);
  const note = card.querySelector(".moderation-ignore-note")!;
  expect(note.textContent).toBe("Applies to all message logs.");
  expect(
    rows[3].compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    note.compareDocumentPosition(
      card.querySelector(".moderation-ignore-lists")!,
    ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
it("saves new keys and categories in the payload", async () => {
  await act(async () =>
    host
      .querySelector<HTMLInputElement>('[aria-label="Emoji logging"]')!
      .click(),
  );
  await act(async () => button("Save changes").click());
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
  expect(host.querySelector(".moderation-settings-error")).toBeNull();
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
  const joinSwitch = host.querySelector<HTMLInputElement>(
    '[aria-label="Joins logging"]',
  )!;
  await act(async () => joinSwitch.click());
  await act(async () => button("Save changes").click());
  expect(joinSwitch.checked).toBe(false);
  expect(host.textContent).toContain("Your edits are preserved");
  expect(host.textContent).toContain("Unsaved changes");
});

it("restores the last active mode despite a retained own channel", async () => {
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
  expect(card.textContent).toContain("Uses the main channel");
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
  expect(
    card.querySelector(".moderation-category-switch")?.textContent,
  ).toContain("Not posting — no channel set");
  expect(card.querySelectorAll(".moderation-event-row")).toHaveLength(5);
  for (const row of card.querySelectorAll(".moderation-event-row")) {
    expect(row.textContent).toContain("Not posting — no channel set");
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
it("renders all seven categories", () => {
  const titles = [...host.querySelectorAll(".moderation-category-head h3")].map(
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
  const channelSelect = host.querySelector<HTMLSelectElement>(
    ".moderation-ignore-group select",
  )!;
  await change(channelSelect, "other");
  expect(host.textContent).toContain("#other-logs");
  expect(host.textContent).toContain("Unsaved changes");
  await act(async () => button("Guests＋").click());
  expect(host.textContent).toContain("@Guests");
  expect(host.textContent).not.toContain("100000000000000002");
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2],
  ).toMatchObject({
    ignores: { channel_ids: ["other"], role_ids: ["100000000000000002"] },
  });
});
it("lists invites with uses and saves edited names; clearing removes", async () => {
  expect(host.textContent).toContain("3 / 10 uses");
  expect(host.textContent).toContain("40 uses");
  expect(host.textContent).toContain("Vanity URL");
  const input = host.querySelector<HTMLInputElement>(
    '[aria-label="Name for abc123"]',
  )!;
  await change(input, "  Spring ad ");
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2].invite_names,
  ).toEqual({ abc123: "Spring ad" });
  await change(input, "");
  expect(host.textContent).toContain("All changes saved");
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
  await act(async () => root.render(<ModerationSettings />));
  await settle();
  expect(host.textContent).toContain("No longer active");
  const before = transport.mock.calls.filter((call) => call[1] === "PUT");
  expect(before).toHaveLength(0);
  await act(async () => button("Remove").click());
  expect(host.textContent).not.toContain("No longer active");
  expect(button("Save changes").disabled).toBe(false);
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
  invites.mockRejectedValue(new Error("Invite list down"));
  await act(async () => button("Refresh invites").click());
  await settle();
  expect(host.textContent).toContain("Invite list down");
  const join = host.querySelector<HTMLInputElement>(
    '[aria-label="Joins logging"]',
  )!;
  await act(async () => join.click());
  expect(button("Save changes").disabled).toBe(false);
});
it("shows the empty invite state", async () => {
  invites.mockResolvedValue({ invites: [], updated_at: null });
  await act(async () => button("Refresh invites").click());
  await settle();
  expect(host.textContent).toContain("No invites recorded yet.");
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
  expect(host.textContent).toContain("All changes saved");
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
  expect(ignoredRoles().textContent).toContain("Guests");
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
  expect(ignoredRoles().querySelector(".role-picker")).toBeNull();
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
  expect(ignoredRoles().querySelector(".role-picker")).toBeNull();
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
  const options = [...botBlock().querySelectorAll("option")].map(
    (item) => item.textContent,
  );
  expect(options).toEqual(["Select a bot", "@Counter"]);
  await change(botBlock().querySelector("select")!, "900000000000000002");
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
  expect(botBlock().querySelector("select")).toBeNull();
  await act(async () => button("Change").click());
  const override = host.querySelector<HTMLSelectElement>(
    '[aria-label="Joins channel override"]',
  )!;
  await change(override, "other");
  await act(async () => button("Save changes").click());
  const body = transport.mock.calls.find((call) => call[1] === "PUT")?.[2];
  expect(body).toBeDefined();
  expect("ignored_bot_ids" in body).toBe(false);
});
