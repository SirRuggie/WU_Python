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
  },
  events: Object.fromEntries(
    ["join", "leave", "kick", "ban"].map((key) => [
      key,
      { enabled: true, channel_id: null, forum_tag_id: null },
    ]),
  ) as SettingsResponse["events"],
  ignores: {},
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
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage/member-events/settings" && method === "PUT")
      return { ...fixture, revision: 5 };
    if (path === "/manage/member-events/settings")
      return structuredClone(fixture);
    if (path === "/manage/member-events/test") return { sent: true };
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
  expect(host.querySelectorAll(".moderation-event-row")).toHaveLength(4);
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
