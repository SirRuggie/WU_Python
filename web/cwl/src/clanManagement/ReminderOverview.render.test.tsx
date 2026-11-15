// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ReminderOverview from "./ReminderOverview";
import { api } from "../api";
vi.mock("../api", () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));
const { ApiError } = await import("../api");
const settings = {
  enabled: true,
  channel_id: "323456789012345678",
  minutes: [60],
  war_started: true,
  audience: "remaining" as const,
};
const row = (
  tag: string,
  name: string,
  over: Record<string, unknown> = {},
) => ({
  clan: { tag, name, type: "CWL" },
  settings,
  revision: `rev-${tag}`,
  health: { category: "tracking", label: "Monitoring", detail: "" },
  checked_at: null,
  last_delivery: null,
  ...over,
});
const off = { ...settings, enabled: false };
const unset = { ...settings, enabled: false, channel_id: "" };
const rows = () => [
  row("#AAA", "Alpha"),
  row("#BBB", "Quiet clan", {
    settings: off,
    health: { category: "off", label: "Off", detail: "" },
  }),
  row("#CCC", "Fresh clan", {
    settings: unset,
    clan: { tag: "#CCC", name: "Fresh clan", type: "FWA" },
    health: { category: "not_configured", label: "Not configured", detail: "" },
  }),
  row("#DDD", "Review clan", {
    health: {
      category: "attention",
      label: "Uncertain delivery",
      detail: "Check the channel before acting",
    },
  }),
];
let host: HTMLDivElement, root: Root;
const onOpen = vi.fn();
const channels = [{ id: settings.channel_id, name: "war-room", type: 0 }];
async function render(list = rows(), channelList = channels) {
  vi.mocked(api).mockImplementation(async (path: string, method?: string) => {
    if (path.endsWith("/overview"))
      return { clans: list, generated_at: "2026-11-15T12:00:00Z" };
    throw new Error(`Unmocked ${method} ${path}`);
  });
  await act(async () =>
    root.render(
      <ReminderOverview
        active
        channels={channelList}
        channelsReady
        choicesError=""
        onRetryChoices={vi.fn()}
        onOpen={onOpen}
        returnTag={null}
        onAdd={vi.fn()}
      />,
    ),
  );
}
const li = (name: string) =>
  [...host.querySelectorAll("li.overview-row")].find((item) =>
    item.textContent?.includes(name),
  )!;
const sw = (name: string) =>
  li(name).querySelector<HTMLInputElement>('input[role="switch"]')!;
const button = (scope: ParentNode, text: string) =>
  [...scope.querySelectorAll("button")].find(
    (b) => b.textContent?.replace(/\s+/g, " ").trim() === text,
  ) as HTMLButtonElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) =>
    setTimeout(() => fn(0), 0),
  );
  vi.mocked(api).mockReset();
  onOpen.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("lists every clan with a channel with a switch and the rest with Set up", async () => {
  await render();
  expect(host.querySelectorAll("li.overview-row")).toHaveLength(4);
  expect(sw("Alpha").checked).toBe(true);
  expect(sw("Alpha").getAttribute("aria-label")).toBe(
    "War reminders for Alpha",
  );
  expect(sw("Quiet clan").checked).toBe(false);
  expect(li("Quiet clan").textContent).toContain("#war-room");
  expect(li("Quiet clan").textContent).toContain("· saved");
  expect(li("Quiet clan").classList.contains("is-off")).toBe(true);
  expect(li("Fresh clan").querySelector('input[role="switch"]')).toBeNull();
  expect(button(li("Fresh clan"), "Set up")).toBeTruthy();
  expect(button(li("Alpha"), "Edit")).toBeTruthy();
  expect(host.textContent).toContain("Check the channel before acting");
  act(() => button(li("Fresh clan"), "Set up").click());
  expect(onOpen).toHaveBeenCalledWith({
    tag: "#CCC",
    name: "Fresh clan",
    type: "FWA",
  });
  expect(host.textContent).not.toContain("Refresh overview");
  expect(host.textContent).not.toContain("the bot");
});

