// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import TodoWorkspace from "./TodoWorkspace";
import { clearJourneyState } from "./journeyState";
import type { Account } from "./api";
import type { TodoRow, TodoSnapshot, TodoView } from "./todo";
const taskFixture = vi.hoisted(() => ({ data: null as TodoSnapshot | null }));
vi.mock("./todoLoading", () => ({
  loadTasks: async (
    publish: (data: TodoSnapshot, updating: boolean) => void,
  ) => {
    if (!taskFixture.data) throw new Error("Task fixture missing");
    publish(taskFixture.data, false);
  },
}));
vi.mock("./snapshotCache", () => ({
  readSnapshot: () => null,
  writeSnapshot: vi.fn(),
}));
vi.mock("./PushReminders", () => ({ default: () => null }));
vi.mock("./activity/useClock", () => ({
  useClock: () => Date.UTC(2026, 10, 6, 12),
}));

let root: ReturnType<typeof createRoot> | undefined;
let host: HTMLDivElement | undefined;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  host = undefined;
  taskFixture.data = null;
  clearJourneyState();
});
const view = (rows: TodoRow[] = []): TodoView => ({
  ok: true,
  note: "",
  notes: [],
  unavailable: "",
  incomplete: "",
  rows,
});
const row = (tag: string, extra: Partial<TodoRow> = {}): TodoRow => ({
  tag,
  name: `Name ${tag}`,
  town_hall: 17,
  clan_tag: "#CLAN",
  clan_name: "Sample clan",
  used: 0,
  total: 2,
  remaining: 2,
  starts_at: 1,
  ends_at: 1800000000,
  state: "inWar",
  detail: null,
  ...extra,
});
async function mount(initialSearch = "") {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const war = [
    row("#A", { fwa_outcome: { status: "lose", opponent: "Rival" } }),
    row("#B"),
  ];
  const hidden = [
    row("#C", { clan_tag: "#HID", state: "private", detail: "private" }),
    row("#D", { clan_tag: "#HID", state: "private", detail: "private" }),
  ];
  taskFixture.data = {
    checked_at: "2026-11-06T12:00:00Z",
    accounts: ["#A", "#B", "#C", "#D"].map(
      (tag) => ({ tag, name: `Name ${tag}`, town_hall: 17 }) as Account,
    ),
    views: {
      war: view(war),
      cwl: view(),
      raid: view(),
      games: view(),
      private: view(hidden),
    },
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root!.render(
      <TodoWorkspace
        userId="layout-fixture"
        initialTab="war"
        initialSearch={initialSearch}
      />,
    ),
  );
  return host;
}
function button(name: string) {
  return host!.querySelector<HTMLButtonElement>(
    `button[aria-label="${name}"]`,
  )!;
}
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("puts the private war log note below the list as a neutral fact", async () => {
  const page = await mount();
  expect(page.querySelector(".todo-warning")).toBeNull();
  const note = page.querySelector(".todo-private-note")!;
  expect(note.textContent).toContain(
    "2 accounts are in a clan with a private war log.",
  );
  const list = page.querySelector(".todo-clan-list")!;
  expect(
    list.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(page.textContent).not.toContain("on this page");
  expect(page.querySelector(".todo-fwa.lose strong")!.textContent).toBe(
    "FWA LOSE",
  );
  expect(
    page.querySelector('a[aria-label="Open Sample clan in Clash of Clans"]'),
  ).not.toBeNull();
});

it("opens search from the icon, keeps it open while editing, and closes back to the icon", async () => {
  await mount();
  expect(host!.querySelector(".todo-search-row")).toBeNull();
  await act(async () => button("Search tasks").click());
  const input = host!.querySelector<HTMLInputElement>(
    'input[name="todo-search"]',
  )!;
  expect(document.activeElement).toBe(input);
  await type(input, "Name #A");
  expect(host!.querySelectorAll(".todo-task")).toHaveLength(1);
  await type(input, "");
  expect(host!.querySelector(".todo-search-row")).not.toBeNull();
  await act(async () => button("Clear and close search").click());
  expect(host!.querySelector(".todo-search-row")).toBeNull();
  expect(document.activeElement).toBe(button("Search tasks"));
  expect(host!.querySelectorAll(".todo-task")).toHaveLength(2);
});

it("shows a deep-link search and keeps the field when its text is cleared", async () => {
  await mount("#A");
  const input = host!.querySelector<HTMLInputElement>(
    'input[name="todo-search"]',
  )!;
  expect(input.value).toBe("#A");
  expect(host!.querySelectorAll(".todo-task")).toHaveLength(1);
  await type(input, "");
  expect(host!.querySelector('input[name="todo-search"]')).not.toBeNull();
});

it("toggles auto-refresh with one pause button", async () => {
  await mount();
  const pause = button("Pause auto-refresh");
  expect(pause.getAttribute("aria-pressed")).toBe("false");
  await act(async () => pause.click());
  expect(pause.getAttribute("aria-pressed")).toBe("true");
  expect(host!.textContent).toContain("Paused · checked");
});
