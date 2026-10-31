// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Command } from "./CommandBuilder";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api,
}));
vi.mock("./CommandBuilder", async (original) => ({
  ...(await original<typeof import("./CommandBuilder")>()),
  default: () => <div>Embed content</div>,
}));
vi.mock("./CommandTest", () => ({ default: () => null }));
vi.mock("./CommandActivity", () => ({ default: () => null }));
vi.mock("./ChangeHistory", () => ({ default: () => null }));
vi.mock("./DiscordMessagePreview", () => ({ default: () => null }));
vi.mock("./MentionText", () => ({
  default: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <label>
      {label}
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  ),
  namedMentions: (value: string) => value,
}));

import TextCommands from "./TextCommands";

const oldCommand: Command = {
  command: "!lazy",
  enabled: true,
  text: "Reply",
  title: "",
  description: "",
  image_url: "",
  color: "#e2b332",
  revision: "r1",
  use_count: 3,
  last_used_at: new Date(Date.now() - 7200000).toISOString(),
  last_outcome: {
    status: "error",
    at: new Date().toISOString(),
    channel_id: "123456789012345678",
    reason: "The reply could not be delivered.",
  },
  last_delete_error: {
    at: "2026-10-30T00:00:00Z",
    channel_id: "123456789012345678",
    reason: "<script>never render this</script>",
  },
};

async function mount(commands: Command[]) {
  api.mockImplementation(
    async (
      path: string,
      method?: string,
      body?: {
        values: Command;
      },
    ) => {
      if (path === "/manage/text-commands" && !method) return { commands };
      if (path === "/manage/text-command-roles") return { roles: [] };
      if (method === "PATCH" || method === "POST") {
        return { ...body?.values, revision: "r2", last_delete_error: null };
      }
      throw new Error(`Unexpected request: ${path}`);
    },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<TextCommands onDirty={() => {}} />));
  return { host, root };
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset();
});
afterEach(() => {
  document.body.replaceChildren();
});

it("starts a new command with trigger deletion enabled and sends that choice", async () => {
  const { host, root } = await mount([]);
  try {
    await act(async () => {
      (host.querySelector(".page-head .primary") as HTMLButtonElement).click();
    });
    const checkbox = [
      ...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    ].find((input) =>
      input.parentElement?.textContent?.includes("Delete the trigger message"),
    )!;
    expect(checkbox.checked).toBe(true);
    expect(host.textContent).toContain("Delete the trigger message");
    await act(async () => {
      (
        host.querySelector("#command-reply-form") as HTMLFormElement
      ).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(api).toHaveBeenCalledWith(
      "/manage/text-commands",
      "POST",
      expect.objectContaining({
        values: expect.objectContaining({ delete_trigger: true }),
      }),
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("defaults an old row on, toggles it off, and excludes runtime error from save", async () => {
  const { host, root } = await mount([oldCommand]);
  try {
    expect(
      host.querySelector(".text-command-rows button")?.textContent,
    ).toContain(
      "Last time the bot could not delete the trigger message in #123456789012345678",
    );
    await act(async () => {
      (
        host.querySelector(".text-command-rows button") as HTMLButtonElement
      ).click();
    });
    const checkbox = [
      ...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    ].find((input) =>
      input.parentElement?.textContent?.includes("Delete the trigger message"),
    )!;
    expect(checkbox.checked).toBe(true);
    expect(host.textContent).toContain(
      "Last time the bot could not delete the trigger message in #123456789012345678",
    );
    expect(host.textContent).toContain("it needs Manage Messages there");
    expect(host.textContent).not.toContain("<script>");
    await act(async () => checkbox.click());
    expect(checkbox.checked).toBe(false);
    expect(host.textContent).toContain("Used 3 times");
    expect(host.textContent).toContain("The reply could not be delivered.");
    await act(async () => {
      (
        host.querySelector("#command-reply-form") as HTMLFormElement
      ).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    const save = api.mock.calls.find((call) => call[1] === "PATCH")!;
    expect(save[2].values.delete_trigger).toBe(false);
    expect(save[2].values).not.toHaveProperty("last_delete_error");
    expect(save[2].revision).toBe("r1");
    for (const field of ["use_count", "last_used_at", "last_outcome"])
      expect(save[2].values).not.toHaveProperty(field);

  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
