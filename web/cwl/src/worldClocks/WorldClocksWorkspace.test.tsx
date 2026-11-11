// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import {
  searchZones,
  statusCounts,
  type WorldClock,
  type WorldClocksData,
} from "./worldClocksModel";

const transport = vi.hoisted(() => vi.fn());
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  api: transport,
}));
import WorldClocksWorkspace from "./WorldClocksWorkspace";

function clock(id: string, values: Partial<WorldClock> = {}): WorldClock {
  return {
    id,
    zone: "America/New_York",
    flag: "🇺🇸",
    code: null,
    code_auto: "EST",
    flag_auto: "🇺🇸",
    needs_code: false,
    channel_id: `9000000000000000${id.length}${id.charCodeAt(0)}`,
    channel_name: "old",
    channel_missing: false,
    enabled: true,
    revision: "1",
    last_name: "🇺🇸 EST GMT-5 · 9:24pm",
    last_renamed_at: "2026-11-11T02:24:00+00:00",
    status: "ok",
    status_detail: "",
    name_now: "🇺🇸 EST GMT-5 · 9:30pm",
    name_other: "🇺🇸 EDT GMT-4",
    offset_minutes: -300,
    ...values,
  };
}

function data(clocks: WorldClock[]): WorldClocksData {
  return {
    settings: {
      category_id: "900000000000000001",
      time_format: "12h",
      interval_minutes: 6,
      revision: "1",
    },
    clocks,
    channels_available: true,
    categories: [{ id: "900000000000000001", name: "⏳ ⇒ Live World Times" }],
    voice_channels: clocks
      .map((row) => ({
        id: row.channel_id!,
        name: row.channel_name || "x",
        category: "Times",
        used: true,
      }))
      .concat([
        {
          id: "900000000000000050",
          name: "Spare",
          category: "Times",
          used: false,
        },
      ]),
    chips: [
      { label: "New York", zone: "America/New_York", flag: "🇺🇸" },
      { label: "Jakarta", zone: "Asia/Jakarta", flag: "🇮🇩" },
    ],
    now: "2026-11-11T02:31:00+00:00",
    next_update: "2026-11-11T02:36:00+00:00",
    runs: [
      {
        at: "2026-11-11T02:30:00+00:00",
        renamed: 7,
        unchanged: 0,
        waited: 1,
        problem: 1,
        moved: false,
      },
    ],
    max_clocks: 25,
  };
}

const NINE = [
  clock("a"),
  clock("b", { zone: "Europe/London", name_now: "🇬🇧 GMT · 2:30am" }),
  clock("c"),
  clock("d"),
  clock("e"),
  clock("f"),
  clock("g"),
  clock("h", {
    zone: "Asia/Manila",
    name_now: "🇵🇭 PHT GMT+8 · 10:30am",
    channel_missing: true,
    channel_name: null,
  }),
  clock("i", {
    zone: "Australia/Sydney",
    enabled: false,
    last_name: "🇦🇺 AEDT GMT+11 · 1:00pm",
  }),
];

let root: Root | undefined;
let host: HTMLDivElement;

async function render(
  payload: WorldClocksData,
  handler?: (path: string, method: string, body: unknown) => unknown,
) {
  transport.mockImplementation(
    async (path: string, method = "GET", body?: unknown) => {
      if (handler) {
        const result = await handler(path, method, body);
        if (result !== undefined) return result;
      }
      if (path === "/manage/world-clocks" && method === "GET") return payload;
      if (path.endsWith("/preview"))
        return {
          code_auto: "WIB",
          flag_auto: "🇮🇩",
          needs_code: false,
          name_now: "🇮🇩 WIB GMT+7 · 9:30am",
          name_other: null,
        };
      if (path.endsWith("/zones")) return { zones: [] };
      throw new Error(`unexpected ${method} ${path}`);
    },
  );
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(<WorldClocksWorkspace />));
  await act(async () => {});
}

function button(text: string, scope: ParentNode = document) {
  return Array.from(scope.querySelectorAll("button")).find(
    (node) => node.textContent?.trim() === text,
  ) as HTMLButtonElement | undefined;
}

async function click(node: Element | null | undefined) {
  await act(async () => (node as HTMLElement).click());
  await act(async () => {});
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  transport.mockReset();
  document.body.innerHTML = "";
});

