// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import FilterChips from "./FilterChips";

it("opts only the Strikes Account views group into pills while preserving its labels, counts and selection", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/strikes?activity_view=all");
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  vi.spyOn(HTMLElement.prototype, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response(JSON.stringify({ accounts: [], clans: [] })),
    ),
  );
  try {
    await act(async () =>
      root.render(
        <>
          <StrikeActivityRoster onChoose={vi.fn()} />
          <FilterChips
            label="Default group"
            value="one"
            options={[{ value: "one", label: "One", count: 0 }]}
            onChange={vi.fn()}
          />
        </>,
      ),
    );
    const group = host.querySelector('[aria-label="Account views"]')!;
    expect(group.classList.contains("strike-activity-tabs")).toBe(true);
    expect(group.classList.contains("filter-chips--pill")).toBe(true);
    const buttons = [...group.querySelectorAll<HTMLButtonElement>("button")];
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Not attacking 0",
      "Inactive 0",
      "Replacements 0",
      "All 0",
    ]);
    expect(
      buttons.map((button) => button.getAttribute("aria-pressed")),
    ).toEqual(["false", "false", "false", "true"]);
    await act(async () => buttons[0].click());
    expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
    expect(buttons[3].getAttribute("aria-pressed")).toBe("false");
    expect(host.querySelector('[aria-label="Default group"]')!.className).toBe(
      "filter-chips has-horizontal-fades ",
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  }
});
