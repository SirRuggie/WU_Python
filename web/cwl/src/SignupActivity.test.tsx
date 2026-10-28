// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SignupActivity from "./SignupActivity";
import {
  signupActivitySummary,
  signupActivityIntro,
  type SignupChange,
} from "./signupActivityModel";
import type { RosterClan, RosterSnapshot } from "./roster";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
const item = (id = 1, action = "member_withdrawal"): SignupChange => ({
  id,
  action,
  tag: `#QG02CY8L${id}`,
  player_name: `Player ${id}`,
  user_id: "505227988229554179",
  from_pool: "lazy",
  to_pool: action === "member_withdrawal" ? null : "main",
  assigned_clan_tag: "#CLAN",
  assigned_clan_name: "Morning Woods!",
  created_at: "2026-10-28T04:44:00Z",
});
const clan = (capacity: number | null, assigned_count = 14) =>
  ({
    tag: "#CLAN",
    name: "Morning Woods!",
    capacity,
    assigned_count,
  }) as RosterClan;
let root: Root, host: HTMLDivElement;
const fill = vi.fn(() => true),
  details = vi.fn(() => true);
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  api.mockReset();
  fill.mockClear();
  details.mockClear();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});
async function render(items = [item()], version?: number) {
  api.mockImplementation((_path: string, method?: string) =>
    Promise.resolve(method ? { ok: true } : { items }),
  );
  await act(async () =>
    root.render(
      <SignupActivity
        seasonId="1"
        roster={
          {
            revision: 1,
            undo: null,
            accounts: [{ tag: item(2).tag }],
            clans: [],
          } as unknown as RosterSnapshot
        }
        publishedVersion={version}
        canCompare
        onFill={fill}
        onDetails={details}
      />,
    ),
  );
}
async function click(text: string) {
  const button = [
    ...document.querySelectorAll<HTMLButtonElement>("button"),
  ].find((b) => b.textContent === text || b.textContent?.includes(text));
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}
async function open() {
  await act(async () =>
    (host.querySelector(".signup-activity-line") as HTMLButtonElement).click(),
  );
}
it("words single, plural, mixed and 100+ changes; red only for known below-war-size", () => {
  expect(signupActivitySummary([item()], []).text).toBe(
    "1 assigned player withdrew",
  );
  expect(signupActivitySummary([item(1, "member_pool_change")], []).text).toBe(
    "1 assigned player switched pool",
  );
  expect(signupActivitySummary([item(), item(2)], []).text).toBe(
    "2 assigned players withdrew",
  );
  expect(
    signupActivitySummary([item(), item(2, "member_pool_change")], []).text,
  ).toBe("2 assigned players changed: 1 withdrew, 1 switched pool");
  expect(
    signupActivitySummary(
      Array.from({ length: 100 }, (_, i) => item(i)),
      [],
    ).text,
  ).toBe("100+ assigned players withdrew");
  expect(signupActivitySummary([item()], [clan(15)])).toEqual({
    danger: true,
    text: "1 signup change · Morning Woods! now below 15",
  });
  expect(signupActivitySummary([item()], [clan(null)]).danger).toBe(false);
  expect(signupActivitySummary([item()], [clan(15, 15)]).danger).toBe(false);
});
it("uses active publication only for the intro", () => {
  expect(signupActivityIntro(3)).toBe(
    "Their spots are open in the draft. Members still see them on version 3 until you publish again.",
  );
  expect(signupActivityIntro()).toBe("Their spots are open in the draft.");
});
it("shows compact dates without clan tags, plain withdrawals and linked pool-switch names", async () => {
  await render([item(), item(2, "member_pool_change")], 2);
  await open();
  expect(document.querySelector("dialog")?.textContent).not.toContain("#CLAN");
  const rows = document.querySelectorAll("article");
  expect(rows[0].querySelector(".signup-activity-name")).toBeNull();
  expect(rows[1].querySelector(".signup-activity-name")?.textContent).toBe(
    "Player 2",
  );
  expect(rows[0].querySelector("time")?.textContent).toMatch(/Oct 28/);
  expect(rows[0].querySelector("time")?.title).toContain("2026");
  const link = rows[0].querySelector("a")!;
  expect(link.textContent).toBe("Message ↗");
  expect(link.rel).toBe("noopener noreferrer");
  await click("Player 2");
  expect(details).toHaveBeenCalledWith(item(2).tag);
  expect(document.querySelector("dialog")).toBeNull();
});
it("Fill spot navigates only, closes panel, and makes no POST", async () => {
  await render();
  await open();
  await click("Fill spot");
  expect(fill).toHaveBeenCalledWith(item());
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(0);
  expect(document.querySelector("dialog")).toBeNull();
});
it("guards double tap synchronously, shows Saving, and closes after last review", async () => {
  await render();
  await open();
  let finish!: () => void;
  api.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const button = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === "Mark reviewed",
  )!;
  await act(async () => {
    button.click();
    button.click();
  });
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(1);
  expect(document.body.textContent).toContain("Saving…");
  await act(async () => finish());
  expect(document.querySelector("dialog")).toBeNull();
  expect(host.textContent).toBe("");
});
it("keeps failed row with inline error and allows an explicit retry", async () => {
  await render();
  await open();
  api.mockRejectedValueOnce(new Error("Network failure"));
  await click("Mark reviewed");
  expect(document.querySelector("article [role=alert]")?.textContent).toBe(
    "Network failure",
  );
  await click("Mark reviewed");
  expect(document.querySelector("dialog")).toBeNull();
});
it("Mark all confirms names, Cancel writes nothing, partial failure reports X of N", async () => {
  await render([item(), item(2), item(3)]);
  await open();
  await click("Mark all reviewed");
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Player 3",
  );
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(0);
  await click("Cancel");
  await click("Mark all reviewed");
  api
    .mockResolvedValueOnce({ ok: true })
    .mockRejectedValueOnce(new Error("Review failed"));
  await act(async () =>
    (
      document.querySelector(
        ".confirm-dialog-actions button:last-child",
      ) as HTMLButtonElement
    ).click(),
  );
  expect(document.body.textContent).toContain("Reviewed 1 of 3");
  expect(document.querySelectorAll("article")).toHaveLength(2);
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(2);
});
it("load failure shows Retry, loading shows nothing, and hidden polling pauses", async () => {
  api.mockRejectedValueOnce(new Error("Offline"));
  await act(async () =>
    root.render(
      <SignupActivity
        seasonId="1"
        roster={null}
        canCompare
        onFill={fill}
        onDetails={details}
      />,
    ),
  );
  expect(host.textContent).toContain("Couldn't check signup changes");
  api.mockResolvedValue({ items: [item()] });
  await click("Retry");
  expect(host.textContent).toContain("1 assigned player withdrew");
  vi.useFakeTimers();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  const count = api.mock.calls.length;
  await act(async () => vi.advanceTimersByTime(30000));
  expect(api).toHaveBeenCalledTimes(count);
});