it("counts states honestly and never shows a problem as a green switch", async () => {
  await render(data(NINE));
  expect(host.querySelector(".world-clock-status")?.textContent).toContain(
    "7 updating · 1 with a problem · 1 off",
  );
  const problemRow = host.querySelector(".world-clock-row.is-problem")!;
  expect(
    problemRow
      .querySelector(".world-clock-switch")
      ?.classList.contains("is-problem"),
  ).toBe(true);
  expect(problemRow.textContent).toContain("Channel missing");
  expect(button("Fix", problemRow)).toBeTruthy();
  const offRow = host.querySelector(".world-clock-row.is-off")!;
  expect(offRow.textContent).toContain(
    "Off · frozen as 🇦🇺 AEDT GMT+11 · 1:00pm",
  );
  expect(
    host.querySelector(".world-clock-discord li.is-missing")?.textContent,
  ).toContain("Missing channel");
  expect(host.querySelector(".world-clock-history")?.textContent).toContain(
    "1 waited (Discord limit)",
  );
});

it("the alert Fix button opens the broken clock at its channel field", async () => {
  await render(data(NINE));
  await click(button("Fix", host.querySelector(".world-clock-alert")!));
  const open = host.querySelector(".world-clock-row.is-open")!;
  expect(open.classList.contains("is-problem")).toBe(true);
  expect(
    document.activeElement?.classList.contains("search-picker-trigger"),
  ).toBe(true);
});

it("a switch saves at once with the clock revision", async () => {
  const calls: unknown[] = [];
  await render(data([clock("a")]), (path, method, body) => {
    if (method === "PATCH") {
      calls.push([path, body]);
      return {
        clock: clock("a", { enabled: false, revision: "2" }),
        next_update: "2026-11-11T02:36:00+00:00",
      };
    }
  });
  const toggle = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  await click(toggle);
  expect(calls).toEqual([
    ["/manage/world-clocks/a", { revision: "1", enabled: false }],
  ]);
  expect(
    host.querySelector<HTMLInputElement>('input[role="switch"]')!.checked,
  ).toBe(false);
});

it("a failed switch goes back and shows the error", async () => {
  await render(data([clock("a")]), (_path, method) => {
    if (method === "PATCH") throw new ApiError("Discord is unavailable.", 503);
  });
  await click(host.querySelector('input[role="switch"]'));
  expect(
    host.querySelector<HTMLInputElement>('input[role="switch"]')!.checked,
  ).toBe(true);
  expect(host.textContent).toContain("Discord is unavailable.");
});

it("a conflicting switch reloads the list with a message", async () => {
  let reads = 0;
  await render(data([clock("a")]), (_path, method) => {
    if (method === "GET" && _path === "/manage/world-clocks") reads += 1;
    if (method === "PATCH")
      throw new ApiError(
        "This clock changed. The page shows the new version.",
        409,
      );
  });
  await click(host.querySelector('input[role="switch"]'));
  expect(reads).toBe(2);
  expect(host.querySelector(".world-clock-notice")?.textContent).toContain(
    "This clock changed",
  );
});

it("shows one solid gold button at a time", async () => {
  await render(data([clock("a")]));
  expect(host.querySelectorAll(".roster-ui-button.is-primary")).toHaveLength(1);
  await click(button("Edit"));
  const primaries = host.querySelectorAll(".roster-ui-button.is-primary");
  expect(primaries).toHaveLength(1);
  expect(primaries[0].textContent).toBe("Save");
  expect((primaries[0] as HTMLButtonElement).disabled).toBe(true); // Nothing changed yet.
  expect(button("Edit") ?? button("Close")).toBeTruthy();
  expect(button("Close")!.getAttribute("aria-expanded")).toBe("true");
});

it("remove asks first, names the channel it deletes, then reports it", async () => {
  const calls: unknown[] = [];
  await render(data([clock("a")]), (path, method, body) => {
    if (method === "DELETE") {
      calls.push([path, body]);
      return { removed: "a", channel: "deleted" };
    }
  });
  await click(button("Edit"));
  await click(button("Remove clock"));
  expect(document.body.textContent).toContain(
    "This deletes the voice channel old in Discord",
  );
  expect(document.body.textContent).toContain("turn the clock off instead");
  expect(calls).toHaveLength(0);
  const dialog = document.querySelector(".confirm-dialog")!;
  await click(button("Remove clock", dialog));
  expect(calls).toEqual([["/manage/world-clocks/a", { revision: "1" }]]);
  expect(host.querySelector(".world-clock-notice")?.textContent).toBe(
    "Clock and channel removed.",
  );
});

