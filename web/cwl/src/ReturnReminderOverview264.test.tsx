// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ReturnReminderOverview from "./ReturnReminderOverview";
import ReturnReminderStatus from "./returns/ReturnReminderStatus";
import { api, ApiError } from "./api";
import type { ReturnClan } from "./returns/model";
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
const row = (name: string, state = "scheduled"): ReturnClan => ({
  id: `FWA#${name}`,
  label: name,
  clan_name: name,
  clan_tag: `#${name}`,
  return_section: "FWA",
  group: "War",
  endpoint: "/fixture",
  description: "Fixture",
  return_status: {
    state,
    label: state === "paused" ? "Paused" : "Running",
    players: 4,
    every_minutes: 60,
    last_sent_at: null,
    expires_at: null,
  },
});
const main: ReturnClan = {
  ...row("Main"),
  id: "MAIN#M",
  return_section: "MAIN",
  clan_tag: "#M",
  return_status: {
    ...row("Main").return_status!,
    state: "manual",
    label: "Manual sends",
  },
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const getButton = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === label,
  )!;
const tab = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(
    (b) => b.textContent === label,
  )!;
const render = async () => {
  await act(async () =>
    root.render(<ReturnReminderOverview onOpen={vi.fn()} />),
  );
};
function mockRows(rows: ReturnClan[]) {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === "POST")
      return { status: "done", message: "Paused" } as never;
    if (path === "/manage/return-reminders")
      return { documents: rows } as never;
    if (path === "/manage/return-channels")
      return {
        fields: [
          { key: "fwa_channel_id", value: "1" },
          { key: "main_channel_id", value: "2" },
        ],
      } as never;
    if (path === "/announcement-channels")
      return {
        channels: [
          { id: "1", name: "FWA returns" },
          { id: "2", name: "Main returns" },
        ],
      } as never;
    if (path.startsWith("/manage/return-bulk/"))
      return {
        revision: "r264",
        fields: [
          {
            key: "clans",
            options: rows
              .filter((r) => r.return_section === "FWA")
              .map((r) => ({ value: `FWA:${r.clan_tag}` })),
          },
        ],
      } as never;
    throw new Error(`Unlisted fixture ${path}`);
  });
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("global Pause ignores current Main pool/search/selection and confirms all eligible FWA clans once", async () => {
  mockRows([row("A"), row("B"), main]);
  await render();
  const pool = [
    ...host.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Home clan type"] button',
    ),
  ].find((b) => b.textContent?.includes("Main"))!;
  await act(async () => pool.click());
  const search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(search, "Main");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Pause return reminders for all eligible FWA clans"]',
      )!
      .click(),
  );
  expect(
    vi.mocked(api).mock.calls.some(([, method]) => method === "POST"),
  ).toBe(false);
  expect(
    host.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  ).not.toHaveLength(0);
  expect(
    [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].every(
      (b) => b.disabled,
    ),
  ).toBe(true);
  await act(async () => getButton("Review action").click());
  const confirm = getButton("Pause for 2 clans");
  expect(confirm).toBeDefined();
  expect(document.querySelector("dialog")?.textContent).toContain("A, B");
  await act(async () => {
    confirm.click();
    confirm.click();
  });
  const posts = vi
    .mocked(api)
    .mock.calls.filter(([, method]) => method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/manage/return-bulk/pause/run");
  expect(posts[0][2]).toMatchObject({
    revision: "r264",
    values: { clans: ["FWA:#A", "FWA:#B"] },
  });
  expect(typeof (posts[0][2] as { request_id: string }).request_id).toBe(
    "string",
  );
  expect(posts[0][0]).not.toContain("season");
});
it("shows Paused and opens the existing Resume review for all paused FWA clans", async () => {
  mockRows([row("A", "paused"), row("B", "paused"), main]);
  await render();
  expect(
    host.querySelector(".return-scheduling-status")?.textContent,
  ).toContain("Paused");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Resume return reminders for all eligible FWA clans"]',
      )!
      .click(),
  );
  expect(api).toHaveBeenCalledWith("/manage/return-bulk/resume");
  expect(
    vi.mocked(api).mock.calls.some(([, method]) => method === "POST"),
  ).toBe(false);
});
it("keeps the Message tab read-only and preserves clan selection when returning", async () => {
  mockRows([row("A")]);
  await render();
  await act(async () =>
    host.querySelector<HTMLInputElement>('[aria-label="Select A"]')!.click(),
  );
  const reads = vi.mocked(api).mock.calls.length;
  await act(async () => tab("Message").click());
  const panel = host.querySelector(
    '[aria-labelledby="return-sections-tab-message"]',
  )!;
  expect(panel.textContent).toContain("#FWA returns");
  expect(panel.textContent).toContain("#Main returns");
  expect(panel.textContent).toContain("Message text is not editable");
  expect(panel.querySelector("h2")).toBeNull();
  expect(panel.querySelector("input,textarea,button")).toBeNull();
  expect(api).toHaveBeenCalledTimes(reads);
  await act(async () => tab("Clans").click());
  expect(
    host.querySelector<HTMLInputElement>('[aria-label="Select A"]')!.checked,
  ).toBe(true);
});

it("honors the existing50-clan boundary without starting a write", async () => {
  const onAction = vi.fn();
  await act(async () =>
    root.render(
      <ReturnReminderStatus
        clans={Array.from({ length: 51 }, (_, i) => row(String(i)))}
        loading={false}
        error=""
        busy={false}
        onAction={onAction}
      />,
    ),
  );
  const button = host.querySelector("button")!;
  expect(button.disabled).toBe(true);
  button.click();
  expect(onAction).not.toHaveBeenCalled();
});
it("clears clan and destination data when history loses permission", async () => {
  mockRows([row("Private clan")]);
  await render();
  vi.mocked(api).mockRejectedValue(new ApiError("Access lost", 403));
  await act(async () => tab("History").click());
  expect(host.textContent).not.toContain("Private clan");
  await act(async () => tab("Message").click());
  expect(host.textContent).not.toContain("#FWA returns");
  expect(
    host.querySelector(".return-scheduling-status")?.textContent,
  ).toContain("Status unavailable");
});
