// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import ReminderWorkspace from "./ReminderWorkspace";
import initial from "../tests/fixtures/signup-reminders-data.json";
import { dashboardTarget } from "./dashboardHistory";
import { api, ApiError } from "./api";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const state = () => ({
  cycle: "2026-11",
  generation: "1:0",
  activated: true,
  worker_ready: true,
  schedule_synced: true,
  campaign: structuredClone(initial),
  schedule: [],
  history: [],
  signup_open: true,
});
it("keeps six editable rows and directs roster posts to season Announcements without a roster editor", async () => {
  const value = state();
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("manage-reminders")
      ? (value as never)
      : path.includes("roles")
        ? ({ roles: [] } as never)
        : ({ channels: [] } as never),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <ReminderWorkspace seasonId="42" archived={false} onDirty={() => {}} />,
      ),
    );
    expect(host.querySelectorAll(".signup-reminder-row")).toHaveLength(6);
    const link = [...host.querySelectorAll("a")].find(
      (link) => link.textContent === "Announcements ›",
    )!;
    expect(link).toBeTruthy();
    expect(link.parentElement?.textContent).toBe(
      "Roster posts are on Announcements ›",
    );
    const url = new URL(link.href);
    expect(dashboardTarget(url.search, url.pathname)).toMatchObject({
      view: "publication",
      step: "announce",
      season: "42",
    });
    expect(host.textContent).not.toContain("Waiting for the bot");

    expect(host.textContent).toContain("Messages for December 2026 CWL");
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent === "Messages")!
        .click(),
    );
    expect(
      [...host.querySelectorAll("button")].some(
        (button) => button.textContent === "Save",
      ),
    ).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it.each([500, 403])(
  "failed refresh retains rows except authorization denial %s",
  async (status) => {
    let fail = false;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.includes("manage-reminders")) {
        if (fail) throw new ApiError("Fixture unavailable", status);
        return state() as never;
      }
      return path.includes("roles")
        ? ({ roles: [] } as never)
        : ({ channels: [] } as never);
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <ReminderWorkspace
            seasonId="42"
            archived={false}
            onDirty={() => {}}
          />,
        ),
      );
      fail = true;
      await act(async () => {
        [...host.querySelectorAll("button")]
          .find((button) => button.textContent === "Refresh")!
          .click();
      });
      expect(host.querySelectorAll(".signup-reminder-row")).toHaveLength(
        status === 500 ? 6 : 0,
      );
      expect(host.querySelector('[role="alert"]')).toBeTruthy();
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