it("a remove that Discord refuses keeps the clock open with the error", async () => {
  await render(data([clock("a")]), (_path, method) => {
    if (method === "DELETE")
      throw new ApiError(
        "Discord did not confirm the delete. The clock was not removed. Check Discord, then press Remove again.",
        503,
      );
  });
  await click(button("Edit"));
  await click(button("Remove clock"));
  await click(
    button("Remove clock", document.querySelector(".confirm-dialog")!),
  );
  expect(host.querySelector(".world-clock-row.is-open")).toBeTruthy();
  expect(host.textContent).toContain("The clock was not removed.");
});

it("add clock sends one request per press and keeps the id after an unconfirmed create", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const posts: { request_id: string }[] = [];
  await render(data([]), (path, method, body) => {
    if (path === "/manage/world-clocks" && method === "POST") {
      posts.push(body as { request_id: string });
      throw new ApiError("Discord did not confirm the new channel.", 503);
    }
  });
  expect(host.textContent).toContain("No clocks yet.");
  await click(button("+ Add clock"));
  const sheet = document.querySelector(".world-clock-sheet")!;
  const create = button("Create channel and add", sheet)!;
  expect(create.disabled).toBe(true);
  await click(
    Array.from(sheet.querySelectorAll("button")).find((node) =>
      node.textContent?.includes("Jakarta"),
    ),
  );
  await act(async () => {
    vi.advanceTimersByTime(400);
  });
  expect(sheet.textContent).toContain("🇮🇩 WIB GMT+7 · 9:30am");
  expect(button("Create channel and add", sheet)!.disabled).toBe(false);
  await click(button("Create channel and add", sheet));
  await click(button("Create channel and add", sheet));
  expect(posts).toHaveLength(2);
  expect(posts[0].request_id).toBe(posts[1].request_id);
  expect(sheet.textContent).toContain(
    "Discord did not confirm the new channel.",
  );
});

it("add clock keeps the id after a network error and renews it only after a refusal", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const posts: { request_id: string }[] = [];
  const errors = [
    new ApiError("Network error.", 0),
    new ApiError("Discord is unavailable.", 502),
    new ApiError("Check the clock settings.", 400),
    new ApiError("Check the clock settings.", 400),
  ];
  await render(data([]), (path, method, body) => {
    if (path === "/manage/world-clocks" && method === "POST") {
      posts.push(body as { request_id: string });
      throw errors.shift();
    }
  });
  await click(button("+ Add clock"));
  const sheet = document.querySelector(".world-clock-sheet")!;
  await click(
    Array.from(sheet.querySelectorAll("button")).find((node) =>
      node.textContent?.includes("Jakarta"),
    ),
  );
  await act(async () => {
    vi.advanceTimersByTime(400);
  });
  for (let press = 0; press < 4; press += 1)
    await click(button("Create channel and add", sheet));
  const ids = posts.map((post) => post.request_id);
  expect(ids[0]).toBe(ids[1]);
  expect(ids[1]).toBe(ids[2]);
  expect(ids[3]).not.toBe(ids[2]);
});

it("turning an open clock off keeps its unsaved edits", async () => {
  await render(data([clock("a")]), (_path, method) => {
    if (method === "PATCH")
      return {
        clock: clock("a", { enabled: false, revision: "2" }),
        next_update: "2026-11-11T02:36:00+00:00",
      };
  });
  await click(button("Edit"));
  const code = Array.from(
    host.querySelectorAll<HTMLInputElement>(".world-clock-row.is-open input"),
  ).find(
    (input) => input.getAttribute("role") !== "switch" && input.maxLength === 6,
  )!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(code, "NYC");
    code.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click(host.querySelector('input[role="switch"]'));
  const after = Array.from(
    host.querySelectorAll<HTMLInputElement>(".world-clock-row.is-open input"),
  ).find(
    (input) => input.getAttribute("role") !== "switch" && input.maxLength === 6,
  );
  expect(after?.value).toBe("NYC");
});

