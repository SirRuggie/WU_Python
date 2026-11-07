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
    messages: { mode: "main", channel_id: null, forum_tag_id: null },
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
    ].map((key) => [
      key,
      { enabled: true, channel_id: null, forum_tag_id: null },
    ]),
  ) as SettingsResponse["events"],
  ignores: { channel_ids: [], role_ids: [] },
  invite_names: {},
  channels_available: true,
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
  expect(host.textContent).toContain("Uses main's channel · #main-logs");
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
it("hides unsupported future event controls", () => {
  expect(host.textContent).not.toContain("Nickname changes");
  expect(host.textContent).not.toContain("Roles added");
  expect(host.textContent).not.toContain("Channels created");
  expect(host.querySelectorAll(".moderation-event-row")).toHaveLength(11);
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
  expect(card.textContent).toContain("Uses main's channel");
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
  expect(card.querySelectorAll(".moderation-event-row")).toHaveLength(4);
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
it("renders the four categories with Links and Invites events", () => {
  const titles = [...host.querySelectorAll(".moderation-category-head h3")].map(
    (item) => item.textContent?.trim(),
  );
  expect(titles).toEqual([
    "👥 Members",
    "🛡️ Moderation",
    "💬 Messages",
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
  const roleInput = host.querySelector<HTMLInputElement>(
    '.moderation-ignore-group input[placeholder="Role ID"]',
  )!;
  await change(roleInput, "12");
  await act(async () => button("Add").click());
  expect(host.textContent).toContain("17 to 20 digits");
  await change(roleInput, "123456789012345678");
  await act(async () => button("Add").click());
  expect(host.textContent).toContain("Role 123456789012345678");
  await act(async () => button("Save changes").click());
  expect(
    transport.mock.calls.find((call) => call[1] === "PUT")?.[2],
  ).toMatchObject({
    ignores: { channel_ids: ["other"], role_ids: ["123456789012345678"] },
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
