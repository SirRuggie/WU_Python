// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import RosterClanChips from "./RosterClanChips";
import { assignmentOptions, type RosterSnapshot } from "./roster";
it("hides empty clans, reveals the correct count, preserves assign options, and resets on season", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const roster = {
    revision: 1,
    undo: null,
    accounts: [],
    clans: [
      {
        tag: "#P",
        name: "Empty One",
        pool: "main",
        archived: false,
        capacity: 15,
      },
      {
        tag: "#Q",
        name: "Empty Two",
        pool: "main",
        archived: false,
        capacity: 15,
      },
    ],
  } as unknown as RosterSnapshot;
  const render = (season: string) =>
    root.render(
      <RosterClanChips
        key={season}
        roster={roster}
        pool="main"
        selectedTags={[]}
        onSelect={() => {}}
        disabled={false}
      />,
    );
  try {
    await act(async () => render("1"));
    expect(host.textContent).toContain("No clans have players yet");
    expect(host.textContent).toContain("+2 clans with no players");
    expect(host.textContent).not.toContain("Empty One");
    expect(assignmentOptions(roster.clans).map((clan) => clan.tag)).toEqual([
      "#P",
      "#Q",
    ]);
    await act(async () => host.querySelector("button")!.click());
    expect(host.textContent).toContain("Empty One");
    expect(host.textContent).toContain("Empty Two");
    await act(async () => render("2"));
    expect(host.textContent).not.toContain("Empty One");
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});
it("the Assign panel still offers an empty hosting clan", async () => {
  const { default: AssignPanel } = await import("./RosterAssignPanel");
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const roster = {
    revision: 1,
    undo: null,
    accounts: [
      {
        tag: "#QG02CY8LG",
        player_name: "Aurora",
        pool: "main",
        assigned_clan_tag: null,
        effective_weight: 170000,
      },
    ],
    clans: [
      {
        tag: "#P",
        name: "Empty One",
        pool: "main",
        archived: false,
        capacity: 15,
        assigned_count: 0,
      },
    ],
  } as unknown as RosterSnapshot;
  try {
    await act(async () =>
      root.render(
        <AssignPanel
          roster={roster}
          selectedAccounts={roster.accounts}
          hiddenTags={[]}
          busy={false}
          trigger={null}
          onClose={() => {}}
          onAssign={async () => true}
        />,
      ),
    );
    const destination = [
      ...document.querySelectorAll<HTMLButtonElement>("dialog button"),
    ].find((button) => button.textContent?.includes("Empty One"));
    expect(destination).toBeTruthy();
    expect(destination!.disabled).toBe(false);
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});
it("uses singular for one empty clan", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <RosterClanChips
          roster={
            {
              accounts: [],
              clans: [
                {
                  tag: "#P",
                  name: "Empty",
                  pool: "main",
                  archived: false,
                  capacity: 15,
                },
              ],
            } as unknown as RosterSnapshot
          }
          pool="main"
          selectedTags={[]}
          onSelect={() => {}}
          disabled={false}
        />,
      ),
    );
    expect(host.querySelector("button")?.textContent).toBe(
      "+1 clan with no players",
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
