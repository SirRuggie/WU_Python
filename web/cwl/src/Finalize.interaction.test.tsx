// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PublicationWorkspace from "./PublicationWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({
  api,
  ApiError: class extends Error {
    status = 409;
  },
}));
vi.mock("./ClanRosterImages", () => ({ default: () => null }));
vi.mock("./ManageBridgeWorkspace", () => ({ default: () => null }));
vi.mock("./StaffPlayerButton", () => ({
  default: ({ rosterUi }: { rosterUi?: boolean }) => (
    <button data-roster-ui={rosterUi}>Details</button>
  ),
}));
let host: HTMLDivElement, root: Root;
const dirty = vi.fn(),
  navigate = vi.fn();
const base = () => ({
  draft_revision: 9,
  draft_changed: false,
  next_version: 4,
  published: null,
  last_publication: {
    version: 3,
    published_at: "2026-10-27T00:00:00Z",
    withdrawn_at: "2026-10-28T00:00:00Z",
    joining_instructions: "Join after war\nThanks",
  },
  preview: {
    accounts: [
      {
        tag: "#P",
        player_name: "Ann",
        pool: "main",
        effective_weight: 170000,
        assigned_clan_tag: "#A",
      },
    ],
    clans: [{ tag: "#A", name: "Clan A", effective_capacity: 15 }],
    assigned_count: 1,
    unassigned_count: 0,
  },
});
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  api.mockReset();
  dirty.mockReset();
  navigate.mockReset();
  api.mockResolvedValue(base());
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
async function render(owner = true) {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner, permissions: [] }}>
        <PublicationWorkspace
          seasonId="1"
          seasons={
            [{ id: 1, label: "November 2026", status: "draft" }] as never
          }
          onSeasonChange={() => {}}
          onFix={navigate}
          step="review"
          onStepChange={() => {}}
          onDirty={dirty}
        />
      </DashboardPermissions.Provider>,
    ),
  );
}
function button(label: string, node: ParentNode = host) {
  return [...node.querySelectorAll<HTMLButtonElement>("button")].find(
    (e) => e.textContent === label,
  )!;
}
async function type(text: string) {
  const input = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("prefills withdrawn instructions, keeps preview whitespace and protects local edits across refresh", async () => {
  await render();
  expect(host.querySelector("textarea")!.value).toBe("Join after war\nThanks");
  expect(host.textContent).toContain(
    "Hidden from members · last published version 3",
  );
  expect(
    host.querySelector<HTMLElement>(".joining-instructions-editor .card p")!
      .style.whiteSpace,
  ).toBe("pre-wrap");
  await type("Edited instructions");
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(host.textContent).toContain("Joining instructions changed");
  await act(async () => button("Refresh draft").click());
  expect(host.querySelector("textarea")!.value).toBe("Edited instructions");
  expect(api.mock.calls.every((call) => !call[1])).toBe(true);
});
it("shows the counter at 1800 and blocks publish above 2000", async () => {
  await render();
  await type("x".repeat(1799));
  expect(host.textContent).not.toContain("/ 2,000 characters");
  await type("x".repeat(1800));
  expect(host.textContent).toContain("1800 / 2,000 characters");
  await type("x".repeat(2001));
  expect(host.querySelector("textarea")!.getAttribute("aria-invalid")).toBe(
    "true",
  );
  expect(button("Publish roster").disabled).toBe(true);
  await type("x".repeat(2000));
  expect(button("Publish roster").disabled).toBe(false);
});
it("sends edited instructions only after explicit publish confirmation, once", async () => {
  await render();
  await type("New instructions");
  await act(async () => button("Publish roster").click());
  expect(document.querySelector("dialog")!.textContent).toContain(
    "Publish version 4?",
  );
  expect(api.mock.calls.every((call) => !call[1])).toBe(true);
  api.mockImplementation(async (_path: string, method?: string) =>
    method === "POST"
      ? {
          published: {
            version: 4,
            revision: 9,
            joining_instructions: "New instructions",
          },
        }
      : base(),
  );
  const confirm = button("Publish roster", document.querySelector("dialog")!);
  await act(async () => {
    confirm.click();
    confirm.click();
  });
  const writes = api.mock.calls.filter((call) => call[1] === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0][2]).toEqual({
    revision: 9,
    acknowledge_unassigned: false,
    joining_instructions: "New instructions",
  });
});
it("blocks publishing without permission and requires acknowledgement only when unassigned", async () => {
  await render(false);
  expect(button("Publish roster").disabled).toBe(true);
  await render(true);
  expect(button("Publish roster").disabled).toBe(false);
  api.mockResolvedValue({
    ...base(),
    preview: { ...base().preview, unassigned_count: 1, assigned_count: 0 },
  });
  await act(async () => button("Refresh draft").click());
  expect(button("Publish roster").disabled).toBe(true);
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  expect(button("Publish roster").disabled).toBe(false);
});