it("zone search finds codes and puts common cities first", () => {
  const rows = [
    {
      zone: "America/Belize",
      city: "Belize",
      region: "America",
      flag: "🇧🇿",
      offset: "GMT-6",
      codes: ["CST"],
    },
    {
      zone: "America/Chicago",
      city: "Chicago",
      region: "America",
      flag: "🇺🇸",
      offset: "GMT-6",
      codes: ["CST", "CDT"],
    },
    {
      zone: "Asia/Shanghai",
      city: "Shanghai",
      region: "Asia",
      flag: "🇨🇳",
      offset: "GMT+8",
      codes: ["CST"],
    },
    {
      zone: "Europe/Budapest",
      city: "Budapest",
      region: "Europe",
      flag: "🇭🇺",
      offset: "GMT+1",
      codes: ["CET", "CEST"],
    },
    {
      zone: "America/New_York",
      city: "New York",
      region: "America",
      flag: "🇺🇸",
      offset: "GMT-5",
      codes: ["EST", "EDT"],
    },
  ];
  const chips = ["America/New_York", "America/Chicago"];
  expect(searchZones(rows, "CST", 8, chips).map((row) => row.zone)).toEqual([
    "America/Chicago",
    "America/Belize",
    "Asia/Shanghai",
  ]);
  expect(searchZones(rows, "cdt", 8, chips).map((row) => row.zone)).toEqual([
    "America/Chicago",
  ]);
  // "est" is inside "Budapest", but the exact code match comes first.
  expect(searchZones(rows, "est", 8, chips).map((row) => row.zone)).toEqual([
    "America/New_York",
    "Europe/Budapest",
  ]);
});

it("the category picker is searchable and saves only on Save", async () => {
  const puts: unknown[] = [];
  const payload = data([clock("a")]);
  payload.categories = [
    { id: "900000000000000001", name: "⏳ ⇒ Live World Times" },
    { id: "900000000000000009", name: "Voice Lounge" },
  ];
  await render(payload, (path, method, body) => {
    if (path.endsWith("/settings") && method === "PUT") {
      puts.push(body);
      return {
        settings: {
          ...payload.settings,
          category_id: "900000000000000009",
          revision: "2",
        },
      };
    }
  });
  await click(button("Settings"));
  const trigger = host.querySelector<HTMLButtonElement>(
    ".search-picker-trigger",
  )!;
  expect(trigger.textContent).toContain("Live World Times");
  expect(trigger.textContent).not.toContain("#");
  await click(trigger);
  const input = host.querySelector<HTMLInputElement>('input[role="combobox"]')!;
  expect(input.placeholder).toBe("Search categories");
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "loun");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const options = Array.from(host.querySelectorAll('[role="option"]'));
  expect(options.map((node) => node.textContent)).toEqual(["Voice Lounge"]);
  expect(host.textContent).not.toContain("900000000000000009"); // No raw ids.
  await click(options[0]);
  expect(puts).toHaveLength(0);
  await click(button("Save settings"));
  expect(puts).toEqual([
    {
      revision: "1",
      category_id: "900000000000000009",
      time_format: "12h",
      interval_minutes: 6,
    },
  ]);
});

it("add clock: a channel with a clock cannot be selected; empty zone search lists the chip cities", async () => {
  await render(data([clock("a")]));
  await click(button("+ Add clock"));
  const sheet = document.querySelector(".world-clock-sheet")!;
  await click(sheet.querySelector<HTMLButtonElement>(".search-picker-trigger"));
  const zones = Array.from(sheet.querySelectorAll('[role="option"]')).map(
    (node) => node.textContent,
  );
  expect(zones[0]).toContain("New York");
  expect(zones[0]).toContain("has a clock");
  expect(zones[1]).toContain("Jakarta");
  await act(async () => {
    sheet
      .querySelector<HTMLInputElement>('input[role="combobox"]')!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
  });
  await click(
    Array.from(sheet.querySelectorAll("label")).find((node) =>
      node.textContent?.includes("Use an existing voice channel"),
    ),
  );
  const triggers = sheet.querySelectorAll<HTMLButtonElement>(
    ".search-picker-trigger",
  );
  await click(triggers[triggers.length - 1]);
  const rows = Array.from(
    sheet.querySelectorAll<HTMLElement>('[role="option"]'),
  );
  const used = rows.find((node) => node.textContent?.includes("old"))!;
  expect(used.getAttribute("aria-disabled")).toBe("true");
  expect(used.textContent).toContain("has a clock");
  await click(used);
  expect(triggers[triggers.length - 1].textContent).toContain(
    "Select a voice channel",
  );
  expect(host.textContent + sheet.textContent).not.toContain(
    "900000000000000050",
  );
});

it("model helpers", () => {
  expect(statusCounts(NINE)).toEqual({ updating: 7, problems: 1, off: 1 });
  const rows = [
    {
      zone: "Asia/Jakarta",
      city: "Jakarta",
      region: "Asia",
      flag: "🇮🇩",
      offset: "GMT+7",
    },
    {
      zone: "America/New_York",
      city: "New York",
      region: "America",
      flag: "🇺🇸",
      offset: "GMT-5",
    },
  ];
  expect(searchZones(rows, "new york").map((row) => row.zone)).toEqual([
    "America/New_York",
  ]);
  expect(searchZones(rows, "")).toEqual([]);
});
