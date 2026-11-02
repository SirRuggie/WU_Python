// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import Update from "./AnnouncementPostUpdate";
import { ApiError } from "./api";
import type { PostReview } from "./announcementPostUpdate";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DiscordMessagePreview", () => ({
  default: ({ label, parts }: { label: string; parts: unknown[] }) => (
    <section aria-label={label}>{JSON.stringify(parts)}</section>
  ),
}));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const updated = vi.fn(),
  dirty = vi.fn();
const copy = {
  title: "Roster title",
  body: "Roster body",
  buttons: [{ label: "My tasks", url: "https://dash.warriorsunited.cc/tasks" }],
};
const props = {
  seasonId: "1",
  cycle: "2026-11",
  pool: "main" as const,
  generation: "g1",
  copy,
  allowed: true,
  onUpdated: updated,
  onDirty: dirty,
};
const ready: PostReview = {
  status: "ready",
  candidate: copy,
  generation: "g1",
  future_months: true,
  worker_ready: true,
  channel_name: "main-rosters",
  message_url: "https://discord.com/channels/1/2/3",
  live_preview: [{ type: "text", text: "Actual live post" }],
  draft_preview: [{ type: "text", text: "Proposed post" }],
};
const button = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")]
    .filter((item) => item.textContent?.trim() === name)
    .at(-1)!;
const click = async (name: string) => {
  expect(button(name)).toBeTruthy();
  await act(async () => button(name).click());
};
async function mount(changes: Partial<typeof props> = {}) {
  await act(async () => root.render(<Update {...props} {...changes} />));
}
async function preview() {
  await click("Edit post");
  await click("Preview");
}
beforeEach(() => {
  api.mockReset();
  updated.mockReset();
  dirty.mockReset();
  sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

it("does no fetch while closed; Preview does not update and future copy is ticked by default", async () => {
  await mount();
  expect(api).not.toHaveBeenCalled();
  api.mockResolvedValue(structuredClone(ready));
  await preview();
  expect(api).toHaveBeenCalledTimes(1);
  expect(api.mock.calls[0][1]).toBe("POST");
  expect(api.mock.calls[0][0]).toBe(
    "/seasons/1/manage-bridge/main/post-updates",
  );
  expect(api.mock.calls[0][2]).toMatchObject({
    generation: "g1",
    candidate: copy,
  });
  expect(
    document.querySelector<HTMLInputElement>("input[type=checkbox]")?.checked,
  ).toBe(true);
  expect(document.body.textContent).toContain("Actual live post");
  expect(document.body.textContent).toContain("Proposed post");
  expect(updated).not.toHaveBeenCalled();
  await click("Update post");
  expect(document.body.textContent).toContain(
    "Update the existing post in #main-rosters?",
  );
  expect(api).toHaveBeenCalledTimes(1);
});

it("confirm sends only reviewed boolean scope once; repeated clicks cannot queue another edit", async () => {
  api.mockResolvedValueOnce(structuredClone(ready));
  await mount();
  await preview();
  const checkbox = document.querySelector<HTMLInputElement>(
    "input[type=checkbox]",
  )!;
  await act(async () => checkbox.click());
  let resolve!: (value: PostReview) => void;
  api.mockImplementationOnce(
    () => new Promise<PostReview>((done) => (resolve = done)),
  );
  await click("Update post");
  const confirmation = button("Update post");
  await act(async () => {
    confirmation.click();
    confirmation.click();
  });
  expect(
    api.mock.calls.filter((call) => String(call[0]).endsWith("/update")),
  ).toHaveLength(1);
  expect(api.mock.calls.at(-1)?.slice(1)).toEqual([
    "POST",
    { future_months: false },
  ]);
  await act(async () =>
    resolve({
      ...ready,
      status: "done",
      campaign_saved: true,
      recurring_saved: false,
    }),
  );
  expect(document.body.textContent).toContain(
    "Post updated. Saved for this month.",
  );
  expect(updated).toHaveBeenCalledTimes(1);
  expect(document.querySelector("a")?.href).toBe(
    "https://discord.com/channels/1/2/3",
  );
});

it("closing a pending request retains its identity; reopening checks it without another POST", async () => {
  api.mockResolvedValueOnce({ ...ready, status: "pending_update" });
  await mount();
  await preview();
  const close = [
    ...document.querySelectorAll<HTMLButtonElement>("button"),
  ].find((item) => item.getAttribute("aria-label")?.startsWith("Close"))!;
  expect(close).toBeTruthy();
  await act(async () => close.click());
  expect(document.querySelector("[role=dialog]")).toBeNull();
  api.mockResolvedValueOnce({
    ...ready,
    status: "done",
    campaign_saved: true,
    recurring_saved: true,
  });
  await click("Edit post");
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(1);
  expect(api.mock.calls.at(-1)?.[1]).toBeUndefined();
  expect(document.body.textContent).toContain("Post updated.");
});

it("stale or deleted results never offer a new Send or replacement post", async () => {
  api.mockResolvedValue({
    ...ready,
    status: "failed",
    error: "Post changed. Preview again.",
  });
  await mount();
  await preview();
  expect(document.body.textContent).toContain("Post changed. Preview again.");
  expect(button("Update post")).toBeUndefined();
  expect(
    [...document.querySelectorAll("button")].some((item) =>
      /send|new post/i.test(item.textContent || ""),
    ),
  ).toBe(false);
  expect(button("Preview again")).toBeTruthy();
});

it("expired permission clears protected snapshots and candidate instead of showing stale preview", async () => {
  api.mockResolvedValueOnce({ ...ready, worker_ready: false });
  await mount();
  await preview();
  api.mockRejectedValueOnce(new ApiError("Access removed", 403));
  await click("Refresh status");
  expect(document.body.textContent).toContain("Access removed");
  expect(document.body.textContent).not.toContain("Actual live post");
  expect(document.body.textContent).not.toContain("Proposed post");
  expect(button("Update post")).toBeUndefined();
});

it("an ordinary failed read retains the last authorized preview and a visible error", async () => {
  api.mockResolvedValueOnce({ ...ready, worker_ready: false });
  await mount();
  await preview();
  api.mockRejectedValueOnce(new ApiError("Temporarily unavailable", 503));
  await click("Refresh status");
  expect(document.body.textContent).toContain("Temporarily unavailable");
  expect(document.body.textContent).toContain("Actual live post");
  expect(button("Update post").disabled).toBe(true);
});

it("pins editor generation instead of attaching a new generation to stale text", async () => {
  await mount();
  await click("Edit post");
  await mount({ generation: "g2" });
  expect(button("Preview").disabled).toBe(true);
  expect(document.body.textContent).toContain("Saved campaign changed");
  expect(api).not.toHaveBeenCalled();
});

it("a deleted post offers no update, replacement or fresh edit action", async () => {
  api.mockResolvedValue({
    ...ready,
    status: "failed",
    error_code: "deleted",
    error:
      "The post was deleted or is no longer available. It cannot be updated.",
  });
  await mount();
  await preview();
  expect(button("Update post")).toBeUndefined();
  expect(button("Preview again")).toBeUndefined();
  expect(document.querySelector("a")).toBeNull();
  expect(document.body.textContent).toContain("deleted");
});