it("uses a danger confirmation for Hide, Cancel sends no write, and a successful hide shows history", async () => {
  const published = {
    version: 3,
    revision: 8,
    published_at: "2026-10-27T00:00:00Z",
    joining_instructions: "Join",
  };
  let hidden = false;
  api.mockImplementation(async (path: string, method?: string) => {
    if (path.includes("export-preview"))
      return {
        rows: base().preview.accounts,
        summary: { published_version: 3 },
      };
    if (method === "POST") {
      hidden = true;
      return {};
    }
    return { ...base(), published: hidden ? null : published };
  });
  await render(false);
  expect(button("Hide roster from members")).toBeUndefined();
  await render(true);
  await act(async () => button("Hide roster from members").click());
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain(
    "The working roster and signups are kept.",
  );
  expect(button("Hide roster", dialog).className).toBe("confirm-danger");
  expect(
    button("Cancel", dialog).hasAttribute("autofocus") ||
      document.activeElement === button("Cancel", dialog),
  ).toBe(true);
  await act(async () => button("Cancel", dialog).click());
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(0);
  await act(async () => button("Hide roster from members").click());
  await act(async () =>
    button("Hide roster", document.querySelector("dialog")!).click(),
  );
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(1);
  expect(host.textContent).toContain(
    "Hidden from members · last published version 3",
  );
  expect(button("Hide roster from members")).toBeUndefined();
});

it("uses the roster season menu, capacity preview and roster-styled Details", async () => {
  const data = base();
  data.preview.clans[0].effective_capacity = 0;
  api.mockResolvedValue(data);
  await render();
  expect(host.querySelector("select")).toBeNull();
  expect(host.querySelector('button[aria-label="Season"]')).not.toBeNull();
  expect(host.querySelector(".publication-group")!.textContent).toContain(
    "1 / 0",
  );
  expect(host.querySelector('[data-roster-ui="true"]')).not.toBeNull();
});

it("guards reload only while instructions are dirty and identifies instructions-only edits", async () => {
  const data = {
    ...base(),
    published: {
      version: 3,
      revision: 8,
      published_at: "2026-10-27T00:00:00Z",
      joining_instructions: "Original",
    },
  };
  api.mockImplementation(async (path: string) =>
    path.includes("export-preview")
      ? { rows: data.preview.accounts, summary: { published_version: 3 } }
      : data,
  );
  await render();
  expect(host.querySelector("textarea")!.value).toBe("Original");
  expect(host.textContent).not.toContain("Joining instructions changed");
  const clean = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
  await type("Only instructions changed");
  expect(host.textContent).toContain("Joining instructions changed");
  const dirtyEvent = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(dirtyEvent);
  expect(dirtyEvent.defaultPrevented).toBe(true);
  await type("Original");
  const restored = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(restored);
  expect(restored.defaultPrevented).toBe(false);
});

it("rejects Hide after a real draft refetch changes the revision", async () => {
  let data = {
    ...base(),
    published: {
      version: 3,
      revision: 8,
      published_at: "2026-10-27T00:00:00Z",
      joining_instructions: "Join",
    },
  };
  api.mockImplementation(async (path: string) =>
    path.includes("export-preview")
      ? { rows: data.preview.accounts, summary: { published_version: 3 } }
      : data,
  );
  await render();
  await act(async () => button("Hide roster from members").click());
  data = { ...data, draft_revision: 10 };
  await act(async () => button("Refresh draft").click());
  await act(async () =>
    button("Hide roster", document.querySelector("dialog")!).click(),
  );
  expect(host.textContent).toContain(
    "The draft changed. Refresh draft and review it before hiding the roster.",
  );
  expect(api.mock.calls.some((call) => call[1] === "POST")).toBe(false);
});
