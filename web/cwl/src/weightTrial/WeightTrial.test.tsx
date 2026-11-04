// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WeightTrial from "./WeightTrial";
import type { Roster } from "./model";
import { api } from "../api";
import { readFileSync, readdirSync } from "node:fs";
vi.mock("../api", () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    status = 409;
  },
}));
let host: HTMLDivElement, root: Root;
const rows = [
  { tag: "#P2Y", name: "First", town_hall: 16, weight: 150000, revision: 1 },
  {
    tag: "#Q2Y",
    name: "Missing one",
    town_hall: 16,
    weight: null,
    revision: 0,
  },
  {
    tag: "#G2Y",
    name: "Missing two",
    town_hall: 16,
    weight: null,
    revision: 0,
  },
  { tag: "#C2Y", name: "Check", town_hall: 16, weight: 160000, revision: 1 },
];
const roster = {
  clan: { tag: "#R2Y", name: "Needs work" },
  members: rows,
  checked_at: "2026-10-30T12:00:00Z",
  war_order: { "#P2Y": 1, "#C2Y": 2, "#J2Y": 3, "#Q2Y": 4 },
  war_source: { state: "inWar", names: { "#J2Y": "Departed" } },
};
const onDirty = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith("/weight-trial/saved-players"))
      return {
        players: [
          {
            ...rows[0],
            name: "Saved outside",
            last_saved_clan_name: "Old clan",
            last_saved_clan_tag: "#R2Y",
            updated_at: "2026-10-29T12:00:00Z",
            current_status: "unavailable",
            current_is_family: null,
          },
        ],
        total: 1,
      };
    if (path.includes("/clans/")) return roster;
    return {
      clans: [
        {
          tag: "#R2Y",
          name: "Needs work",
          weighed_count: 2,
          members_count: 4,
          missing_count: 2,
          last_saved_at: null,
          status: "current",
        },
        {
          tag: "#J2Y",
          name: "Complete",
          weighed_count: 50,
          members_count: 50,
          missing_count: 0,
          last_saved_at: null,
          status: "current",
        },
      ],
      outside_fwa_missing_count: 2,
    };
  });
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
async function render() {
  await act(async () =>
    root.render(<WeightTrial onDirty={onDirty} seasonId="1" />),
  );
}
async function openClanPicker() {
  if (document.querySelector(".weight-clan-picker-panel")) return;
  const trigger = host.querySelector<HTMLButtonElement>(
    ".weight-trial-header .roster-menu-trigger",
  );
  expect(trigger).toBeTruthy();
  await act(async () => trigger!.click());
}
async function click(text: string, scope: ParentNode = document) {
  let target: HTMLElement | undefined = Array.from(
    scope.querySelectorAll<HTMLButtonElement>("button"),
  ).find((node) => node.textContent?.includes(text));
  if (!target && scope === document) {
    await openClanPicker();
    target = [
      ...document.querySelectorAll<HTMLElement>(
        '.weight-clan-picker-panel [role="menuitem"]',
      ),
    ].find((node) => node.textContent?.includes(text));
  }
  expect(target).toBeTruthy();
  await act(async () => {
    target!.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    target!.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, button: 0 }),
    );
    target!.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    target!.dispatchEvent(
      new MouseEvent("mouseup", { bubbles: true, button: 0 }),
    );
    target!.click();
  });
}
async function input(node: HTMLInputElement, text: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(node, text);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("opens with progress list, collapsed help and no member fanout", async () => {
  await render();
  await openClanPicker();
  expect(document.body.textContent).toContain("2/4 weighed");
  expect(document.body.textContent).toContain("50/50 weighed");
  expect(host.querySelector(".weight-trial-note")?.hasAttribute("open")).toBe(
    false,
  );
  expect(host.textContent).not.toContain("Refresh members");
  expect(
    vi.mocked(api).mock.calls.filter(([path]) => path.includes("/clans/")),
  ).toHaveLength(0);
  expect(host.textContent).toContain("2 CWL signups outside FWA clans");
});
it("filters real missing rows, keeps gaps out of counts, and moves Next focus", async () => {
  await render();
  await click("Needs work");
  expect(host.textContent).toContain("2 missing · 1 to check");
  expect(host.textContent).toContain(
    "3 · Departed · War player details unavailable",
  );
  expect(host.querySelector(".weight-trial-gap input")).toBeNull();
  await click("Missing (2)");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(2);
  expect(host.querySelector(".weight-trial-gap")).toBeNull();
  const inputs = host.querySelectorAll<HTMLInputElement>(
    ".weight-trial-loot input",
  );
  expect(inputs[0].getAttribute("enterkeyhint")).toBe("next");
  expect(inputs[1].getAttribute("enterkeyhint")).toBe("done");
  await act(async () => {
    inputs[0].focus();
    inputs[0].dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
  });
  expect(document.activeElement).toBe(inputs[1]);
  await click("Check (1)");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(1);
  expect(host.textContent).toContain("this can sometimes be correct");
});
it("uses in-app discard, restores edit focus, preserves values on cancel, executes once", async () => {
  const native = vi.fn();
  window.confirm = native;
  await render();
  await click("Needs work");
  const loot = host.querySelector<HTMLInputElement>(
    ".weight-trial-loot input",
  )!;
  await act(async () => loot.focus());
  await input(loot, "35.8k");
  await click("Refresh members");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "You have 1 unsaved weight.",
  );
  await click("Keep editing");
  expect(document.activeElement).toBe(loot);
  expect(loot.value.replace(/,/g, " ").replace(/ /g, "")).toMatch(
    /^(35\.8k|35800)$/,
  );
  await click("Refresh members");
  await click("Discard");
  expect(
    vi.mocked(api).mock.calls.filter(([path]) => path.includes("/clans/")),
  ).toHaveLength(2);
  expect(native).not.toHaveBeenCalled();
});
it("keeps phone full readout beside loot, storage picker, and fine-pointer-only hint", async () => {
  await render();
  await click("Needs work");
  expect(host.querySelector(".weight-trial-phone-full")?.textContent).toBe(
    "Full 150k",
  );
  expect(
    host
      .querySelector(".weight-trial-storages select")
      ?.querySelectorAll("option"),
  ).toHaveLength(5);
  const css = readFileSync("src/weightTrial/WeightTrial.css", "utf8");
  expect(css).toMatch(
    /@media\s*\(max-width:\s*800px\)[\s\S]*\.weight-trial-full\s*\{\s*display:\s*none/,
  );
  expect(css).toMatch(/\.weight-trial-phone-full\s*\{\s*display:\s*block/);
  expect(css).toContain("(pointer: fine)");
});
it("shows honest export checklist, missing-loot action and real clipboard failures", async () => {
  await render();
  await click("Needs work");
  expect(host.textContent).toContain("Before pasting into F17");
  expect(host.textContent).toContain("Check: Same war in the sheet");
  expect(host.textContent).toContain("1 player missing loot");
  await click("Show");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(2);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi
        .fn()
        .mockRejectedValue(new Error("Clipboard permission denied")),
    },
  });
  await click("Copy member table");
  expect(host.textContent).toContain("Copy blocked by the browser");
  expect(host.textContent).not.toContain("Clipboard permission denied");
});
it("searches saved players and labels unknown location neutrally", async () => {
  await render();
  await input(
    host.querySelector<HTMLInputElement>(".weight-saved-search input")!,
    "Saved",
  );
  await act(async () =>
    host
      .querySelector(".weight-saved-search form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(host.textContent).toContain("Last saved in Old clan");
  expect(host.textContent).toContain("Current clan unavailable");
  expect(host.textContent).not.toContain("now not in a family clan");
});

it("Next missing focuses an empty visible Loot box and nameless gaps stay excluded", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) =>
    path.includes("/clans/")
      ? { ...roster, war_source: { state: "inWar" } }
      : original(path, ...args),
  );
  await render();
  await click("Needs work");
  expect(host.textContent).toContain("3 · War player details unavailable");
  await click("Next missing");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Loot for Missing one #Q2Y",
  );
  await click("Next missing");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Loot for Missing two #G2Y",
  );
});

