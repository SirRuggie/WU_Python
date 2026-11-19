// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import StaffOverview from "./StaffOverview";
import TodoWorkspace from "./TodoWorkspace";

const mocks = vi.hoisted(() => ({ staff: vi.fn(), tasks: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: (path: string) =>
    path === "/manage/staff-overview" ? mocks.staff() : Promise.resolve({}),
}));
vi.mock("./todoLoading", () => ({ loadTasks: mocks.tasks }));
vi.mock("./snapshotCache", () => ({
  readSnapshot: () => null,
  writeSnapshot: vi.fn(),
}));
vi.mock("./PushReminders", () => ({ default: () => null }));
vi.mock("./VisitorSummary", () => ({ default: () => null }));

for (const page of ["staff", "tasks"] as const) {
  it(`${page}: pausing a pending read neither replaces nor duplicates it, and resume reads once`, async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.useFakeTimers();
    let finish!: () => void;
    const read = mocks[page];
    read.mockReset().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const click = async (name: string) => {
      const button = host.querySelector<HTMLButtonElement>(
        `button[aria-label="${name}"]`,
      )!;
      expect(button).toBeTruthy();
      await act(async () => button.click());
    };
    try {
      await act(async () =>
        root.render(
          page === "staff" ? (
            <StaffOverview onNavigate={vi.fn()} />
          ) : (
            <TodoWorkspace userId="pause249" />
          ),
        ),
      );
      expect(read).toHaveBeenCalledTimes(1);
      await click("Pause automatic refresh");
      await act(async () => {
        vi.advanceTimersByTime(120000);
      });
      expect(read).toHaveBeenCalledTimes(1);
      await click("Resume automatic refresh");
      expect(read).toHaveBeenCalledTimes(1);
      await act(async () => finish());
      await click("Pause automatic refresh");
      await act(async () => {
        vi.advanceTimersByTime(120000);
      });
      expect(read).toHaveBeenCalledTimes(1);
      await click("Resume automatic refresh");
      expect(read).toHaveBeenCalledTimes(2);
      await act(async () => finish());
    } finally {
      await act(async () => root.unmount());
      host.remove();
      vi.useRealTimers();
    }
  });
}
