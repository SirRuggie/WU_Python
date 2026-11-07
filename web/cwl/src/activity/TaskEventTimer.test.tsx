// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, vi } from "vitest";
import TodoWorkspace from "../TodoWorkspace";
import { clearJourneyState } from "../journeyState";
import type { Account } from "../api";
import type { TodoKind, TodoRow, TodoSnapshot, TodoView } from "../todo";
const taskFixture = vi.hoisted(() => ({ data: null as TodoSnapshot | null }));
vi.mock("../todoLoading", () => ({
  loadTasks: async (
    publish: (data: TodoSnapshot, updating: boolean) => void,
  ) => {
    if (!taskFixture.data) throw new Error("Task fixture missing");
    publish(taskFixture.data, false);
  },
}));
vi.mock("../snapshotCache", () => ({
  readSnapshot: () => null,
  writeSnapshot: vi.fn(),
}));
vi.mock("../PushReminders", () => ({ default: () => null }));
vi.mock("./useClock", () => ({ useClock: () => Date.UTC(2026, 10, 6, 12) }));
import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TaskEventTimer from "./TaskEventTimer";
it("shows upcoming then live Clan Games timing at the exact boundary", () => {
  const before = renderToStaticMarkup(
    <TaskEventTimer kind="games" now={Date.UTC(2026, 9, 22, 7, 59)} />,
  );
  expect(before).toContain("Starts");
  expect(before).toContain("1 minute");
  expect(before).toContain("after the event starts");
  const started = renderToStaticMarkup(
    <TaskEventTimer kind="games" now={Date.UTC(2026, 9, 22, 8)} />,
  );
  expect(started).toContain("Ends");
  expect(started).toContain("as activity is reported");
  const ended = renderToStaticMarkup(
    <TaskEventTimer kind="games" now={Date.UTC(2026, 9, 28, 8)} />,
  );
  expect(ended).toContain("Next event");
  expect(ended).toContain("2026-11-22T08:00:00.000Z");
});
it("shows raid start and end timers using the Events calendar", () => {
  const upcoming = renderToStaticMarkup(
    <TaskEventTimer kind="raid" now={Date.UTC(2026, 9, 23, 6)} />,
  );
  expect(upcoming).toContain("1 hour");
  const live = renderToStaticMarkup(
    <TaskEventTimer kind="raid" now={Date.UTC(2026, 9, 23, 7)} />,
  );
  expect(live).toContain("Ends");
  expect(live).toContain("2026-10-26T07:00:00.000Z");
});
it("labels CWL signup timing separately from actual clan battles", () => {
  const upcoming = renderToStaticMarkup(
    <TaskEventTimer kind="cwl" now={Date.UTC(2026, 9, 21, 12)} />,
  );
  expect(upcoming).toContain("Signup opens");
  expect(upcoming).toContain("2026-11-01T08:00:00.000Z");
  expect(upcoming).toContain("Each clan has its own battle times");
  const open = renderToStaticMarkup(
    <TaskEventTimer kind="cwl" now={Date.UTC(2026, 10, 1, 8)} />,
  );
  expect(open).toContain("Signup closes");
  expect(open).toContain("2026-11-03T08:00:00.000Z");
  const closed = renderToStaticMarkup(
    <TaskEventTimer kind="cwl" now={Date.UTC(2026, 10, 3, 8)} />,
  );
  expect(closed).toContain("Next clan signup");
  expect(closed).toContain("2026-12-01T08:00:00.000Z");
});

