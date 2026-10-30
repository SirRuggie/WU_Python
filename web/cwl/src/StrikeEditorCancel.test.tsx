// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import ManualStrikeEditor from "./ManualStrikeEditor";
import StrikesWorkspace from "./StrikesWorkspace";
import ReplacementWorkspace from "./ReplacementWorkspace";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.stubGlobal(
    "confirm",
    vi.fn(() => {
      throw Error("Native confirm forbidden");
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  transport.mockReset();
});
async function render(node: React.ReactNode) {
  await act(async () => root.render(node));
}
function button(name: string, scope: ParentNode = document) {
  const found = [...scope.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === name,
  );
  expect(found, name).toBeTruthy();
  return found!;
}
async function click(name: string, scope?: ParentNode) {
  await act(async () => button(name, scope).click());
}
async function input(selector: string, value: string) {
  const node = host.querySelector<HTMLInputElement>(selector)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const initialAccount = { player_tag: "#P2Y", player_name: "Aspen" };
const callbacks = () => ({
  onCancel: vi.fn(),
  onSaved: vi.fn(async () => {}),
  onDirty: vi.fn(),
  onBusy: vi.fn(),
});

it.each([null, initialAccount])(
  "cancels a clean manual editor without confirming, including prefilled identity %j",
  async (initial) => {
    const props = callbacks();
    await render(<ManualStrikeEditor {...props} initialAccount={initial} />);
    expect(props.onDirty).toHaveBeenLastCalledWith(false);
    await click("Cancel");
    expect(props.onCancel).toHaveBeenCalledTimes(1);
    expect(document.querySelector("dialog")).toBeNull();
    expect(transport).not.toHaveBeenCalled();
  },
);

it("keeps a dirty manual draft and only discards on explicit confirmation", async () => {
  const props = callbacks();
  await render(
    <ManualStrikeEditor {...props} initialAccount={initialAccount} />,
  );
  expect(
    host.querySelector<HTMLInputElement>(
      '[placeholder="Why is this strike needed?"]',
    )!.maxLength,
  ).toBe(500);
  await input(
    '[placeholder="Why is this strike needed?"]',
    "Missed both attacks",
  );
  await click("Cancel");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Unsaved changes",
  );
  await click("Keep editing");
  expect(
    host.querySelector<HTMLInputElement>(
      '[placeholder="Why is this strike needed?"]',
    )!.value,
  ).toBe("Missed both attacks");
  expect(props.onCancel).not.toHaveBeenCalled();
  await click("Cancel");
  await click("Discard");
  expect(props.onCancel).toHaveBeenCalledTimes(1);
  expect(props.onDirty).toHaveBeenLastCalledWith(false);
  expect(transport).not.toHaveBeenCalled();
});

it("treats changed prefilled identity as dirty and retains review and retry request identity", async () => {
  const props = callbacks();
  await render(
    <ManualStrikeEditor {...props} initialAccount={initialAccount} />,
  );
  transport.mockResolvedValueOnce({
    accounts: [
      { tag: "#Q2Y", name: "Birch", town_hall: 17, current_clan_name: "Oak" },
    ],
    members: [],
  });
  await click("Change");
  await input('[placeholder="Name, tag or Discord member"]', "Birch");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((node) => node.textContent?.includes("Birch"))!
      .click(),
  );
  expect(host.textContent).toContain("Oak");
  transport.mockClear();
  await click("Cancel");
  await click("Keep editing");
  await input('[placeholder="Why is this strike needed?"]', "Reason");
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(host.textContent).toContain("Review strike");
  expect(transport).not.toHaveBeenCalled();
  transport
    .mockRejectedValueOnce(new Error("Unconfirmed"))
    .mockResolvedValueOnce({});
  await click("Confirm strike");
  await click("Confirm strike");
  expect(transport).toHaveBeenCalledTimes(2);
  expect(transport.mock.calls[0][2]).toEqual(transport.mock.calls[1][2]);
  expect(transport.mock.calls[0][2]).toMatchObject({
    player_tag: "#Q2Y",
    reason: "Reason",
    request_id: expect.any(String),
  });
  expect(props.onSaved).toHaveBeenCalledTimes(1);
});