it("retains Missing entry and focus through every character until explicit save", async () => {
  await render();
  await click("Needs work");
  await click("Missing (2)");
  const loot = host.querySelector<HTMLInputElement>(
    ".weight-trial-loot input",
  )!;
  await act(async () => loot.focus());
  for (const text of ["3", "35", "35.", "35.8", "35.8k"]) {
    await input(loot, text);
    expect(loot.isConnected).toBe(true);
    expect(document.activeElement).toBe(loot);
    expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(2);
    expect(host.textContent).toContain("Missing (2)");
  }
  expect(host.querySelector(".weight-trial-phone-full")?.textContent).toBe(
    "Full 179k",
  );
  expect(host.querySelector(".weight-trial-row-error")).toBeNull();
  await click("Next missing");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Loot for Missing two #G2Y",
  );
  const saveResult = {
    ...roster,
    members: rows.map((row) =>
      row.tag === "#Q2Y" ? { ...row, weight: 179000, revision: 1 } : row,
    ),
  };
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, ...args) =>
    method === "PUT" ? saveResult : original(path, method, ...args),
  );
  await click("Save weights");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(1);
  expect(host.textContent).toContain("Missing (1)");
});

it("retains a Check row while edits resolve its warning", async () => {
  await render();
  await click("Needs work");
  await click("Check (1)");
  const loot = host.querySelector<HTMLInputElement>(
    ".weight-trial-loot input",
  )!;
  await act(async () => loot.focus());
  for (const text of ["2", "29", "29.8", "29.8k"]) {
    await input(loot, text);
    expect(loot.isConnected).toBe(true);
    expect(document.activeElement).toBe(loot);
  }
  expect(host.textContent).toContain("0 to check");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(1);
});

