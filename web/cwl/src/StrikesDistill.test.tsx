// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikesWorkspace from "./StrikesWorkspace";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
let host: HTMLDivElement;
let root: Root;
const account = {
  player_tag: "#P2Y",
  player_name: "Portal fixture",
  current_clan_tag: "#Q2Y",
  current_clan_name: "Local Alpha",
  active_strikes: 1,
  total_strikes: 1,
  marked_for_replacement: false,
  status: "active",
  observed_wars: 3,
  attacked_wars: 0,
  missed_attacks: 6,
  observed_attacks: 6,
  quiet_days: 7,
};
const clans = [
  {
    clan_tag: "#Q2Y",
    clan_name: "Local Alpha",
    status: "behind",
    current_war_state: "warEnded",
    error: "Missing final war check",
  },
];
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/strikes?activity_view=all");
  sessionStorage.clear();
  transport.mockReset();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
const tracking = () =>
  host.querySelector<HTMLDetailsElement>("details.strikes-tracking")!;
const readCount = () =>
  transport.mock.calls.filter(([path]) => path === "/strikes/tracking").length;
const postCount = () =>
  transport.mock.calls.filter(([path]) => path === "/strikes/tracking/retry")
    .length;
const clickText = async (text: string, scope: ParentNode = host) => {
  const button = [...scope.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent?.trim() === text,
  )!;
  expect(button, text).toBeTruthy();
  await act(async () => button.click());
};

it.each(["success", "error"])(
  "preserves tracking open state and an in-flight retry through real overview/detail navigation (%s)",
  async (outcome) => {
    let finish: (() => void) | undefined;
    transport.mockImplementation(async (path: string) => {
      if (path === "/strikes/tracking/retry")
        return new Promise((resolve, reject) => {
          finish = () =>
            outcome === "success"
              ? resolve({})
              : reject(new Error("Retry fixture failed"));
        });
      if (path === "/strikes/tracking") return { clans };
      if (path.startsWith("/strikes/accounts"))
        return {
          accounts: [account],
          clans: [],
          activity_as_of: "Activity as of 03:21 UTC",
        };
      return { entries: [], accounts: [], clans: [], total: 0 };
    });
    await act(async () =>
      root.render(<StrikesWorkspace permissions={[]} isOwner userId="1" />),
    );
    expect(readCount()).toBe(1);
    expect(host.querySelectorAll(".strikes-tracking")).toHaveLength(1);
    expect(tracking().closest(".strike-activity-tracking-slot")).not.toBeNull();
    expect(
      host.querySelector(".strikes-navigation .strikes-tracking"),
    ).toBeNull();
    expect(tracking().open).toBe(false);
    const oldDisclosure = tracking();
    // Model the browser's queued toggle: navigation can precede its delivery.
    oldDisclosure.addEventListener(
      "toggle",
      (event) => event.stopImmediatePropagation(),
      { once: true, capture: true },
    );
    await act(async () => {
      oldDisclosure.querySelector("summary")!.click();
      host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click();
    });
    expect(tracking().closest(".strikes-navigation")).not.toBeNull();
    expect(tracking().open).toBe(true);
    expect(
      tracking().querySelector(".strikes-tracking-body")?.textContent,
    ).toContain("Local Alpha");
    // A late toggle from the detached portal DOM must not close the new one.
    await act(async () => {
      oldDisclosure.open = false;
      oldDisclosure.dispatchEvent(new Event("toggle"));
    });
    expect(tracking().open).toBe(true);
    expect(readCount()).toBe(1);
    expect(postCount()).toBe(0);
    await clickText("← Players");
    expect(tracking().closest(".strike-activity-tracking-slot")).not.toBeNull();
    expect(tracking().open).toBe(true);
    await clickText("Retry", tracking());
    expect(postCount()).toBe(1);
    expect(tracking().textContent).toContain("Queuing…");

    await act(async () =>
      host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click(),
    );
    expect(host.querySelectorAll(".strikes-tracking")).toHaveLength(1);
    expect(tracking().closest(".strikes-navigation")).not.toBeNull();
    expect(tracking().open).toBe(true);
    expect(tracking().textContent).toContain("Queuing…");
    expect(
      [...tracking().querySelectorAll("button")].every((node) => node.disabled),
    ).toBe(true);
    expect(readCount()).toBe(1);
    expect(postCount()).toBe(1);

    await clickText("← Players");
    expect(tracking().closest(".strike-activity-tracking-slot")).not.toBeNull();
    expect(tracking().open).toBe(true);
    expect(tracking().textContent).toContain("Queuing…");
    expect(readCount()).toBe(1);
    expect(postCount()).toBe(1);
    await act(async () => finish!());
    expect(tracking().textContent).not.toContain("Queuing…");
    expect(tracking().open).toBe(true);
    if (outcome === "error") {
      expect(tracking().textContent).toContain("Retry fixture failed");
      expect(readCount()).toBe(1);
    } else {
      expect(tracking().textContent).not.toContain("Retry fixture failed");
      expect(readCount()).toBe(2);
    }
    expect(postCount()).toBe(1);
    const line = host.querySelector(".strike-activity-status-line")!;
    expect(line.querySelector(".strike-activity-summary")?.textContent).toBe(
      "Showing 1 of 1",
    );
    expect(line.querySelector(".strike-activity-as-of")?.textContent).toBe(
      "Activity as of 03:21 UTC",
    );
    expect(
      line
        .querySelector(".strike-activity-as-of")!
        .classList.contains("notice"),
    ).toBe(false);
  },
);