it("never shows a raw channel ID and asks for a new channel when it is missing", async () => {
  await render(rows(), []);
  expect(host.textContent).toContain("Channel missing · select a new one");
  expect(host.textContent).not.toContain(settings.channel_id);
  expect(button(li("Alpha"), "Review")).toBeTruthy();
  expect(button(li("Quiet clan"), "Review")).toBeTruthy();
});

it("shows a red problem switch for a clan that needs attention", async () => {
  await render();
  expect(li("Review clan").querySelector(".wu-switch")!.classList).toContain(
    "is-problem",
  );
  expect(li("Alpha").querySelector(".wu-switch")!.classList).not.toContain(
    "is-problem",
  );
});

it("turns reminders on at once with the saved revision and keeps the response", async () => {
  await render();
  let release: (value: unknown) => void = () => {};
  vi.mocked(api).mockImplementationOnce(
    () => new Promise((resolve) => (release = resolve)),
  );
  act(() => sw("Quiet clan").click());
  expect(sw("Quiet clan").checked).toBe(true);
  expect(sw("Quiet clan").disabled).toBe(true);
  expect(sw("Alpha").disabled).toBe(false);
  expect(api).toHaveBeenLastCalledWith(
    "/manage/clans/%23BBB/war-reminders",
    "PUT",
    { settings: { ...settings, enabled: true }, revision: "rev-#BBB" },
  );
  await act(async () =>
    release({
      settings: { ...settings, enabled: true },
      revision: "rev-new",
      history: [],
    }),
  );
  expect(sw("Quiet clan").checked).toBe(true);
  expect(sw("Quiet clan").disabled).toBe(false);
  expect(li("Quiet clan").classList.contains("is-off")).toBe(false);
  vi.mocked(api).mockResolvedValueOnce({
    settings: off,
    revision: "rev-newer",
    history: [],
  });
  await act(async () => sw("Quiet clan").click());
  expect(api).toHaveBeenLastCalledWith(
    "/manage/clans/%23BBB/war-reminders",
    "PUT",
    { settings: off, revision: "rev-new" },
  );
});

it("rolls the switch back and shows the error under that row when saving fails", async () => {
  await render();
  vi.mocked(api).mockRejectedValueOnce(new Error("Select a channel first."));
  await act(async () => sw("Quiet clan").click());
  expect(sw("Quiet clan").checked).toBe(false);
  const alert = li("Quiet clan").querySelector('[role="alert"]')!;
  expect(alert.textContent).toBe("Select a channel first.");
  expect(li("Alpha").querySelector('[role="alert"]')).toBeNull();
});

it("reloads the overview and shows the server message on a conflict", async () => {
  await render();
  const fresh = rows();
  fresh[1] = row("#BBB", "Quiet clan", {
    settings: { ...off, minutes: [30] },
    revision: "rev-server",
    health: { category: "off", label: "Off", detail: "" },
  });
  vi.mocked(api)
    .mockRejectedValueOnce(
      new ApiError("Reminders changed. Reload before saving.", 409),
    )
    .mockResolvedValueOnce({
      clans: fresh,
      generated_at: "2026-11-15T12:01:00Z",
    });
  await act(async () => sw("Quiet clan").click());
  expect(sw("Quiet clan").checked).toBe(false);
  expect(li("Quiet clan").textContent).toContain(
    "Reminders changed. Reload before saving.",
  );
  expect(li("Quiet clan").textContent).toContain("30m before end");
  expect(vi.mocked(api).mock.calls.at(-1)![0]).toBe(
    "/manage/war-reminders/overview",
  );
});