const candidates = [
  {
    player_tag: "#P2Y",
    player_name: "Aspen",
    priority: "normal",
    note: "Original",
    active_strikes: 2,
    is_manual: true,
  },
  {
    player_tag: "#Q2Y",
    player_name: "Birch",
    priority: "high",
    note: "",
    active_strikes: 4,
    is_manual: true,
  },
];
async function replacements(canManage = true) {
  transport.mockImplementation(async (_path, method) =>
    method ? {} : { candidates, clans: [] },
  );
  await render(
    <ReplacementWorkspace
      isOwner={canManage}
      permissions={canManage ? [] : ["strikes_add"]}
    />,
  );
}
async function edit(name: string) {
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(`[aria-label="Edit ${name}"]`)!
      .click(),
  );
}
it("closes clean replacement add/edit immediately and preserves dirty add on Keep editing", async () => {
  await replacements();
  await click("Add accounts");
  await click("Cancel");
  expect(document.querySelector("dialog")).toBeNull();
  await edit("Aspen");
  await click("Cancel");
  expect(host.querySelector(".replacement-edit-panel")).toBeNull();
  await click("Add accounts");
  await input('[placeholder="e.g. Temporary filler"]', "Draft note");
  await click("Cancel");
  await click("Keep editing");
  expect(
    host.querySelector<HTMLInputElement>(
      '[placeholder="e.g. Temporary filler"]',
    )!.value,
  ).toBe("Draft note");
  await click("Cancel");
  await click("Discard");
  expect(host.querySelector(".replacement-editor")).toBeNull();
  expect(transport.mock.calls.every((call) => !call[1])).toBe(true);
});

it("keeps edited replacement values on cancelled row navigation and runs the discarded action once", async () => {
  await replacements();
  await edit("Aspen");
  await input(".replacement-edit-panel input", "Unsaved");
  await edit("Birch");
  await click("Keep editing");
  expect(
    host.querySelector<HTMLInputElement>(".replacement-edit-panel input")!
      .value,
  ).toBe("Unsaved");
  expect(
    host
      .querySelector('[aria-label="Edit Aspen"]')!
      .getAttribute("aria-expanded"),
  ).toBe("true");
  await edit("Birch");
  await click("Discard");
  expect(
    host
      .querySelector('[aria-label="Edit Birch"]')!
      .getAttribute("aria-expanded"),
  ).toBe("true");
  expect(
    host.querySelector<HTMLInputElement>(".replacement-edit-panel input")!
      .value,
  ).toBe("");
  expect(transport.mock.calls.every((call) => !call[1])).toBe(true);
});

it("clears only the confirmed replacement priority, keeps draft on cancel, and prevents duplicate deletion", async () => {
  await replacements();
  await edit("Aspen");
  await input(".replacement-edit-panel input", "Unsaved");
  await click("Clear priority");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Strike history stays.",
  );
  await click("Cancel", document.querySelector("dialog")!);
  expect(
    host.querySelector<HTMLInputElement>(".replacement-edit-panel input")!
      .value,
  ).toBe("Unsaved");
  expect(transport.mock.calls.every((call) => !call[1])).toBe(true);
  await click("Clear priority");
  const confirm = button("Clear priority", document.querySelector("dialog")!);
  await act(async () => {
    confirm.click();
    confirm.click();
  });
  expect(transport.mock.calls.filter((call) => call[1])).toEqual([
    ["/strikes/replacement-list/%23P2Y", "DELETE"],
  ]);
});

