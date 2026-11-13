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
import LazyAnnouncementSheet from "./LazyAnnouncementSheet";

const preview = (patch = {}) => ({
  cycle: "2026-10",
  scope: "one",
  clan_tag: "#2YQ",
  ping: true,
  ping_count: 2,
  clans: [
    { tag: "#2YQ", name: "Lazy One", draw_state: "approved", ready: true },
  ],
  blockers: [],
  pages: [[{ type: "text", text: "x" }]],
  history: [
    { label: "July", count: 2 },
    { label: "August", count: 1 },
    { label: "September", count: 3 },
  ],
  winner_count: 2,
  clan_count: 1,
  unlinked_count: 0,
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
  )!;
function change(element: HTMLSelectElement | HTMLInputElement, value?: string) {
  act(() => {
    if (element instanceof HTMLSelectElement) {
      element.value = value!;
      element.dispatchEvent(new Event("change", { bubbles: true }));
    } else element.click();
  });
}

async function render(previewValue = preview()) {
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
      <LazyAnnouncementSheet
        seasonId="7"
        clans={[{ tag: "#2YQ", name: "Lazy One" }]}
        initialClan="#2YQ"
        archived={false}
        trigger={null}
        onClose={() => {}}
        onSent={() => {}}
      />,
    ),
  );
  await flush();
}

describe("LazyAnnouncementSheet", () => {
  beforeEach(() => api.mockReset());
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    document.body.innerHTML = "";
  });

  it("needs a channel and the review check before Send, and sends once", async () => {
    await render();
    expect(api.mock.calls[1][0]).toContain("scope=one");
    expect(api.mock.calls[1][0]).toContain("ping=1");
    const send = () => button(/Send/);
    expect(send().disabled).toBe(true);
    change(
      document.querySelector(
        'select[aria-label="Channel"]',
      ) as HTMLSelectElement,
      "123456789012345678",
    );
    expect(send().textContent).toBe("Send to #lazy-news");
    expect(send().disabled).toBe(true);
    const review = [
      ...document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    ][1];
    change(review);
    expect(send().disabled).toBe(false);
    act(() => {
      send().click();
      send().click();
    });
    await flush();
    const posts = api.mock.calls.filter((call) => call[1] === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0][2]).toMatchObject({
      scope: "one",
      clan_tag: "#2YQ",
      ping: true,
      channel_id: "123456789012345678",
    });
    expect(posts[0][2].request_id).toMatch(/^[a-f0-9]{24}$/);
    expect(document.body.textContent).toContain("Announcement sent");
    expect(document.body.textContent).toContain("View message 1 in Discord");
  });

  it("blocks Send and lists the reason when a clan is not approved", async () => {
    await render(
      preview({
        blockers: ["Lazy Two: approve the winners first."],
        pages: [],
      }),
    );
    expect(document.body.textContent).toContain(
      "Lazy Two: approve the winners first.",
    );
    change(
      document.querySelector(
        'select[aria-label="Channel"]',
      ) as HTMLSelectElement,
      "123456789012345678",
    );
    const review = [
      ...document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    ][1];
    expect(review.disabled).toBe(true);
    expect(button(/Send/).disabled).toBe(true);
  });

  it("switching to All Lazy clans reloads the preview and clears the review", async () => {
    await render();
    change(document.querySelector('input[value="all"]') as HTMLInputElement);
    await flush();
    const reads = api.mock.calls.filter((call) =>
      String(call[0]).includes("lazy-announcement"),
    );
    expect(reads.at(-1)![0]).toContain("scope=all");
    expect(reads.at(-1)![0]).not.toContain("clan_tag");
  });
});
