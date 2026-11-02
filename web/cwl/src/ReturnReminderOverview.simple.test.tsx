// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ReturnReminderOverview from "./ReturnReminderOverview";
import ReturnBatch from "./returns/ReturnBatch";
import { api, ApiError } from "./api";
import { canApply, captureMonth, type ReturnClan } from "./returns/model";
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
const row = (
  id: string,
  state = "scheduled",
  label = "Running",
): ReturnClan => ({
  id: "FWA#" + id,
  label: id,
  clan_name: id,
  clan_tag: "#" + id,
  return_section: "FWA",
  endpoint: "/fixture",
  description: "Fixture",
  group: "War",
  return_status: {
    state,
    label,
    players: 4,
    every_minutes: 60,
    last_sent_at: "2026-11-02T10:00:00Z",
    expires_at: "2026-11-09T10:00:00Z",
  },
});
let root: Root, host: HTMLDivElement;
const button = (label: string) =>
  [...document.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label,
  )!;
const click = async (label: string) => act(async () => button(label).click());
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("offers frequency only on running FWA and preserves paused Resume", () => {
  expect(canApply(row("A"), "frequency")).toBe(true);
  expect(canApply(row("A", "paused", "Paused"), "frequency")).toBe(false);
  expect(
    canApply(row("A", "scheduled", "Scheduled to start"), "frequency"),
  ).toBe(false);
  expect(canApply({ ...row("A"), return_section: "MAIN" }, "frequency")).toBe(
    false,
  );
  expect(canApply(row("A", "paused", "Paused"), "resume")).toBe(true);
  expect(canApply(row("A"), "resume")).toBe(false);
});
it("uses UTC capture cycle at the 16th and year boundary", () => {
  expect(captureMonth(new Date("2026-11-15T23:59:59Z"))).toBe("November 2026");
  expect(captureMonth(new Date("2026-11-16T00:00:00Z"))).toBe("December 2026");
  expect(captureMonth(new Date("2026-12-16T00:00:00Z"))).toBe("January 2027");
});
it("changes frequency with exactly one resume write, never start/send", async () => {
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? { status: "done", message: "Saved" }
      : ({
          revision: "r1",
          fields: [
            { key: "clans", options: [{ value: "FWA:#A", label: "A" }] },
          ],
        } as never),
  );
  await act(async () =>
    root.render(
      <ReturnBatch
        action="frequency"
        clans={[row("A")]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    ),
  );
  expect(api).toHaveBeenCalledWith("/manage/return-bulk/resume");
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "120";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await click("Review action");
  expect(button("Change frequency")).toBeTruthy();
  await click("Change frequency");
  const writes = vi.mocked(api).mock.calls.filter((call) => call[1] === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/manage/return-bulk/resume/run");
  expect(writes[0][2]).toMatchObject({
    values: { clans: ["FWA:#A"], every_minutes: 120 },
  });
  expect(writes.some((call) => /start|send/.test(call[0]))).toBe(false);
});
it.each([500, 401, 403])(
  "retains failed-refresh rows except auth denial %s",
  async (status) => {
    let fail = false;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/manage/return-reminders") {
        if (fail) throw new ApiError("Refresh failed", status);
        return { documents: [row("A"), row("B", "paused", "Paused")] } as never;
      }
      return { fields: [], channels: [] } as never;
    });
    await act(async () =>
      root.render(<ReturnReminderOverview onOpen={vi.fn()} />),
    );
    expect(host.textContent).toContain("Every 60 minutes");
    expect(host.textContent).toContain("CWL month for new member lists:");
    expect(host.querySelectorAll(".return-row-actions button")).toHaveLength(3);
    fail = true;
    await click("Refresh");
    if (status === 500) {
      expect(host.textContent).toContain("Showing the last loaded overview.");
      expect(
        (host.querySelector("fieldset") as HTMLFieldSetElement).disabled,
      ).toBe(false);
      expect(button("Change frequency")).toBeTruthy();
    } else expect(host.querySelectorAll(".return-clan-row")).toHaveLength(0);
  },
);
it.each([
  ["send", "Send now"],
  ["start", "Start reminders"],
  ["resume", "Resume"],
  ["pause", "Pause"],
] as const)("names confirmation action %s", async (action, label) => {
  vi.mocked(api).mockResolvedValue({
    revision: "r1",
    fields: [{ key: "clans", options: [{ value: "FWA:#A" }] }],
  } as never);
  await act(async () =>
    root.render(
      <ReturnBatch
        action={action}
        clans={[row("A")]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    ),
  );
  if (action === "send") expect(host.textContent).toContain("Last sent");
  if (action === "start")
    expect(host.textContent).toContain(
      "Starts now. Repeats every hour. Stops within 7 days.",
    );
  await click("Review action");
  expect(button(label)).toBeTruthy();
});
it("keeps capture guidance short after the saved receipt", async () => {
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? { status: "done", message: "Saved" }
      : ({
          revision: "r1",
          fields: [{ key: "clans", options: [{ value: "FWA:#A" }] }],
        } as never),
  );
  await act(async () =>
    root.render(
      <ReturnBatch
        action="save"
        clans={[row("A", "not_saved", "No saved list")]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    ),
  );
  await click("Review action");
  await click("Capture current members");
  expect(host.textContent).toContain("Next: Start return reminders.");
});
it("says away checks send nothing", async () => {
  vi.mocked(api).mockResolvedValue({
    revision: "r1",
    fields: [{ key: "clans", options: [{ value: "FWA:#A" }] }],
  } as never);
  await act(async () =>
    root.render(
      <ReturnBatch
        action="away"
        clans={[row("A")]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    ),
  );
  expect(host.textContent).toContain("Checks only. Sends nothing.");
});
it("uses member list for clear while retaining its existing review route", async () => {
  const open = vi.fn();
  vi.mocked(api).mockImplementation(
    async (path) =>
      ({
        fields: [],
        channels: [],
        documents:
          path === "/manage/return-reminders"
            ? [
                row("A"),
                {
                  id: "return-bulk-clear",
                  label: "Existing clear review",
                  endpoint: "/manage/return-bulk/clear",
                },
              ]
            : [],
      }) as never,
  );
  await act(async () => root.render(<ReturnReminderOverview onOpen={open} />));
  await click("Clear member list");
  expect(open).toHaveBeenCalledWith(
    expect.objectContaining({ endpoint: "/manage/return-bulk/clear" }),
  );
  expect(host.textContent).toContain("Times are in your time zone.");
  expect(host.textContent).not.toContain(
    "Changing search or status clears selection",
  );
});
