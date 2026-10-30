// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import WeightQueue from "./WeightQueue";
import type { RosterAccount } from "./roster";

let allowWeight = true;
vi.mock("./DashboardPermissions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./DashboardPermissions")>()),
  useDashboardPermission: () => allowWeight,
}));
const accounts = Array.from(
  { length: 65 },
  (_, i) =>
    ({
      tag: `#P${i}Y`,
      player_name: `Player ${i}`,
      pool: i % 2 ? "lazy" : "main",
      town_hall: 16,
      effective_weight: null,
      manual_weight: null,
      source_status: i % 3 ? "missing" : "unavailable",
      clan_weight_managed: false,
    }) as RosterAccount,
);
let host: HTMLDivElement, root: Root;
const rows = () => [
  ...host.querySelectorAll<HTMLFormElement>(".weight-queue-row"),
];
const input = (i = 0) => rows()[i].querySelector<HTMLInputElement>("input")!;
const button = (text: string, scope: ParentNode = host) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find(
    (e) => e.textContent === text,
  )!;
async function type(element: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function click(element: HTMLElement) {
  await act(async () => element.click());
}
async function render(
  overrides: Partial<Parameters<typeof WeightQueue>[0]> = {},
) {
  const props = {
    accounts,
    busy: false,
    onEdit: vi.fn(),
    onSave: vi.fn().mockResolvedValue(true),
    onRefresh: vi.fn(),
    ...overrides,
  };
  await act(async () => root.render(<WeightQueue {...props} />));
  return props;
}
beforeEach(() => {
  allowWeight = true;
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("defaults to Loot and previews 25,000 as 125,000 full weight without saving", async () => {
  const props = await render();
  expect(button("Loot").getAttribute("aria-pressed")).toBe("true");
  expect(rows()[0].querySelectorAll("[aria-pressed]")).toHaveLength(0);
  expect(input().inputMode).toBe("decimal");
  expect(input().placeholder).toBe("Loot");
  await type(input(), "25,000");
  expect(rows()[0].textContent).toContain(
    "= 125,000 full weight · saved for future seasons",
  );
  expect(props.onSave).not.toHaveBeenCalled();
});
it("keeps typed text when switching to Full and re-evaluates", async () => {
  await render();
  await type(input(), "25,000");
  await click(button("Full"));
  expect(input().value).toBe("25,000");
  expect(input().placeholder).toBe("Full weight");
  expect(rows()[0].textContent).toContain(
    "= 25,000 · saved for future seasons",
  );
  expect(rows()[1].querySelectorAll("[aria-pressed]")).toHaveLength(0);
});
it("uses the same save payload for Loot and Full as the former row units", async () => {
  const props = await render();
  await type(input(), "25,000");
  await click(button("Save", rows()[0]));
  expect(props.onSave).toHaveBeenLastCalledWith("#P0Y", 125000);
  await click(button("Full"));
  await type(input(1), "25,000");
  await click(button("Save", rows()[1]));
  expect(props.onSave).toHaveBeenLastCalledWith("#P1Y", 25000);
});

it("does not save or rewrite unsaved text when the top unit changes", async () => {
  const props = await render();
  await type(input(), "25,000");
  await type(input(1), "12,000");
  await click(button("Full"));
  expect(input().value).toBe("25,000");
  expect(input(1).value).toBe("12,000");
  expect(rows()[0].textContent).toContain(
    "= 25,000 · saved for future seasons",
  );
  expect(rows()[1].textContent).toContain(
    "= 12,000 · saved for future seasons",
  );
  expect(props.onSave).not.toHaveBeenCalled();
  expect(
    host.querySelectorAll(".weight-queue-unit-picker [aria-pressed]"),
  ).toHaveLength(2);
  expect(
    host.querySelectorAll(".weight-queue-row [aria-pressed]"),
  ).toHaveLength(0);
});

it("reports nonempty drafts and clears drafts and errors on reset without saving", async () => {
  const onDirtyCount = vi.fn();
  const onDirty = vi.fn();
  const props = await render({
    onDirtyCount,
    onDirty,
    resetToken: 0,
    onSave: vi.fn().mockResolvedValue(false),
  });
  expect(onDirtyCount).toHaveBeenLastCalledWith(0);
  await type(input(), "25,000");
  await type(input(1), "12,000");
  expect(onDirtyCount).toHaveBeenLastCalledWith(2);
  expect(onDirty).toHaveBeenLastCalledWith(true);
  await click(button("Save", rows()[0]));
  expect(rows()[0].textContent).toContain("Weight wasn't saved");
  await render({ ...props, resetToken: 1 });
  expect(input().value).toBe("");
  expect(input(1).value).toBe("");
  expect(rows()[0].textContent).not.toContain("Weight wasn't saved");
  expect(onDirtyCount).toHaveBeenLastCalledWith(0);
  expect(onDirty).toHaveBeenLastCalledWith(false);
  expect(props.onSave).toHaveBeenCalledOnce();
});

it.each(["e3", "-1", "0", "100001", "0.01"])(
  "shows inline validation and disables Save for invalid loot %s",
  async (value) => {
    const props = await render();
    await type(input(), value);
    expect(button("Save", rows()[0]).disabled).toBe(true);
    expect(input().getAttribute("aria-invalid")).toBe("true");
    expect(rows()[0].querySelector(".is-error")?.textContent).not.toBe("");
    expect(props.onSave).not.toHaveBeenCalled();
  },
);
it("saves converted full weight only after explicit Save and focuses the next row", async () => {
  const save = vi.fn();
  function Harness() {
    const [items, setItems] = useState(accounts);
    return (
      <WeightQueue
        accounts={items}
        busy={false}
        onEdit={() => {}}
        onRefresh={() => {}}
        onSave={async (tag, weight) => {
          save(tag, weight);
          setItems((current) => current.filter((a) => a.tag !== tag));
          return true;
        }}
      />
    );
  }
  await act(async () => root.render(<Harness />));
  await type(input(), "25,000");
  await click(button("Save", rows()[0]));
  expect(save).toHaveBeenCalledExactlyOnceWith("#P0Y", 125000);
  expect(document.activeElement).toBe(input());
  expect(input().getAttribute("aria-label")).toBe("Loot for Player 1");
});
it("renders only 50 then Load more; search includes unrendered accounts", async () => {
  await render();
  expect(rows()).toHaveLength(50);
  expect(host.textContent).toContain("Showing 50 of 65");
  await click(button("Load more"));
  expect(rows()).toHaveLength(65);
  await type(host.querySelector('input[type="search"]')!, "Player 64");
  expect(rows()).toHaveLength(1);
  expect(rows()[0].textContent).toContain("Player 64");
});
it("retains unmounted drafts across search and reports dirty until input is cleared", async () => {
  const onDirty = vi.fn();
  await render({ onDirty });
  await type(input(), "25000");
  expect(onDirty).toHaveBeenLastCalledWith(true);
  await type(host.querySelector('input[type="search"]')!, "Player 64");
  expect(onDirty).toHaveBeenLastCalledWith(true);
  await type(host.querySelector('input[type="search"]')!, "");
  expect(input().value).toBe("25000");
  await type(input(), "");
  expect(onDirty).toHaveBeenLastCalledWith(false);
});
it("clears the dirty count when refreshed accounts no longer need the drafted weight", async () => {
  const onDirty = vi.fn();
  const onDirtyCount = vi.fn();
  const onSave = vi.fn();
  await render({ onDirty, onDirtyCount, onSave });
  await type(input(), "25000");
  expect(onDirtyCount).toHaveBeenLastCalledWith(1);
  await type(host.querySelector('input[type="search"]')!, "Player 64");
  expect(onDirtyCount).toHaveBeenLastCalledWith(1);
  await render({ accounts: accounts.slice(1), onDirty, onDirtyCount, onSave });
  expect(onDirtyCount).toHaveBeenLastCalledWith(0);
  expect(onDirty).toHaveBeenLastCalledWith(false);
  expect(onSave).not.toHaveBeenCalled();
});

it("has the concise header, primitive Refresh icon, no instructions or Back button", async () => {
  const props = await render();
  expect(host.querySelectorAll("p")).toHaveLength(0);
  expect(host.textContent).not.toContain("Back to roster");
  const refresh = button("Refresh weights");
  expect(refresh.classList.contains("roster-ui-button")).toBe(true);
  expect(refresh.querySelector("svg")).not.toBeNull();
  await click(refresh);
  expect(props.onRefresh).toHaveBeenCalledOnce();
});
it("retains input on failed saves and prevents duplicate submits while pending", async () => {
  let finish!: (value: boolean) => void;
  const save = vi.fn(
    () =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  await render({ onSave: save });
  await type(input(), "25000");
  await click(button("Save", rows()[0]));
  expect(button("Full").disabled).toBe(true);
  await act(async () =>
    rows()[0].dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ),
  );
  expect(save).toHaveBeenCalledOnce();
  await act(async () => finish(false));
  expect(input().value).toBe("25000");
  expect(rows()[0].textContent).toContain("Weight wasn't saved");
});
it("disables edits and refresh in archived seasons and while busy", async () => {
  await render({ archived: true });
  expect(input().disabled).toBe(true);
  expect(button("Refresh weights").disabled).toBe(true);
  expect(button("Save", rows()[0]).disabled).toBe(true);
});
it("uses 15px primary names and 12px regular metadata and helper text, with a text-fill reset", () => {
  const css = readFileSync("src/WeightQueue.css", "utf8");
  expect(css).toContain("font-size: 15px");
  expect(css).toMatch(
    /\.roster-workspace\.roster-ui \.weight-queue \.weight-queue-name button \{[^}]*display: block;[^}]*text-align: left;/,
  );
  expect(css).toContain("font-weight: 700");
  expect(css).toContain("font-size: 12px");
  expect(css).toContain("font-weight: 400");
  expect(css).toContain("-webkit-text-fill-color: currentColor");
  expect(css).not.toMatch(/font-size: (?:[0-9]|1[01])px/);
});

it.each([
  "Request timed out",
  "Your login expired",
  "Roster changed; refresh before saving",
])(
  "keeps the draft and never retries automatically after %s",
  async (message) => {
    const onSave = vi.fn().mockRejectedValue(new Error(message));
    await render({ onSave });
    await type(input(), "25,000");
    await click(button("Save", rows()[0]));
    expect(input().value).toBe("25,000");
    expect(rows()[0].textContent).toContain(message);
    expect(onSave).toHaveBeenCalledOnce();
  },
);

it("keeps Save disabled on empty input", async () => {
  await render();
  expect(input().value).toBe("");
  expect(button("Save", rows()[0]).disabled).toBe(true);
});
it("opens Details in archived seasons but blocks the name while busy", async () => {
  const onEdit = vi.fn();
  await render({ archived: true, onEdit });
  await click(button("Player 0", rows()[0]));
  expect(onEdit).toHaveBeenCalledExactlyOnceWith("#P0Y");
  expect(input().disabled).toBe(true);
  await render({ archived: true, busy: true, onEdit });
  expect(button("Player 0", rows()[0]).disabled).toBe(true);
});
it("focus after Save skips clan-weight-managed rows", async () => {
  function Harness() {
    const [items, setItems] = useState([
      accounts[0],
      { ...accounts[1], clan_weight_managed: true },
      accounts[2],
    ]);
    return (
      <WeightQueue
        accounts={items}
        busy={false}
        onEdit={() => {}}
        onRefresh={() => {}}
        onSave={async (tag) => {
          setItems((current) => current.filter((a) => a.tag !== tag));
          return true;
        }}
      />
    );
  }
  await act(async () => root.render(<Harness />));
  await type(
    host.querySelector<HTMLInputElement>(
      'input[aria-label="Loot for Player 0"]',
    )!,
    "25000",
  );
  await click(
    button(
      "Save",
      rows().find((row) => row.textContent?.includes("Player 0"))!,
    ),
  );
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Loot for Player 2",
  );
});

import { DashboardPermissions } from "./DashboardPermissions";
import { mergeRosterMetadata } from "./roster";
it("keeps the FWA split and link through unavailable metadata and updates when known", async () => {
  const member = {
    ...accounts[0],
    current_clan_tag: "#FWA",
    current_clan_status: "current" as const,
    current_fwa_clan_tag: "#FWA",
    current_fwa_status: "current",
  };
  let snapshot = { revision: 1, accounts: [member], clans: [], undo: null };
  const show = async () =>
    act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <WeightQueue
            accounts={snapshot.accounts}
            busy={false}
            onEdit={() => {}}
            onSave={async () => true}
            onRefresh={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
  await show();
  expect(host.textContent).toContain("Set in Clan weights ›");
  expect(host.querySelector(".weight-queue-row input")).toBeNull();
  const unknown = {
    ...snapshot,
    accounts: [
      {
        ...member,
        current_fwa_clan_tag: null,
        current_fwa_status: "unavailable",
      },
    ],
  };
  snapshot = mergeRosterMetadata(snapshot, unknown) as typeof snapshot;
  await show();
  expect(host.textContent).toContain("FWA players");
  expect(host.textContent).toContain("Showing last known groups");
  expect(host.querySelector(".weight-queue-row input")).toBeNull();
  snapshot = mergeRosterMetadata(snapshot, {
    ...unknown,
    accounts: [{ ...unknown.accounts[0], current_fwa_status: "current" }],
  }) as typeof snapshot;
  await show();
  expect(host.textContent).toContain("Other accounts · enter here");
  expect(host.querySelector(".weight-queue-row input")).not.toBeNull();
});

it("rejects a non-thousand value inline before submit", async () => {
  const props = await render();
  await type(input(), "30300");
  expect(rows()[0].textContent).toContain("Full weight must end in 000");
  expect(button("Save", rows()[0]).disabled).toBe(true);
  await act(async () =>
    rows()[0].dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ),
  );
  expect(props.onSave).not.toHaveBeenCalled();
});

it("keeps roster-only queue read-only and shows permission notice instead of opening an editor", async () => {
  allowWeight = false;
  const props = await render();
  expect(input().disabled).toBe(true);
  await click(button("Player 0"));
  expect(props.onEdit).not.toHaveBeenCalled();
  expect(props.onSave).not.toHaveBeenCalled();
  expect(host.textContent).toContain(
    "Permission needed: changing weights needs Clan weights access. Ask an owner.",
  );
  expect(button("Refresh weights").disabled).toBe(false);
});
