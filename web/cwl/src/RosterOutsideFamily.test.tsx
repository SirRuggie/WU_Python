// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi } from "vitest";
import RosterFilters from "./RosterFilters";
import {
  DEFAULT_ROSTER_RELEASE_PREFERENCES,
  deriveRosterRelease,
  type RosterReleaseFilters,
} from "./rosterReleaseModel";
import type { RosterAccount, RosterSnapshot } from "./roster";
const account = (name: string, outside: boolean): RosterAccount => ({
  tag: "#" + name,
  user_id: name,
  pool: "main",
  player_name: name,
  town_hall: 16,
  prefer_crystal_1_or_lower: false,
  source_weight: 149000,
  source_status: "current",
  source_name: "fixture",
  source_checked_at: null,
  source_modified_at: null,
  manual_weight: null,
  effective_weight: 149000,
  assigned_clan_tag: null,
  kept: !outside,
  outside_family_and_hosts: outside,
});
const roster: RosterSnapshot = {
  revision: 1,
  accounts: [account("Outside", true), account("Inside", false)],
  clans: [],
  undo: null,
};
it("adds the counted checkbox, applies it, shows the active chip and clears it with Clear all", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const go = vi.spyOn(history, "go").mockImplementation(() => {});
  history.replaceState({}, "", "/");
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  function Page() {
    const [value, setValue] = useState<RosterReleaseFilters>(
      DEFAULT_ROSTER_RELEASE_PREFERENCES,
    );
    return (
      <>
        <RosterFilters
          roster={roster}
          value={value}
          onChange={setValue}
          disabled={false}
        />
        <output>
          {deriveRosterRelease(roster.accounts, [], value)
            .matches.map((row) => row.player_name)
            .join(",")}
        </output>
      </>
    );
  }
  const button = (text: string) =>
    [...document.querySelectorAll<HTMLButtonElement>("button")].find(
      (node) => node.textContent?.trim() === text,
    )!;
  try {
    await act(async () => root.render(<Page />));
    await act(async () => button("Filters").click());
    const label = [...document.querySelectorAll("label")].find(
      (node) => node.querySelector("span")?.textContent === "Outside family",
    )!;
    expect(label.querySelector("small")?.textContent).toBe("1");
    await act(async () =>
      label.querySelector<HTMLInputElement>("input")!.click(),
    );
    await act(async () => button("Show 1 accounts").click());
    expect(host.querySelector("output")?.textContent).toBe("Outside");
    expect(
      host.querySelector('[aria-label="Remove Outside family filter"]'),
    ).not.toBeNull();
    await act(async () => button("Clear all").click());
    expect(host.querySelector("output")?.textContent).toBe("Outside,Inside");
    expect(
      host.querySelector('[aria-label="Remove Outside family filter"]'),
    ).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
    go.mockRestore();
  }
});
