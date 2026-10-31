// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import type { ActivityAccount } from "./strikeActivityView";
const row: ActivityAccount = {
  player_tag: "#PYY",
  player_name: "Fixture healthy",
  current_clan_tag: "#PQQ",
  current_clan_name: "Family",
  town_hall: 16,
  weight: 149000,
  active_strikes: 0,
  total_strikes: 0,
  marked_for_replacement: false,
  status: "active",
  quiet_days: 0,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  skipped_raid_weekends: 0,
};
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/strikes");
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) =>
    setTimeout(() => fn(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            accounts: [
              row,
              {
                ...row,
                player_tag: "#PQQ",
                player_name: "Risk fixture",
                active_strikes: 3,
                total_strikes: 3,
                marked_for_replacement: true,
                status: "risk",
                quiet_days: 14,
                no_attack_wars: 3,
                missed_attacks: 6,
                observed_attacks: 6,
              },
            ],
            clans: [{ tag: "#PQQ", name: "Family" }],
          }),
        ),
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("loads the family once, keeps weight tool closed, and row selection only navigates", async () => {
  const choose = vi.fn();
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={choose} />),
  );
  expect(host.textContent).toContain("1 at risk · 0 watch · 1 active");
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(2);
  expect(host.textContent).toContain("Active today");
  expect(host.textContent).toContain("Didn't attack in their last 3 wars");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click(),
  );
  expect(choose.mock.calls[0][0].player_name).toBe("Risk fixture");
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(
        ([, options]) => !options?.method || options.method === "GET",
      ),
  ).toBe(true);
});
it("replacements alias starts with marked filter and preserves URL changes", async () => {
  await act(async () =>
    root.render(<StrikeActivityRoster markedDefault onChoose={vi.fn()} />),
  );
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(1);
  const toggle = [...host.querySelectorAll("label")]
    .find((label) => label.textContent === "Marked for replacement")!
    .querySelector<HTMLInputElement>("input")!;
  await act(async () => toggle.click());
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(2);
  expect(new URLSearchParams(location.search).get("marked")).toBe("0");
});
it("permission loss clears loaded protected rows", async () => {
  const denied = vi.fn();
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} onDenied={denied} />),
  );
  vi.mocked(fetch).mockImplementation(
    async () =>
      new Response(JSON.stringify({ error: "No strike access" }), {
        status: 403,
      }),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Refresh activity")!
      .click(),
  );
  expect(denied).toHaveBeenCalledOnce();
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(0);
  expect(host.querySelector("[role=alert]")).not.toBeNull();
});

it("loads recruit matches only on request and ignores a response after the weight changes", async () => {
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  const disclosure = [...host.querySelectorAll("details")].find(
    (node) =>
      node.querySelector("summary")?.textContent === "Match a recruit’s weight",
  )!;
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  await act(async () => {
    disclosure.open = true;
    disclosure.dispatchEvent(new Event("toggle"));
  });
  let finish!: (response: Response) => void;
  vi.mocked(fetch).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const input = host.querySelector<HTMLInputElement>(
    ".strike-activity-recruit input",
  )!;
  async function weight(value: string) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await weight("149");
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((node) => node.textContent === "Find closest weights")!
      .click(),
  );
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  await weight("150");
  await act(async () =>
    finish(
      new Response(
        JSON.stringify({
          candidates: [
            {
              player_tag: "#PYY",
              player_name: "Stale match",
              weight: 149000,
              clan_name: "Family",
            },
          ],
        }),
      ),
    ),
  );
  expect(host.textContent).not.toContain("Stale match");
  expect(input.value).toBe("150");
  expect(
    [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (node) => node.textContent === "Find closest weights",
    )!.disabled,
  ).toBe(false);
});