it("does not let the 30 second refresh overwrite a row with a save in flight", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await render();
    let release: (value: unknown) => void = () => {};
    vi.mocked(api).mockImplementationOnce(
      () => new Promise((resolve) => (release = resolve)),
    );
    act(() => sw("Quiet clan").click());
    vi.mocked(api).mockResolvedValueOnce({
      clans: rows(),
      generated_at: "2026-11-15T12:01:00Z",
    });
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    expect(vi.mocked(api).mock.calls.at(-1)![0]).toBe(
      "/manage/war-reminders/overview",
    );
    expect(sw("Quiet clan").checked).toBe(true);
    await act(async () =>
      release({
        settings: { ...settings, enabled: true },
        revision: "rev-new",
        history: [],
      }),
    );
    expect(sw("Quiet clan").checked).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("drops a refresh that started before a toggle and ended after it", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await render();
    let finishLoad: (value: unknown) => void = () => {};
    vi.mocked(api).mockImplementationOnce(
      () => new Promise((resolve) => (finishLoad = resolve)),
    );
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    vi.mocked(api).mockResolvedValueOnce({
      settings: { ...settings, enabled: true },
      revision: "rev-new",
      history: [],
    });
    await act(async () => sw("Quiet clan").click());
    expect(sw("Quiet clan").checked).toBe(true);
    await act(async () =>
      finishLoad({ clans: rows(), generated_at: "2026-11-15T12:01:00Z" }),
    );
    expect(sw("Quiet clan").checked).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("filters through one panel with Type and Status counts, chips and Clear all", async () => {
  await render();
  expect(host.querySelector(".overview-applied")).toBeNull();
  expect(host.textContent).toContain("4 of 4 clans");
  expect(host.textContent).not.toContain("Refresh overview");
  expect(host.querySelector(".clan-category-filters")).toBeNull();
  await act(async () => button(host, "Filters").click());
  const panel = document.querySelector("dialog")!;
  expect(panel.textContent).toContain("Filter clans");
  const group = (name: string) =>
    panel.querySelector(`[aria-label="${name}"]`)!;
  const labels = (name: string) =>
    [...group(name).querySelectorAll("button")].map((b) =>
      b.textContent?.replace(/\s+/g, " ").trim(),
    );
  expect(labels("Clan type")).toEqual(["All 4", "CWL 3", "FWA 1"]);
  expect(labels("Reminder status")).toEqual([
    "All 4",
    "Needs attention 1",
    "On 2",
    "Off 1",
    "Not set up 1",
  ]);
  await act(async () => button(group("Reminder status"), "Off 1").click());
  expect(labels("Clan type")).toEqual(["All 1", "CWL 1", "FWA 0"]);
  expect(panel.querySelector("[role=status]")!.textContent).toBe("1 clans");
  // A draft changes nothing until Apply.
  expect(host.textContent).toContain("4 of 4 clans");
  await act(async () => button(panel, "Reset").click());
  expect(panel.querySelector("[role=status]")!.textContent).toBe("4 clans");
  await act(async () =>
    button(group("Reminder status"), "Not set up 1").click(),
  );
  await act(async () => button(panel, "Apply").click());
  expect(document.querySelector("dialog")).toBeNull();
  expect(host.textContent).toContain("1 of 4 clans");
  expect(host.querySelectorAll("li.overview-row")).toHaveLength(1);
  expect(button(host, "Filters · 1")).toBeTruthy();
  const chips = [...host.querySelectorAll(".overview-applied button")].map(
    (b) => b.textContent?.replace(/\s+/g, " ").trim(),
  );
  expect(chips).toEqual(["Not set up ✕", "Clear all"]);
  await act(async () => button(host, "Not set up ✕").click());
  expect(host.querySelector(".overview-applied")).toBeNull();
  expect(host.querySelectorAll("li.overview-row")).toHaveLength(4);
  await act(async () => button(host, "Filters").click());
  const again = document.querySelector("dialog")!;
  await act(async () =>
    button(again.querySelector('[aria-label="Clan type"]')!, "FWA 1").click(),
  );
  await act(async () => button(again, "Apply").click());
  expect(host.querySelectorAll("li.overview-row")).toHaveLength(1);
  await act(async () => button(host, "Clear all").click());
  expect(host.querySelectorAll("li.overview-row")).toHaveLength(4);
  expect(host.querySelector(".overview-applied")).toBeNull();
});

it("finds a clan by name and keeps the placeholder with an ellipsis", async () => {
  await render();
  const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  expect(input.placeholder).toBe("Clan name, tag or channel…");
  expect(host.textContent).toContain("Find a clan");
});
