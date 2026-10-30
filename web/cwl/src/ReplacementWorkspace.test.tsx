// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import ReplacementWorkspace from "./ReplacementWorkspace";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const row = {
  player_tag: "#P2Y",
  player_name: "Sample",
  clan_tag: "#R2Y",
  clan_name: "Family",
  active_strikes: 4,
  revision: 7,
  priority: "high",
  note: "Original",
  is_manual: true,
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue({
    candidates: [row],
    clans: [{ tag: "#R2Y", name: "Family" }],
    groups: [
      {
        clan_tag: "#R2Y",
        clan_name: "Family",
        listed: 1,
        at_three: 1,
        chopping_block: 0,
      },
    ],
    top: [row],
    total: 1,
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const button = (text: string) =>
  [...document.body.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
async function render() {
  await act(async () =>
    root.render(<ReplacementWorkspace permissions={[]} isOwner />),
  );
  await act(async () =>
    (
      host.querySelector(".replacement-group-summary") as HTMLButtonElement
    ).click(),
  );
}
async function click(text: string) {
  expect(button(text)).toBeDefined();
  await act(async () => button(text).click());
}
async function input(node: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("retains a conflicting edit and only changes its baseline after explicit Reload", async () => {
  await render();
  await click("Edit");
  const note = [...host.querySelectorAll("input")].find(
    (n) => n.value === "Original",
  )!;
  expect(note).toBeDefined();
  await input(note, "Keep my text");
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method) throw new ApiError("Changed by someone else · Reload", 409);
    return {
      revision: 8,
      priority: "replace_first",
      note: "Their note",
    } as never;
  });
  await click("Save");
  expect(note.isConnected).toBe(true);
  expect(note.value).toBe("Keep my text");
  expect(host.textContent).toContain("Changed by someone else");
  expect(api).toHaveBeenCalledWith("/strikes/replacement-list/%23P2Y", "PUT", {
    priority: "high",
    note: "Keep my text",
    revision: 7,
  });
  await click("Reload list");
  expect(host.textContent).toContain(
    'Saved by someone else: Chopping Block · "Their note"',
  );
  expect(note.value).toBe("Keep my text");
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method ? ({} as never) : ({ candidates: [row], clans: [] } as never),
  );
  await click("Save");
  expect(api).toHaveBeenCalledWith("/strikes/replacement-list/%23P2Y", "PUT", {
    priority: "high",
    note: "Keep my text",
    revision: 8,
  });
});
it("clears with its displayed revision through an in-app confirmation", async () => {
  const confirm = vi.fn();
  vi.stubGlobal("confirm", confirm);
  await render();
  await click("Edit");
  await click("Clear priority");
  expect(host.textContent).toContain("Strike history stays.");
  expect(confirm).not.toHaveBeenCalled();
  await click("Clear");
  expect(api).toHaveBeenCalledWith(
    "/strikes/replacement-list/%23P2Y",
    "DELETE",
    { revision: 7 },
  );
  vi.unstubAllGlobals();
});

it("starts collapsed with Top 10 and requests the fixed threshold, TH and sort filters", async () => {
  await act(async () =>
    root.render(<ReplacementWorkspace permissions={[]} isOwner />),
  );
  expect(host.textContent).toContain("Top 10 across all clans");
  expect(host.textContent).toContain("Got a recruit? Enter their weight");
  expect(
    host
      .querySelector(".replacement-group-summary")
      ?.getAttribute("aria-expanded"),
  ).toBe("false");
  expect(host.querySelectorAll(".replacement-row")).toHaveLength(0);
  const check = host.querySelector(
    'input[type="checkbox"]',
  ) as HTMLInputElement;
  await act(async () => check.click());
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toContain("include_low=true");
  const select = [...host.querySelectorAll("select")].find((n) =>
    n.textContent?.includes("Most strikes"),
  )!;
  await act(async () => {
    select.value = "strikes";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toContain("sort=strikes");
});

it("restores filters and expanded clans when returning from strike history", async () => {
  const memory = new Map<string, unknown>();
  const onHistory = vi.fn();
  const show = () =>
    root.render(
      <ReplacementWorkspace
        permissions={[]}
        isOwner
        memory={memory}
        onHistory={onHistory}
      />,
    );
  await act(async () => show());
  await act(async () =>
    (
      host.querySelector(".replacement-group-summary") as HTMLButtonElement
    ).click(),
  );
  const search = host.querySelector<HTMLInputElement>(
    'input[placeholder="Name or player tag"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(search, "Sample");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    (
      host.querySelector(".replacement-identity a") as HTMLAnchorElement
    ).click(),
  );
  expect(onHistory).toHaveBeenCalledWith("#P2Y");
  await act(async () => root.render(<div>Strike history</div>));
  await act(async () => show());
  expect(
    host.querySelector<HTMLInputElement>(
      'input[placeholder="Name or player tag"]',
    )!.value,
  ).toBe("Sample");
  expect(
    host
      .querySelector(".replacement-group-summary")
      ?.getAttribute("aria-expanded"),
  ).toBe("true");
});

it("shows an existing tag mark before editing and preserves its note on Save", async () => {
  await render();
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (!method && path === "/strikes/replacement-list/%23P2Y")
      return {
        revision: 7,
        priority: "replace_first",
        note: "Keep this note",
        is_manual: true,
      } as never;
    return { candidates: [row], clans: [] } as never;
  });
  await click("Add accounts");
  const select = host.querySelector(
    ".replacement-add-mode select",
  ) as HTMLSelectElement;
  await act(async () => {
    select.value = "tag";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await input(host.querySelector(".replacement-tag-choice input")!, "#P2Y");
  expect(host.textContent).toContain(
    'Already marked: Chopping Block · "Keep this note"',
  );
  expect(button("Add account").disabled).toBe(true);
  await click("Edit instead");
  expect(
    (host.querySelector(".replacement-add-details input") as HTMLInputElement)
      .value,
  ).toBe("Keep this note");
  await click("Save");
  expect(api).toHaveBeenCalledWith("/strikes/replacement-list", "POST", {
    player_tag: "#P2Y",
    revision: 7,
    priority: "replace_first",
    note: "Keep this note",
  });
});

it("Clear after a conflict reload uses the visible saved revision", async () => {
  await render();
  await click("Edit");
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method) throw new ApiError("Changed", 409);
    return { revision: 8, priority: "normal", note: "New saved note" } as never;
  });
  await click("Save");
  await click("Reload list");
  expect(host.textContent).toContain(
    'Saved by someone else: Normal · "New saved note"',
  );
  vi.mocked(api).mockResolvedValue({ candidates: [row], clans: [] } as never);
  await click("Clear priority");
  await click("Clear");
  expect(api).toHaveBeenCalledWith(
    "/strikes/replacement-list/%23P2Y",
    "DELETE",
    { revision: 8 },
  );
});