it("owns hidden-label styling, readable text and disclosure targets on cold navigation", async () => {
  await render();
  await click("Needs work");
  const label = host.querySelector(".weight-trial-storages > span")!;
  expect(label.className).toBe("weight-trial-sr-only");
  const css = readFileSync("src/weightTrial/WeightTrial.css", "utf8");
  expect(css).toMatch(
    /\.weight-trial \.weight-trial-sr-only\s*\{[^}]*position: absolute;[^}]*width: 1px;[^}]*height: 1px;[^}]*clip: rect\(0, 0, 0, 0\)/,
  );
  expect(css).toMatch(/\.weight-trial summary\s*\{[^}]*min-height: 44px/);
  expect(css).toMatch(/\.weight-trial a\s*\{[^}]*color: var\(--wu-accent\)/);
  const globalTokens = readFileSync("src/tokens.css", "utf8");
  expect(globalTokens.match(/--wu-accent:\s*(#[\da-f]{6})\s*;/)?.[1]).toBe(
    "#f4cd64",
  );
  const main = readFileSync("src/main.tsx", "utf8");
  expect(main.match(/^import\s+["']([^"']+)["'];?/m)?.[1]).toBe("./tokens.css");
  const accentDefinitions = readdirSync("src", {
    recursive: true,
    encoding: "utf8",
  })
    .filter((file) => file.endsWith(".css"))
    .filter((file) =>
      /--wu-accent\s*:/.test(readFileSync(`src/${file}`, "utf8")),
    );
  expect(accentDefinitions).toEqual(["tokens.css"]);
  expect(css).toMatch(
    /\.weight-trial \.town-hall-fallback\s*\{[^}]*font-size: 12px/,
  );
  expect(
    host.querySelector(".weight-trial-editor .weight-trial-save"),
  ).not.toBeNull();
  expect(
    host.querySelector(".weight-trial-editor .weight-trial-export"),
  ).toBeNull();
});

