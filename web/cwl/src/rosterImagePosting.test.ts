import { expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  imageConfirm,
  imageJobs,
  imagePoolStatus,
  runImageJobs,
  type ImageData,
} from "./rosterImagePosting";
const data = (): ImageData => ({
  published: { version: 1, published_at: "2026-10-28T12:00:00Z" },
  last_publication: null,
  posts: [],
  clans: Array.from({ length: 6 }, (_, i) => ({
    tag: `#C${i}`,
    name: `Clan ${i}`,
    pool: "lazy",
    pages: 1,
    count: 15,
  })),
});
const row = (i: number, extra = {}) => ({
  clan_tag: `#C${i}`,
  pool: "lazy" as const,
  channel_id: "123",
  message_id: "456",
  status: "posted" as const,
  posted_version: 1,
  posted_at: "2026-10-28 12:00:00",
  operation: "post" as const,
  ...extra,
});
it("states and Resume/Retry only select eligible clans", () => {
  const d = data();
  expect(imagePoolStatus(d, "lazy").label).toBe("Not posted yet");
  d.posts = [0, 1, 2, 3].map((i) => row(i));
  expect(imagePoolStatus(d, "lazy").label).toBe("4 of 6 posted · Resume");
  expect(imageJobs(d, "lazy", "123").map((j) => j.clan.tag)).toEqual([
    "#C4",
    "#C5",
  ]);
  d.posts.push(row(4, { status: "failed" }));
  expect(imagePoolStatus(d, "lazy").label).toBe("1 failed · Retry failed");
  expect(imageJobs(d, "lazy", "123", true).map((j) => j.clan.tag)).toEqual([
    "#C4",
  ]);
  d.posts = [0, 1, 2, 3, 4, 5].map((i) => row(i));
  expect(imagePoolStatus(d, "lazy").label).toContain("for version 1 · 6 clans");
  d.published!.version = 2;
  expect(imagePoolStatus(d, "lazy").action).toBe("Update posted images");
  d.clans = d.clans.slice(1);
  const jobs = imageJobs(d, "lazy", "123");
  expect(jobs.at(-1)?.operation).toBe("drop");
  expect(imageConfirm(jobs, "rosters")).toBe(
    "Update 5 posted messages to version 2, post 0 new clan, and mark 1 clan as no longer hosting?",
  );
  d.posts[0] = row(0, { status: "uncertain" });
  expect(imageJobs(d, "lazy", "123").some((j) => j.clan.tag === "#C0")).toBe(
    false,
  );
  d.published = null;
  expect(imageJobs(d, "lazy", "123")).toEqual([]);
});
it("runs sequentially, waits for 429, then resumes with a new known-safe request id", async () => {
  const send = vi
    .fn()
    .mockRejectedValueOnce(new ApiError("Rate limit", 429, 0.01))
    .mockResolvedValue({});
  const wait = vi.fn(async () => {}),
    completed = vi.fn(async () => {});
  await runImageJobs("1", imageJobs(data(), "lazy", "123"), {
    send,
    wait,
    active: () => true,
    progress: () => {},
    completed,
  });
  expect(wait).toHaveBeenCalledWith(10);
  expect(send).toHaveBeenCalledTimes(7);
  expect(completed).toHaveBeenCalledTimes(6);
  expect(send.mock.calls[0][2].request_id).not.toBe(
    send.mock.calls[1][2].request_id,
  );
});
it("close waits for the current request, then stops; non-429 errors stop", async () => {
  let active = true;
  const send = vi.fn(async () => {
    active = false;
    return {} as never;
  });
  const jobs = imageJobs(data(), "lazy", "123");
  await runImageJobs("1", jobs, {
    send,
    active: () => active,
    progress: () => {},
    completed: async () => {},
  });
  expect(send).toHaveBeenCalledTimes(1);
  const fail = vi.fn(async () => {
    throw new ApiError("uncertain", 503);
  });
  await expect(
    runImageJobs("1", jobs, {
      send: fail,
      active: () => true,
      progress: () => {},
      completed: async () => {},
    }),
  ).rejects.toThrow("Clan 0: uncertain");
  expect(fail).toHaveBeenCalledTimes(1);
});
it("failed edits retry the existing message; only a deleted message becomes a new post", () => {
  const d = data();
  d.published!.version = 2;
  d.posts = [
    row(0, {
      status: "failed",
      operation: "update",
      error: "Discord unavailable",
    }),
  ];
  expect(imageJobs(d, "lazy", "new", true)[0]).toMatchObject({
    operation: "update",
    channel: "123",
  });
  d.posts[0].error = "Message was deleted in Discord";
  expect(imageJobs(d, "lazy", "new", true)[0]).toMatchObject({
    operation: "post",
    channel: "new",
  });
});
