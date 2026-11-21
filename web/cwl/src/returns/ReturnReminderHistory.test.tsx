// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ReturnReminderHistory from "./ReturnReminderHistory";
import { api, ApiError } from "../api";
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  api: vi.fn(),
}));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const denied = vi.fn();
const record = (i: number) => ({
  id: `batch${i}`,
  label: `Send return reminders · ${20 - i} Nov UTC`,
  endpoint: `/manage/return-batches/batch${i}`,
});
const result = {
  status: "done",
  message: "1 completed · 0 failed",
  result: { details: "Sample clan: Completed" },
};
const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  denied.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const render = async (active = true) => {
  await act(async () =>
    root.render(
      <ReturnReminderHistory
        active={active}
        disabled={false}
        onOpen={vi.fn()}
        onAccessLost={denied}
      />,
    ),
  );
};
it("loads nothing while closed, then only five visible details and locally reveals at most20", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/manage/return-batches"
      ? { documents: Array.from({ length: 20 }, (_, i) => record(i)) }
      : (result as never),
  );
  await render(false);
  expect(api).not.toHaveBeenCalled();
  await render();
  expect(host.querySelectorAll("article")).toHaveLength(5);
  expect(
    vi.mocked(api).mock.calls.filter(([p]) => p.endsWith("/status")),
  ).toHaveLength(5);
  for (let i = 0; i < 3; i++)
    await act(async () => button("Show more").click());
  expect(host.querySelectorAll("article")).toHaveLength(20);
  expect(host.querySelector("article h3")?.textContent).toContain("20 Nov UTC");
  expect(
    vi.mocked(api).mock.calls.filter(([p]) => p.endsWith("/status")),
  ).toHaveLength(20);
  expect(
    vi.mocked(api).mock.calls.filter(([p]) => p === "/manage/return-batches"),
  ).toHaveLength(1);
  expect(button("Show more")).toBeUndefined();
  expect(host.textContent).toContain("Latest 20 staff actions.");
  expect(host.querySelector("h2")).toBeNull();
  expect(
    vi
      .mocked(api)
      .mock.calls.every(([, method]) => !method || method === "GET"),
  ).toBe(true);
});
it("ignores an abandoned list response without requesting hidden details", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }) as never,
  );
  await render();
  await render(false);
  await act(async () =>
    finish({ documents: [{ ...record(0), label: "Secret late row" }] }),
  );
  expect(host.textContent).not.toContain("Secret late row");
  expect(api).toHaveBeenCalledTimes(1);
});
it("clears protected history on403 and ignores other late detail responses", async () => {
  let late!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/manage/return-batches")
      return { documents: [record(0), record(1)] } as never;
    if (path.includes("batch0")) throw new ApiError("Access lost", 403);
    return new Promise((resolve) => {
      late = resolve;
    }) as never;
  });
  await render();
  await act(async () =>
    late({
      status: "done",
      message: "Secret late result",
      result: { details: "Private clan" },
    }),
  );
  expect(denied).toHaveBeenCalledOnce();
  expect(host.querySelectorAll("article")).toHaveLength(0);
  expect(host.textContent).not.toContain("Private clan");
});
it("renders upstream text as text and keeps a partial detail failure discoverable", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/manage/return-batches")
      return { documents: [record(0), record(1)] } as never;
    if (path.includes("batch1")) throw new Error("Result read failed");
    return {
      status: "done",
      message: "<img src=x onerror=bad>",
      result: { details: "<script>bad()</script>" },
    } as never;
  });
  await render();
  expect(host.querySelector("img, script")).toBeNull();
  expect(host.textContent).toContain("<script>bad()</script>");
  expect(host.textContent).toContain("Result read failed");
});
it("rejects malformed endpoint metadata without making another API request", async () => {
  vi.mocked(api).mockResolvedValue({
    documents: [{ ...record(0), endpoint: "https://example.com/private" }],
  } as never);
  await render();
  expect(api).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Return action history is unavailable");
});

it("clears mounted cached history when another protected read loses access, without retrying", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/manage/return-batches"
      ? { documents: [record(0)] }
      : (result as never),
  );
  await render();
  expect(host.querySelectorAll("article")).toHaveLength(1);
  await render(false);
  const reads = vi.mocked(api).mock.calls.length;
  await act(async () =>
    root.render(
      <ReturnReminderHistory
        active={false}
        disabled={false}
        accessRevision={1}
        onOpen={vi.fn()}
        onAccessLost={denied}
      />,
    ),
  );
  expect(host.querySelectorAll("article")).toHaveLength(0);
  expect(api).toHaveBeenCalledTimes(reads);
});

it("uses singular checking grammar without changing plural result counts", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/manage/return-batches"
      ? { documents: [record(0), record(1)] }
      : ({
          status: "done",
          message: path.includes("batch0")
            ? "1 completed · 1 need checking"
            : "1 completed · 11 need checking",
        } as never),
  );
  await render();
  expect(host.textContent).toContain("1 completed · 1 needs checking");
  expect(host.textContent).toContain("1 completed · 11 need checking");
});