let workspaceRoot: ReturnType<typeof createRoot> | undefined;
let workspaceHost: HTMLDivElement | undefined;
afterEach(async () => {
  if (workspaceRoot) await act(async () => workspaceRoot!.unmount());
  workspaceHost?.remove();
  workspaceRoot = undefined;
  workspaceHost = undefined;
  taskFixture.data = null;
  clearJourneyState();
});
function emptyView(): TodoView {
  return {
    ok: true,
    note: "",
    notes: [],
    unavailable: "",
    incomplete: "",
    rows: [],
  };
}
function taskSnapshot(
  kind: TodoKind,
  count: number,
  gamesSeason = false,
): TodoSnapshot {
  const rows: TodoRow[] = Array.from({ length: count }, (_, index) => ({
    tag: `#P${index}`,
    name: `Sample ${index}`,
    town_hall: 18,
    clan_tag: "#CLAN",
    clan_name: "Sample clan",
    used: 0,
    total: 2,
    remaining: 2,
    starts_at: 1,
    ends_at: 1800000000,
    state: "inWar",
    detail: null,
  }));
  const view: TodoView = {
    ...emptyView(),
    rows,
    ...(gamesSeason
      ? {
          season: "2026-11",
          checked_at: "2026-11-06T12:00:00Z",
          event_start: Date.UTC(2026, 10, 22, 8) / 1000,
          event_end: Date.UTC(2026, 10, 28, 8) / 1000,
        }
      : {}),
  };
  return {
    checked_at: "2026-11-06T12:00:00Z",
    accounts: Array.from(
      { length: Math.max(count, 1) },
      (_, index) =>
        ({
          tag: `#P${index}`,
          name: `Sample ${index}`,
          town_hall: 18,
        }) as Account,
    ),
    views: {
      war: emptyView(),
      cwl: emptyView(),
      raid: emptyView(),
      games: emptyView(),
      private: emptyView(),
      [kind]: view,
    },
  };
}
async function mountTasks(
  kind: TodoKind,
  count: number,
  search = "",
  gamesSeason = false,
) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  taskFixture.data = taskSnapshot(kind, count, gamesSeason);
  workspaceHost = document.createElement("div");
  document.body.append(workspaceHost);
  workspaceRoot = createRoot(workspaceHost);
  await act(async () =>
    workspaceRoot!.render(
      <TodoWorkspace
        userId="timer-placement-fixture"
        initialTab={kind}
        initialSearch={search}
      />,
    ),
  );
  return workspaceHost;
}
function before(first: Element, second: Element) {
  return !!(
    first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING
  );
}
it("places a nonempty CWL timer after the displayed list and pagination, before freshness", async () => {
  const host = await mountTasks("cwl", 13);
  const timer = host.querySelector(".todo-event-timer")!;
  expect(host.querySelectorAll(".todo-event-timer")).toHaveLength(1);
  expect(timer.classList.contains("is-cwl")).toBe(true);
  expect(host.querySelectorAll(".todo-task")).toHaveLength(12);
  expect(before(host.querySelector(".todo-clan-list")!, timer)).toBe(true);
  expect(before(host.querySelector(".todo-pagination")!, timer)).toBe(true);
  expect(before(timer, host.querySelector(".todo-freshness")!)).toBe(true);
});
it("keeps the CWL timer first when the view has no task rows", async () => {
  const host = await mountTasks("cwl", 0);
  expect(
    before(
      host.querySelector(".todo-event-timer")!,
      host.querySelector(".card.empty")!,
    ),
  ).toBe(true);
  expect(host.querySelector(".todo-clan-list")).toBeNull();
});
it("uses filtered rows so an empty CWL search keeps the timer before the list state", async () => {
  const host = await mountTasks("cwl", 13, "NoTimerMatch");
  const timer = host.querySelector(".todo-event-timer")!;
  expect(before(timer, host.querySelector(".todo-search-row")!)).toBe(true);
  expect(before(timer, host.querySelector(".card.empty")!)).toBe(true);
  expect(host.querySelector(".todo-clan-list")).toBeNull();
  expect(host.querySelectorAll(".todo-event-timer")).toHaveLength(1);
});
it.each(["raid", "games"] as const)(
  "keeps the %s event timer before its task rows without the CWL modifier",
  async (kind) => {
    const host = await mountTasks(kind, 1);
    const timer = host.querySelector(".todo-event-timer")!;
    expect(timer.className).toBe("todo-event-timer");
    expect(before(timer, host.querySelector(".todo-clan-list")!)).toBe(true);
  },
);
it("preserves the Clan Games season summary branch in its original first position", async () => {
  const host = await mountTasks("games", 1, "", true);
  const timer = host.querySelector(".todo-event-timer")!;
  expect(host.querySelectorAll(".todo-event-timer")).toHaveLength(1);
  expect(timer.className).toBe("todo-event-timer");
  expect(timer.textContent).toContain("Tracked scores");
  expect(timer.textContent).not.toContain("usual game schedule");
  expect(before(timer, host.querySelector(".todo-clan-list")!)).toBe(true);
});
