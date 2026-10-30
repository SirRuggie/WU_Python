// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ClanHistory from "./ClanHistory";
import { api } from "./api";
vi.mock("./api", () => ({ api: vi.fn() }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const event = {
  id: "old",
  action: "Before this change",
  at: "2026-10-29T12:00:00Z",
  actor: "Jamie",
  source: "Dashboard",
  clan: { name: "Example", tag: "#ABC", type: "FWA" },
  can_restore: false,
  present: true,
};
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-30T12:00:00Z"));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
async function render(events = [event]) {
  vi.mocked(api).mockResolvedValue({ events, more: false });
  await act(async () => root.render(<ClanHistory onRestored={() => {}} />));
  await act(async () => vi.advanceTimersByTimeAsync(200));
}
it("renders older snapshots honestly and exposes the exact timestamp on tap", async () => {
  await render();
  expect(host.textContent).toContain("Settings before this change · View");
  expect(host.textContent).toContain("By Jamie");
  const summary = host.querySelector<HTMLElement>(".history-time summary")!;
  expect(summary.textContent).toBe("yesterday");
  await act(async () => summary.click());
  expect(host.querySelector(".history-time")?.hasAttribute("open")).toBe(true);
  expect(host.querySelector("time")?.getAttribute("datetime")).toBe(event.at);
});
it("groups same-day events and displays a supplied diff without confusing it with a snapshot", async () => {
  await render([
    {
      ...event,
      changes: [{ field: "Clan type", before: "FWA", after: "CWL" }],
    } as typeof event,
    { ...event, id: "other" },
  ]);
  expect(host.textContent).toContain("Clan type: FWA → CWL");
  expect(host.querySelectorAll(".clan-history-list > div > h3")).toHaveLength(
    1,
  );
  expect(host.textContent).toContain("View settings before this change");
});
it("does not display a stale response after the history filter changes", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await act(async () => root.render(<ClanHistory onRestored={() => {}} />));
  await act(async () => vi.advanceTimersByTimeAsync(200));
  vi.mocked(api).mockResolvedValue({ events: [], more: false });
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = "removed";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => vi.advanceTimersByTimeAsync(200));
  await act(async () => resolve({ events: [event], more: false }));
  expect(host.textContent).toContain("No saved settings found");
  expect(host.textContent).not.toContain("By Jamie");
});

it("does not expose raw historical member or role IDs when names were not recorded", async () => {
  await render([
    {
      ...event,
      clan: {
        ...event.clan,
        leader_id: "123456789012345678",
        role_id: "987654321098765432",
      },
    } as typeof event,
  ]);
  expect(host.textContent).not.toContain("123456789012345678");
  expect(host.textContent).not.toContain("987654321098765432");
  expect(host.textContent).toContain("Name not recorded");
});

it("shows saved reminder values even when disabled or empty", async () => {
  await render([
    {
      ...event,
      reminder_snapshot: [
        { field: "Reminders", value: "Off" },
        { field: "Reminder times", value: "None" },
        { field: "Remind who", value: "Players with no attacks used" },
      ],
    } as typeof event,
  ]);
  const values = host.querySelector(".clan-history-values")!;
  expect(values.textContent).toContain("RemindersOff");
  expect(values.textContent).toContain("Reminder timesNone");
  expect(values.textContent).toContain("Players with no attacks used");
});