it("shows plain clipboard failures for both copy actions, retaining validation guidance", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) =>
    path.includes("/clans/")
      ? { ...roster, members: [rows[0]], war_order: { [rows[0].tag]: 1 } }
      : original(path, ...args),
  );
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi
        .fn()
        .mockRejectedValue(
          new TypeError("Cannot read properties of undefined"),
        ),
    },
  });
  await render();
  await click("Needs work");
  for (const button of ["Copy member table", "Copy loot for FWA column F"]) {
    await click(button);
    expect(host.textContent).toContain(
      "Copy blocked by the browser. Select the text and copy it manually.",
    );
    expect(host.textContent).not.toContain("Cannot read properties");
  }
});
it("polls loading progress with bounded backoff and stops when loaded", async () => {
  vi.useFakeTimers();
  try {
    const complete = {
      clans: [
        {
          tag: "#R2Y",
          name: "Loading clan",
          members_count: 50,
          weighed_count: 50,
          status: "current",
        },
      ],
      outside_fwa_missing_count: 0,
    };
    vi.mocked(api)
      .mockResolvedValueOnce({
        ...complete,
        clans: [
          {
            ...complete.clans[0],
            members_count: null,
            weighed_count: null,
            status: "loading",
          },
        ],
      })
      .mockResolvedValue(complete);
    await render();
    await openClanPicker();
    expect(document.body.textContent).toContain("Loading progress…");
    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(api).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(document.body.textContent).toContain("50/50 weighed");
    await act(async () => vi.advanceTimersByTimeAsync(120000));
    expect(api).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});
it("bounds retries and makes stalled progress actionable", async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(api).mockResolvedValue({
      clans: [
        {
          tag: "#R2Y",
          name: "Waiting",
          members_count: null,
          weighed_count: null,
          status: "loading",
        },
      ],
      outside_fwa_missing_count: null,
    });
    await render();
    await act(async () => vi.advanceTimersByTimeAsync(120000));
    expect(api).toHaveBeenCalledTimes(7);
    expect(host.textContent).toContain("Progress is still unavailable");
    expect(host.textContent).not.toContain("Loading progress…");
  } finally {
    vi.useRealTimers();
  }
});
it("cancels old-season timers and ignores late progress responses", async () => {
  vi.useFakeTimers();
  try {
    let oldResolve!: (value: unknown) => void;
    vi.mocked(api).mockImplementation((path) =>
      path.includes("season_id=1")
        ? new Promise((resolve) => {
            oldResolve = resolve;
          })
        : Promise.resolve({ clans: [], outside_fwa_missing_count: 0 }),
    );
    await render();
    await act(async () =>
      root.render(<WeightTrial onDirty={onDirty} seasonId="2" />),
    );
    await act(async () =>
      oldResolve({
        clans: [
          {
            tag: "#OLD",
            name: "Wrong season",
            status: "loading",
            members_count: null,
            weighed_count: null,
          },
        ],
        outside_fwa_missing_count: 9,
      }),
    );
    await act(async () => vi.advanceTimersByTimeAsync(120000));
    expect(host.textContent).not.toContain("Wrong season");
    expect(api).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});

it("shows a plain last-check date when cached membership needs checking", async () => {
  vi.mocked(api).mockResolvedValue({
    clans: [
      {
        tag: "#R2Y",
        name: "Known",
        members_count: 50,
        weighed_count: 48,
        status: "stale",
        membership_checked_at: "2026-10-30T12:00:00Z",
      },
    ],
    outside_fwa_missing_count: null,
  });
  await render();
  await openClanPicker();
  expect(document.body.textContent).toContain("members checked");
  expect(host.textContent).not.toContain("stale membership");
});
it("disposes pending progress timers when navigating away", async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(api).mockResolvedValue({
      clans: [
        {
          tag: "#R2Y",
          name: "Waiting",
          members_count: null,
          weighed_count: null,
          status: "loading",
        },
      ],
      outside_fwa_missing_count: null,
    });
    await render();
    await act(async () => root.render(<div>Other page</div>));
    await act(async () => vi.advanceTimersByTimeAsync(120000));
    expect(api).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

it("stops progress retries on access denial and removes protected counts", async () => {
  vi.useFakeTimers();
  try {
    const { ApiError } = await import("../api");
    const denied = new ApiError("Access denied", 403);
    denied.status = 403;
    vi.mocked(api).mockRejectedValue(denied);
    await render();
    await act(async () => vi.advanceTimersByTimeAsync(120000));
    expect(api).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("Access denied");
    expect(
      host.querySelectorAll(".weight-trial-clan-list button"),
    ).toHaveLength(0);
  } finally {
    vi.useRealTimers();
  }
});

it("edits departed war players, defaults newest, switches wars and copies selected war only", async () => {
  const newest = {
    state: "warEnded",
    end_time: "20261102T070000.000Z",
    order: { "#G2Y": 1, "#P2Y": 2 },
    names: { "#G2Y": "Left newest" },
    town_halls: { "#G2Y": 15 },
  };
  const previous = {
    state: "warEnded",
    end_time: "20261031T070000.000Z",
    order: { "#J2Y": 1 },
    names: { "#J2Y": "Left previous" },
  };
  const all = [
    { ...rows[0], storages: 5, current_member: true },
    {
      tag: "#G2Y",
      name: "Left newest",
      town_hall: 15,
      weight: 150000,
      storages: 5,
      revision: 1,
      current_member: false,
    },
    {
      tag: "#J2Y",
      name: "Left previous",
      town_hall: null,
      weight: null,
      storages: null,
      revision: 0,
      current_member: false,
    },
  ];
  let current: Roster = {
    ...roster,
    members: all.filter((row) => row.current_member),
    weight_members: all,
    war_lineups: [newest, previous],
    war_order: newest.order,
    war_source: newest,
    current_members_count: 1,
  };
  const write = vi.fn();
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path.startsWith("/weight-trial/saved-players"))
      return { players: [], total: 0 };
    if (path.includes("/clans/")) {
      if (method === "PUT") {
        write(body);
        current = {
          ...current,
          weight_members: current.weight_members!.map((row) =>
            row.tag === "#J2Y"
              ? { ...row, weight: 140000, storages: 4, revision: 1 }
              : row,
          ),
        };
      }
      return current;
    }
    return {
      clans: [
        {
          tag: "#R2Y",
          name: "Needs work",
          weighed_count: 2,
          members_count: 2,
          missing_count: 0,
          last_saved_at: null,
          status: "current",
        },
      ],
      outside_fwa_missing_count: 0,
    };
  });
  const copied = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copied },
  });
  await render();
  await click("Needs work");
  expect(host.querySelector('[data-player="#G2Y"] input')).not.toBeNull();
  expect(
    host.querySelector<HTMLInputElement>('[data-player="#G2Y"] input')!
      .disabled,
  ).toBe(false);
  expect(host.querySelector('[data-player="#G2Y"]')!.textContent).toContain(
    "Left clan",
  );
  expect(host.querySelector('[data-player="#J2Y"]')).toBeNull();
  const war = host.querySelector<HTMLSelectElement>(
    ".weight-trial-war-picker select",
  )!;
  expect(war.value).toBe(newest.end_time);
  await act(async () => {
    war.value = previous.end_time;
    war.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const departed = host.querySelector('[data-player="#J2Y"]')!;
  expect(departed.textContent).toContain(
    "Town Hall unavailable · select storages",
  );
  const storages = departed.querySelector<HTMLSelectElement>("select")!;
  expect(storages.value).toBe("");
  expect(storages.disabled).toBe(false);
  await act(async () => {
    storages.value = "4";
    storages.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await input(
    departed.querySelector<HTMLInputElement>(".weight-trial-loot input")!,
    "35000",
  );
  await click("Save weights");
  expect(write).toHaveBeenCalledExactlyOnceWith({
    changes: [{ tag: "#J2Y", revision: 0, weight: 140000, storages: 4 }],
  });
  expect(war.value).toBe(previous.end_time);
  await click("Copy loot for FWA column F");
  expect(copied).toHaveBeenCalledExactlyOnceWith("35000");
});

it("keeps departed edits when switching wars is canceled and renders saved names as text", async () => {
  const newest = {
    state: "inWar",
    end_time: "20261102T070000.000Z",
    order: { "#G2Y": 1 },
    names: { "#G2Y": '<img src=x onerror="alert(1)">' },
    town_halls: { "#G2Y": 15 },
  };
  const previous = {
    state: "warEnded",
    end_time: "20261031T070000.000Z",
    order: { "#J2Y": 1 },
  };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith("/weight-trial/saved-players"))
      return { players: [], total: 0 };
    if (path.includes("/clans/"))
      return {
        ...roster,
        members: [
          {
            tag: "#G2Y",
            name: '<img src=x onerror="alert(1)">',
            town_hall: 15,
            weight: null,
            storages: 5,
            revision: 0,
            current_member: false,
          },
          {
            tag: "#J2Y",
            name: "Previous",
            town_hall: 14,
            weight: null,
            storages: 5,
            revision: 0,
            current_member: false,
          },
        ],
        war_lineups: [newest, previous],
        war_order: newest.order,
        war_source: newest,
      };
    return {
      clans: [
        {
          tag: "#R2Y",
          name: "Needs work",
          weighed_count: 0,
          members_count: 1,
          missing_count: 1,
          last_saved_at: null,
          status: "current",
        },
      ],
      outside_fwa_missing_count: 0,
    };
  });
  await render();
  await click("Needs work");
  const row = host.querySelector('[data-player="#G2Y"]')!;
  expect(row.textContent).toContain('<img src=x onerror="alert(1)">');
  expect(row.querySelector('img[src="x"]')).toBeNull();
  await input(
    row.querySelector<HTMLInputElement>(".weight-trial-loot input")!,
    "30000",
  );
  const war = host.querySelector<HTMLSelectElement>(
    ".weight-trial-war-picker select",
  )!;
  await act(async () => {
    war.value = previous.end_time;
    war.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(document.body.textContent).toContain("Unsaved changes");
  await click("Keep editing");
  expect(war.value).toBe(newest.end_time);
  expect(
    row
      .querySelector<HTMLInputElement>(".weight-trial-loot input")!
      .value.replace(/,/g, ""),
  ).toBe("30000");
  expect(
    vi.mocked(api).mock.calls.filter(([, method]) => method === "PUT"),
  ).toHaveLength(0);
});

it("clears clan summaries and an opened saved-player search when member access is revoked", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  await render();
  await click("Needs work");
  await input(
    host.querySelector<HTMLInputElement>(
      '.weight-saved-search input[type="search"]',
    )!,
    "Saved",
  );
  await click("Search saved players");
  expect(host.textContent).toContain("Saved outside");
  const { ApiError } = await import("../api");
  const denied = new ApiError("Access revoked", 403);
  denied.status = 403;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path.includes("/clans/")) throw denied;
    return original(path, ...args);
  });
  await click("Refresh members");
  expect(host.textContent).toContain("Access revoked");
  expect(host.textContent).not.toContain("Saved outside");
  expect(host.textContent).not.toContain("2/4 weighed");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(0);
  vi.mocked(api).mockImplementation(original);
  await click("Retry clans");
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(4);
  expect(host.textContent).not.toContain("Saved outside");
});