it("keeps replacement mutation controls unavailable to read-only staff and has no native confirms", async () => {
  await replacements(false);
  expect(host.querySelector(".replacement-more")).toBeNull();
  expect(host.textContent).not.toContain("Add accounts");
  expect(readFileSync("src/ReplacementWorkspace.tsx", "utf8")).not.toMatch(
    /window\.confirm|\bconfirm\s*\(/,
  );
});

it("workspace Cancel confirms once and tab navigation retains the draft until Discard", async () => {
  transport.mockResolvedValue({
    clans: [],
    accounts: [],
    records: [],
    total: 0,
    roles: [],
    exempt_role_ids: [],
    leaves: [],
  });
  await render(
    <StrikesWorkspace permissions={[]} isOwner userId="cancel-workspace" />,
  );
  await click("Add strike");
  await input(
    'input[placeholder="Why is this strike needed?"]',
    "Keep this draft",
  );
  await click("Cancel");
  expect(document.querySelectorAll("dialog")).toHaveLength(1);
  await click("Keep editing");
  expect(
    host.querySelector<HTMLInputElement>(
      'input[placeholder="Why is this strike needed?"]',
    )?.value,
  ).toBe("Keep this draft");
  await click("Settings");
  expect(document.querySelectorAll("dialog")).toHaveLength(1);
  await click("Keep editing");
  expect(
    host.querySelector<HTMLInputElement>(
      'input[placeholder="Why is this strike needed?"]',
    )?.value,
  ).toBe("Keep this draft");
  await click("Cancel");
  await click("Discard");
  expect(document.querySelectorAll("dialog")).toHaveLength(0);
  expect(
    host.querySelector('input[placeholder="Why is this strike needed?"]'),
  ).toBeNull();
  expect(window.confirm).not.toHaveBeenCalled();
});

it("starts empty, searches Discord members and requires choosing a linked account with TH and clan", async () => {
  transport.mockImplementation(async (path: string) => {
    if (path.startsWith("/strikes/targets?"))
      return {
        accounts: [],
        members: [{ id: "42", name: "Birch member", accounts: [] }],
      };
    if (path === "/strikes/members/42/accounts")
      return {
        member: {
          id: "42",
          name: "Birch member",
          accounts: [
            {
              tag: "#Q2Y",
              name: "Birch player",
              town_hall: 17,
              current_clan_name: "Oak",
            },
          ],
        },
      };
    throw Error(path);
  });
  const props = callbacks();
  await render(<ManualStrikeEditor {...props} />);
  expect(host.textContent).not.toContain("Adding a strike to");
  expect(transport).not.toHaveBeenCalled();
  await input('[placeholder="Name, tag or Discord member"]', "Birch");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent?.includes("Birch member"))!
      .click(),
  );
  expect(host.textContent).toContain("TH 17 · Oak");
  expect(host.textContent).not.toContain("Adding a strike to");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent?.includes("Birch player"))!
      .click(),
  );
  expect(host.textContent).toContain("Adding a strike to Birch player · Oak");
  expect(transport.mock.calls.every((call) => !call[1])).toBe(true);
});

it("does not display a late result from an older target search", async () => {
  let resolveOld!: (value: object) => void;
  transport.mockImplementation(async (path: string) => {
    if (path.includes("Older"))
      return new Promise((resolve) => {
        resolveOld = resolve;
      });
    return {
      members: [],
      accounts: [
        {
          tag: "#Q2Y",
          name: "Current player",
          town_hall: 16,
          current_clan_name: "Oak",
        },
      ],
    };
  });
  await render(<ManualStrikeEditor {...callbacks()} />);
  await input('[placeholder="Name, tag or Discord member"]', "Older");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  await input('[placeholder="Name, tag or Discord member"]', "Current");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  await act(async () =>
    resolveOld({
      members: [],
      accounts: [{ tag: "#P2Y", name: "Old player" }],
    }),
  );
  expect(host.textContent).toContain("Current player");
  expect(host.textContent).not.toContain("Old player");
});
