// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import BonusStepBar from "./BonusStepBar";
import {
  bonusStepStates,
  type BonusStatus,
  type BonusStatusClan,
} from "./bonusStatus";

const clan = (patch: Partial<BonusStatusClan> = {}): BonusStatusClan => ({
  tag: "#2YQ",
  name: "Lazy One",
  active: true,
  candidates: 8,
  meets_rule: 5,
  results_state: "captured",
  allowance_ready: true,
  draw_state: "none",
  ...patch,
});
const status = (
  lazy: BonusStatusClan[],
  minimum: number | null = 3,
): BonusStatus => ({
  season_id: 1,
  cycle: "2026-11",
  archived: false,
  main_minimum: minimum,
  pools: { main: [], lazy },
});
const states = (
  item: BonusStatusClan | null,
  pool: "main" | "lazy" = "lazy",
  minimum: number | null = 3,
) => bonusStepStates(item, pool, minimum).map((step) => step.state);

describe("bonus step states from the status read", () => {
  it("marks done, current and blocked steps from real data", () => {
    expect(states(clan())).toEqual(["done", "done", "current", "todo", "todo"]);
    expect(states(clan({ draw_state: "saved" }))).toEqual([
      "done",
      "done",
      "done",
      "current",
      "todo",
    ]);
    expect(states(clan({ draw_state: "approved" }))).toEqual([
      "done",
      "done",
      "done",
      "done",
      "current",
    ]);
    expect(states(clan({ draw_state: "sent" }))).toEqual([
      "done",
      "done",
      "done",
      "done",
      "done",
    ]);
    expect(states(clan({ draw_state: "cancelled" }))).toEqual([
      "done",
      "done",
      "current",
      "todo",
      "todo",
    ]);
    // Rules & count is done only with a count (and a Main minimum).
    expect(states(clan({ allowance_ready: false }))).toEqual([
      "done",
      "blocked",
      "todo",
      "todo",
      "todo",
    ]);
    expect(states(clan({ results_state: "not_checked" }))).toEqual([
      "blocked",
      "done",
      "todo",
      "todo",
      "todo",
    ]);
    expect(states(clan({ results_state: "partial" }))[0]).toBe("current");
  });
  it("gives one short reason for a blocked step", () => {
    const reason = (
      item: BonusStatusClan,
      pool: "main" | "lazy" = "lazy",
      minimum: number | null = 3,
    ) =>
      bonusStepStates(item, pool, minimum).find(
        (step) => step.state === "blocked",
      )?.reason;
    expect(reason(clan({ results_state: "not_checked" }))).toBe(
      "Results not captured",
    );
    expect(reason(clan({ allowance_ready: false }))).toBe(
      "Enter the bonus count",
    );
    expect(reason(clan({ active: false }))).toBe("Inactive host");
    expect(reason(clan(), "main", null)).toBe("Set the Main minimum");
  });
});

let cleanup: (() => Promise<void>) | undefined;
afterEach(async () => {
  await cleanup?.();
  cleanup = undefined;
});
async function render(props: Partial<Parameters<typeof BonusStepBar>[0]> = {}) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const select = vi.fn();
  const retry = vi.fn();
  await act(async () =>
    root.render(
      <BonusStepBar
        seasonId="1"
        pool="lazy"
        clan="#2YQ"
        status={status([clan()])}
        failed={false}
        onRetry={retry}
        canOpen={() => true}
        onSelect={select}
        {...props}
      />,
    ),
  );
  cleanup = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  return { host, select, retry };
}