it("does not restore protected clan counts from a stale success after access denial", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  let resolveDirectory!: (value: unknown) => void;
  const pending = new Promise((resolve) => {
    resolveDirectory = resolve;
  });
  let directoryCalls = 0;
  let denied = false;
  const { ApiError } = await import("../api");
  const forbidden = new ApiError("Access revoked", 403);
  forbidden.status = 403;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path.startsWith("/weight-trial/clans") && !path.includes("/clans/")) {
      directoryCalls++;
      if (directoryCalls === 2) return pending;
    }
    if (denied && path.includes("/clans/")) throw forbidden;
    return original(path, ...args);
  });
  await render();
  await click("Needs work");
  expect(directoryCalls).toBe(2);
  denied = true;
  await click("Refresh members");
  expect(host.textContent).toContain("Access revoked");
  const oldDirectory = await original("/weight-trial/clans?season_id=1");
  await act(async () => {
    resolveDirectory(oldDirectory);
    await pending;
  });
  expect(host.textContent).not.toContain("2/4 weighed");
  expect(host.querySelector(".weight-saved-search")).toBeNull();
  expect(host.querySelectorAll(".weight-trial-row")).toHaveLength(0);
});

it("does not relabel an unchanged verified war after saving a weight", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  const war = {
    state: "inWar",
    end_time: "20261102T070000.000Z",
    captured_at: "2026-11-02T12:00:00Z",
    cached: false,
    order: roster.war_order,
  };
  const fresh = { ...roster, war_lineups: [war], war_source: war };
  vi.mocked(api).mockImplementation(async (path, method, ...rest) => {
    if (path.includes("/clans/"))
      return method === "PUT"
        ? {
            ...fresh,
            members: fresh.members.map((row) =>
              row.tag === "#P2Y"
                ? { ...row, weight: 155000, revision: 2 }
                : row,
            ),
            war_lineups: [{ ...war, cached: true }],
            war_source: { ...war, cached: true },
          }
        : fresh;
    return original(path, method, ...rest);
  });
  await render();
  await click("Needs work");
  expect(host.querySelector(".weight-trial-order")?.textContent).toContain(
    "Current war · Battle day order",
  );
  await input(
    host.querySelector<HTMLInputElement>(
      '[data-player="#P2Y"] .weight-trial-loot input',
    )!,
    "31000",
  );
  await click("Save weights");
  expect(host.textContent).toContain("1 weight saved.");
  expect(host.querySelector(".weight-trial-order")?.textContent).toContain(
    "Current war · Battle day order",
  );
});

