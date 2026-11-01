// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi, afterEach } from "vitest";
import type { ReactNode } from "react";
vi.mock("./ActionPanel", () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
import RosterAssignPanel from "./RosterAssignPanel";
import type { RosterAccount, RosterSnapshot } from "./roster";
let root: ReturnType<typeof createRoot> | undefined, host: HTMLDivElement;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
});
for (const capacity of [15, 30])
  it(`allows only fillers past ${capacity}, blocking regular and mixed selections`, async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    const filler = {
      tag: "#F",
      player_name: "Filler",
      assigned_clan_tag: null,
      pool: "lazy",
      kept: false,
      effective_weight: 100,
      roster_filler: true,
    } as RosterAccount;
    const regular = {
      ...filler,
      tag: "#R",
      player_name: "Regular",
      roster_filler: false,
    };
    const roster = {
      revision: 1,
      undo: null,
      accounts: [],
      clans: [
        {
          tag: "#HOST",
          name: "Host",
          pool: "lazy",
          archived: false,
          assigned_count: capacity,
          capacity,
          effective_capacity: capacity,
        },
      ],
    } as unknown as RosterSnapshot;
    const assign = vi.fn(async () => true);
    for (const chosen of [[filler], [regular], [filler, regular]]) {
      await act(async () =>
        root!.render(
          <RosterAssignPanel
            roster={roster}
            selectedAccounts={chosen}
            hiddenTags={[]}
            busy={false}
            trigger={null}
            onClose={() => {}}
            onAssign={assign}
          />,
        ),
      );
      const button = host.querySelector<HTMLButtonElement>(
        ".roster-assign-clan",
      )!;
      expect(button.disabled).toBe(chosen.some((a) => !a.roster_filler));
    }
  });