describe("bonus step bar", () => {
  it("links carry season, pool and clan; Results opens Participation", async () => {
    const { host, select } = await render();
    const links = [
      ...host.querySelectorAll<HTMLAnchorElement>(".bonus-step-list a"),
    ];
    expect(links.map((link) => link.textContent)).toEqual([
      "✓Results · Done",
      "✓Rules & count · Done",
      "3Draw",
      "4Approve",
      "5Announce & award",
    ]);
    expect(links[0].getAttribute("href")).toBe(
      "/cwl/results?season=1&pool=lazy&clan=%232YQ",
    );
    expect(links[2].getAttribute("href")).toBe(
      "/cwl/results?season=1&pool=lazy&clan=%232YQ&step=draw",
    );
    expect(links[2].getAttribute("aria-current")).toBe("step");
    expect(host.querySelector(".bonus-step.is-current")?.textContent).toContain(
      "Draw",
    );
    await act(async () => links[2].click());
    expect(select).toHaveBeenCalledExactlyOnceWith(
      "draw",
      "pool=lazy&clan=%232YQ&step=draw",
    );
  });
  it("keeps Results as an in-page step in the clan steps", async () => {
    const { host } = await render({ resultsInPage: true });
    expect(host.querySelector(".bonus-step-list a")?.getAttribute("href")).toBe(
      "/cwl/results?season=1&pool=lazy&clan=%232YQ&step=results",
    );
  });
  it("shows what the page computed, including a typed count, before the status arrives", async () => {
    const { host } = await render({
      status: null,
      input: {
        done: {
          results: false,
          rules: false,
          draw: false,
          approve: false,
          announce: false,
        },
        reasons: { results: "2 not checked · Review" },
      },
    });
    expect(host.querySelector(".bonus-step-mark")?.textContent).toBe("!");
    expect(host.querySelector(".bonus-step.is-blocked")?.textContent).toContain(
      "2 not checked · Review",
    );
  });
  it("lets modified clicks through without in-page navigation", async () => {
    const { host, select } = await render();
    const link = host.querySelector<HTMLAnchorElement>(".bonus-step-list a")!;
    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      ctrlKey: true,
    });
    await act(async () => link.dispatchEvent(event));
    expect(select).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });
  it("shows the phone compact line and expands the full bar", async () => {
    const { host } = await render({
      status: status([clan({ allowance_ready: false })]),
    });
    const compact = host.querySelector<HTMLButtonElement>(
      ".bonus-step-compact",
    )!;
    expect(compact.textContent).toContain("Step 2 of 5 · Rules & count");
    expect(compact.getAttribute("aria-expanded")).toBe("false");
    // The toggle names the list it opens.
    expect(
      host.querySelector(`#${compact.getAttribute("aria-controls")}`)
        ?.className,
    ).toContain("bonus-step-list");
    expect(host.querySelectorAll(".bonus-step-dot")).toHaveLength(5);
    await act(async () => compact.click());
    expect(compact.getAttribute("aria-expanded")).toBe("true");
    expect(host.querySelector(".bonus-step-list")?.classList).toContain(
      "is-expanded",
    );
    expect(host.querySelector(".bonus-step.is-blocked")?.textContent).toContain(
      "Enter the bonus count",
    );
  });
  it("shows a placeholder while loading and one muted retry line on failure", async () => {
    const loading = await render({ status: null });
    expect(
      loading.host.querySelectorAll(".bonus-step-mark")[0].textContent,
    ).toBe("…");
    expect(loading.host.querySelector(".bonus-step.is-done")).toBeNull();
    await cleanup?.();
    const failed = await render({ status: null, failed: true });
    expect(
      failed.host.querySelector(".bonus-step-unavailable")?.textContent,
    ).toBe("Status unavailable · Retry");
    expect(
      failed.host.querySelector(
        ".bonus-step.is-blocked, .bonus-step.is-done, .bonus-step.is-current",
      ),
    ).toBeNull();
    await act(async () =>
      failed.host
        .querySelector<HTMLButtonElement>(".bonus-step-unavailable button")!
        .click(),
    );
    expect(failed.retry).toHaveBeenCalledOnce();
  });
  it("renders steps the user cannot open as text", async () => {
    const { host } = await render({ canOpen: (step) => step === "results" });
    expect(host.querySelectorAll(".bonus-step-list a")).toHaveLength(1);
    expect(host.querySelectorAll(".bonus-step-text")).toHaveLength(4);
  });
});