it("restores the last clan for its viewer without sharing it with another viewer", async () => {
  localStorage.clear();
  localStorage.setItem("wu-clan-weights:last-clan:viewer-one", "#R2Y");
  await act(async () =>
    root.render(
      <WeightTrial onDirty={onDirty} seasonId="1" viewerId="viewer-one" />,
    ),
  );
  expect(
    host.querySelector(".weight-trial-header .roster-menu-trigger")
      ?.textContent,
  ).toContain("Needs work");
  expect(
    host.querySelector(".weight-trial-header .roster-menu-trigger")
      ?.textContent,
  ).not.toContain("weighed");
  expect(localStorage.getItem("wu-clan-weights:last-clan:viewer-one")).toBe(
    "#R2Y",
  );
  await act(async () => root.render(null));
  vi.mocked(api).mockClear();
  await act(async () =>
    root.render(
      <WeightTrial onDirty={onDirty} seasonId="1" viewerId="viewer-two" />,
    ),
  );
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.includes("/clans/")),
  ).toBe(false);
  expect(
    localStorage.getItem("wu-clan-weights:last-clan:viewer-two"),
  ).toBeNull();
  localStorage.clear();
});

it("keeps an explicit clan deep link ahead of remembered selection", async () => {
  localStorage.clear();
  localStorage.setItem("wu-clan-weights:last-clan:viewer-link", "#J2Y");
  await act(async () =>
    root.render(
      <WeightTrial
        onDirty={onDirty}
        seasonId="1"
        viewerId="viewer-link"
        targetClan="#R2Y"
      />,
    ),
  );
  const requests = vi.mocked(api).mock.calls.map(([path]) => path);
  expect(requests.some((path) => path.includes("/clans/%23R2Y"))).toBe(true);
  expect(requests.some((path) => path.includes("/clans/%23J2Y"))).toBe(false);
  expect(
    host.querySelector(".weight-trial-header .roster-menu-trigger")
      ?.textContent,
  ).toContain("Needs work");
  localStorage.clear();
});

