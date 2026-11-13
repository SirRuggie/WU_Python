// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./ChannelCombobox", () => ({
  default: ({
    value,
    onChange,
    disabled,
  }: {
    value: string;
    onChange: (v: string) => void;
    disabled: boolean;
  }) => (
    <select
      aria-label="Channel"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Select</option>
      <option value="123456789012345678">lazy-news</option>
    </select>
  ),
}));
vi.mock("./DiscordPreview", () => ({
  default: ({ label }: { label: string }) => <div>{label}</div>,
}));
import LazyInfractionsSheet from "./LazyInfractionsSheet";

const preview = (patch = {}) => ({
  cycle: "2026-11",
  label: "November 2026",
  clans: [
    {
      tag: "#2YQ",
      name: "Lazy One",
      players: [
        {
          tag: "#P2Y",
          player_name: "Amy",
          town_hall: 15,
          infractions: ["Missed sync", "Lingering"],
        },
        {
          tag: "#Q2Y",
          player_name: "Zed",
          town_hall: 14,
          infractions: ["Did not join"],
        },
      ],
    },
  ],
  exceptions: [
    {
      tag: "#R2Y",
      player_name: "Excused",
      town_hall: 13,
      infractions: ["Left family"],
      clan_name: "Lazy One",
      reason: "Moved for family war",
    },
  ],
  blockers: [],
  pages: [[{ type: "text", text: "x" }]],
  player_count: 2,
  clan_count: 1,
  fingerprint: "f".repeat(64),
  ...patch,
});

let root: Root;
let host: HTMLDivElement;
const flush = () =>
  act(async () => void (await new Promise((r) => setTimeout(r, 0))));
const button = (text: RegExp) =>
  [...document.querySelectorAll("button")].find((b) =>
    text.test(b.textContent || ""),
  );
const select = () =>
  document.querySelector('select[aria-label="Channel"]') as HTMLSelectElement;
const review = () =>
  document.querySelector<HTMLInputElement>('input[type="checkbox"]')!;

async function render(
  previewValue = preview(),
  { canSend = true, archived = false } = {},
) {
  api.mockImplementation(async (path: string, method = "GET") => {
    if (path === "/announcement-channels")
      return {
        channels: [{ id: "123456789012345678", name: "lazy-news", type: 0 }],
      };
    if (method === "GET") return previewValue;
    return {
      status: "sent",
      failure: null,
      urls: ["https://discord.com/channels/1/2/3"],
      pages: 1,
    };
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() =>
    root.render(
      <LazyInfractionsSheet
        seasonId="7"
        archived={archived}
        canSend={canSend}
        trigger={null}
        onClose={() => {}}
      />,
    ),
  );
  await flush();
}

describe("LazyInfractionsSheet", () => {
  beforeEach(() => api.mockReset());
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    document.body.innerHTML = "";
  });

  it("lists players by clan with their infractions and keeps exceptions apart", async () => {
    await render();
    const text = document.body.textContent || "";
    expect(text).toContain("November 2026 · 2 players · 1 clan");
    const clan = document.querySelector('section[aria-label="Lazy One"]')!;
    expect(clan.textContent).toContain("Amy");
    expect(clan.textContent).toContain("#P2Y");
    expect(clan.textContent).toContain("Missed sync");
    expect(clan.textContent).toContain("Lingering");
    expect(clan.textContent).toContain("Did not join");
    expect(clan.textContent).not.toContain("Excused");
    const exceptions = document.querySelector("details")!;
    expect(exceptions.open).toBe(false);
    expect(exceptions.textContent).toContain("Staff exceptions · 1 player");
    expect(exceptions.textContent).toContain("Moved for family war");
  });

  it("needs a channel and the review check, then sends once with no pings field", async () => {
    await render();
    const send = () => button(/Send/)!;
    expect(send().disabled).toBe(true);
    act(() => {
      select().value = "123456789012345678";
      select().dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(send().textContent).toBe("Send to #lazy-news");
    expect(send().disabled).toBe(true);
    act(() => review().click());
    expect(send().disabled).toBe(false);
    act(() => {
      send().click();
      send().click();
    });
    await flush();
    const posts = api.mock.calls.filter((call) => call[1] === "POST");
    expect(posts).toHaveLength(1);
    expect(Object.keys(posts[0][2]).sort()).toEqual([
      "channel_id",
      "fingerprint",
      "request_id",
    ]);
    expect(posts[0][2].request_id).toMatch(/^[a-f0-9]{24}$/);
    expect(document.body.textContent).toContain("Infractions sent");
  });

  it("without send access it is a read-only list and loads no channels", async () => {
    await render(preview(), { canSend: false });
    expect(document.body.textContent).toContain("Amy");
    expect(select()).toBeNull();
    expect(button(/Send/)).toBeUndefined();
    expect(
      api.mock.calls.some((call) => call[0] === "/announcement-channels"),
    ).toBe(false);
  });

  it("an empty month shows a plain line and no send", async () => {
    await render(
      preview({
        clans: [],
        exceptions: [],
        pages: [],
        player_count: 0,
        clan_count: 0,
        blockers: ["No players have infractions to post."],
      }),
    );
    expect(document.body.textContent).toContain("No players have infractions.");
    act(() => {
      select().value = "123456789012345678";
      select().dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(review().disabled).toBe(true);
    expect(button(/Send/)!.disabled).toBe(true);
  });

  it("a changed list (409) offers Try again and keeps the same request ID", async () => {
    await render();
    api.mockImplementation(async (path: string, method = "GET") => {
      if (path === "/announcement-channels")
        return {
          channels: [{ id: "123456789012345678", name: "lazy-news", type: 0 }],
        };
      if (method === "GET") return preview();
      const { ApiError } = await import("./api");
      throw new ApiError(
        "The infractions changed. Review the preview again.",
        409,
      );
    });
    act(() => {
      select().value = "123456789012345678";
      select().dispatchEvent(new Event("change", { bubbles: true }));
    });
    act(() => review().click());
    act(() => button(/Send/)!.click());
    await flush();
    expect(document.body.textContent).toContain("The infractions changed");
    expect(button(/Try again/)).toBeDefined();
  });
});
