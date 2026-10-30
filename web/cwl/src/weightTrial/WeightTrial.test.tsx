// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WeightTrial from "./WeightTrial";
import { api } from "../api";
import { readFileSync } from "node:fs";
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
async function click(text: string, scope: ParentNode = document) {
  const button = Array.from(
    scope.querySelectorAll<HTMLButtonElement>("button"),
  ).find((node) => node.textContent?.includes(text));
  expect(button).toBeTruthy();
  await act(async () => button!.click());
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
  expect(host.textContent).toContain("2/4 weighed");
  expect(host.textContent).toContain("50/50 weighed");
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
  expect(host.textContent).toContain("3 · Departed · left the clan");
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
  expect(host.textContent).toContain("3 · Not in clan anymore");
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
  expect(css).toMatch(/\.weight-trial a\s*\{[^}]*color: #f4cd64/);
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
    expect(host.textContent).toContain("Loading progress…");
    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(api).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(host.textContent).toContain("50/50 weighed");
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
  expect(host.textContent).toContain("members checked");
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