it("ignores a remembered clan absent from the current permitted directory", async () => {
  localStorage.clear();
  localStorage.setItem(
    "wu-clan-weights:last-clan:viewer-missing",
    "#NOTVISIBLE",
  );
  await act(async () =>
    root.render(
      <WeightTrial onDirty={onDirty} seasonId="1" viewerId="viewer-missing" />,
    ),
  );
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.includes("/clans/")),
  ).toBe(false);
  expect(
    host.querySelector(".weight-trial-header .roster-menu-trigger")
      ?.textContent,
  ).toContain("Select a clan");
  expect(
    host
      .querySelector(".weight-trial-header .roster-menu-trigger")
      ?.getAttribute("aria-label"),
  ).toBe("Select a clan");
  localStorage.clear();
});

it("guards unsaved edits when changing clans through the picker", async () => {
  await render();
  await click("Needs work");
  const trigger = host.querySelector<HTMLButtonElement>(
    ".weight-trial-header .roster-menu-trigger",
  )!;
  expect(trigger.getAttribute("aria-label")).toBe("Clan: Needs work");
  expect(trigger.textContent).not.toContain("Clan:");
  await openClanPicker();
  expect(
    document
      .querySelector('.weight-clan-picker-panel [role="menu"]')
      ?.getAttribute("aria-label"),
  ).toBe("Clan: Needs work");
  await act(async () => {
    document
      .querySelector<HTMLButtonElement>(
        ".weight-clan-picker-panel header button",
      )!
      .click();
  });
  const loot = host.querySelector<HTMLInputElement>(
    ".weight-trial-loot input",
  )!;
  await act(async () => loot.focus());
  await input(loot, "35.8k");
  await click("Complete");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "You have 1 unsaved weight.",
  );
  await click("Keep editing");
  await act(async () => {
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve()),
    );
  });
  expect(loot.isConnected).toBe(true);
  expect(document.activeElement).toBe(loot);
  expect(loot.value.replace(/[, ]/g, "")).toMatch(/^(35\.8k|35800)$/);
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.includes("%23J2Y")),
  ).toBe(false);
  await click("Complete");
  await click("Discard");
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.includes("%23J2Y")),
  ).toBe(true);
});
