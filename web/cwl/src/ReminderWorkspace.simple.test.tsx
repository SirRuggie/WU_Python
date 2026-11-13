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
    expect(host.textContent).not.toContain("Waiting for changes to load");

    expect(host.textContent).toContain("Messages for December 2026 CWL");
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((button) => button.textContent === "Messages")!
        .click(),
    );
    expect(
      [...host.querySelectorAll("button")].some(
        (button) => button.textContent === "Save changes",
      ),
    ).toBe(true);
    expect(
      [...host.querySelectorAll("button")].some(
        (button) => button.textContent === "Preview schedule",
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

it("does not call intentionally inactive schedules pending", async () => {
  const value = { ...state(), activated: false, schedule_synced: false };
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
    expect(host.textContent).not.toContain("Waiting for changes to load");
    expect(
      host.querySelector(".reminder-status .roster-ui-status")?.textContent,
    ).toBe("Off");
    expect(host.querySelector(".reminder-status .badge")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it.each([
  ["absent", false, undefined],
  ["current", true, 128],
  ["newer", true, 129],
  ["older", true, 127],
  ["zero", true, 0],
  ["null", true, null],
  ["boolean", true, false],
] as const)("saves the 128 marker only when the loaded campaign marker is absent: %s", async (_label, present, version) => {
  const value = state();
  if (present) Object.assign(value.campaign, { default_copy_version: version });
  vi.mocked(api).mockReset();
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
  const button = (text: string) => [...host.querySelectorAll("button")].find((item) => item.textContent === text)!;
  try {
    await act(async () => root.render(<ReminderWorkspace seasonId="42" archived={false} onDirty={() => {}} />));
    await act(async () => button("Messages").click());
    const title = [...host.querySelectorAll("label")].find((label) => label.firstChild?.textContent === "Title")!.querySelector("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(title, "Fixture reminder title");
      title.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(button("Save changes").disabled).toBe(false);
    await act(async () => button("Save changes").click());
    expect(vi.mocked(api).mock.calls.filter(([, method]) => method === "PATCH")).toHaveLength(0);
    const confirm = [...document.querySelectorAll("dialog button")].find((item) => item.textContent === "Save") as HTMLButtonElement;
    expect(confirm).toBeTruthy();
    await act(async () => confirm.click());
    const editPatch = { messages: { signup: { variants: { main: { title: "Fixture reminder title" } } } } };
    const previews = vi.mocked(api).mock.calls.filter(([, method]) => method === "POST");
    expect(previews).toEqual([["/seasons/42/manage-reminders/preview", "POST", { generation: "1:0", patch: editPatch, repeat_monthly: true }]]);
    const saves = vi.mocked(api).mock.calls.filter(([, method]) => method === "PATCH");
    expect(saves).toEqual([["/seasons/42/manage-reminders", "PATCH", {
      generation: "1:0",
      patch: present ? editPatch : { ...editPatch, default_copy_version: 128 },
      repeat_monthly: true,
    }]]);
    expect(Object.hasOwn(value.campaign, "default_copy_version")).toBe(present);
    if (present) expect((value.campaign as unknown as Record<string, unknown>).default_copy_version).toBe(version);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
