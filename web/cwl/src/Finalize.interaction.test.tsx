// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PublicationWorkspace from "./PublicationWorkspace";
import { ApiError } from "./api";
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
async function render(
  owner = true,
  step: "review" | "announce" = "review",
  status = "draft",
  onStepChange: (step: "review" | "announce") => void = () => {},
) {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner, permissions: [] }}>
        <PublicationWorkspace
          seasonId="1"
          seasons={[{ id: 1, label: "November 2026", status }] as never}
          onSeasonChange={() => {}}
          onFix={navigate}
          step={step}
          onStepChange={onStepChange}
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
  expect(host.textContent).not.toContain("Joining instructions changed");
  expect(dirty).toHaveBeenLastCalledWith(false);
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
  expect(host.textContent).toContain("1,800 / 2,000 characters");
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
  data.preview.accounts = Array.from({ length: 16 }, (_, i) => ({
    ...data.preview.accounts[0],
    tag: `#P${i}`,
  }));
  data.preview.assigned_count = 16;
  api.mockResolvedValue(data);
  await render();
  expect(host.querySelector("select")).toBeNull();
  expect(host.querySelector('button[aria-label="Season"]')).not.toBeNull();
  expect(host.querySelector(".publication-group")!.textContent).toContain(
    "16 / 15",
  );
  expect(host.querySelector(".publication-over")?.textContent).toBe(
    " · +1 over",
  );
  expect(
    host
      .querySelector(".publication-clan-meta")
      ?.classList.contains("publication-over"),
  ).toBe(false);
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

it("makes the single Refresh reachable after a failed direct Announcements load", async () => {
  api.mockRejectedValueOnce(new Error("Read failed"));
  await render(true, "announce");
  expect(button("Refresh draft").closest("[hidden]")).toBeNull();
  expect(
    [...host.querySelectorAll("button")].filter(
      (b) => b.textContent === "Refresh draft",
    ),
  ).toHaveLength(1);
  api.mockResolvedValue(base());
  await act(async () => button("Refresh draft").click());
  expect(host.textContent).not.toContain("Read failed");
  expect(
    api.mock.calls.filter((c) => c[0] === "/seasons/1/publication"),
  ).toHaveLength(2);
});
it("exposes Refresh on Announcements when the reload after successful publish fails", async () => {
  const changeStep = vi.fn();
  function StatefulWorkspace() {
    const [step, setStep] = useState<"review" | "announce">("review");
    return (
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <PublicationWorkspace
          seasonId="1"
          seasons={
            [{ id: 1, label: "November 2026", status: "draft" }] as never
          }
          onSeasonChange={() => {}}
          step={step}
          onFix={navigate}
          onStepChange={(next) => {
            changeStep(next);
            setStep(next);
          }}
        />
      </DashboardPermissions.Provider>
    );
  }
  await act(async () => root.render(<StatefulWorkspace />));
  await act(async () => button("Publish roster").click());
  api.mockImplementation(async (_path: string, method?: string) => {
    if (method === "POST")
      return {
        published: {
          version: 4,
          revision: 9,
          joining_instructions: "Join after war\nThanks",
        },
      };
    throw new Error("Reload failed");
  });
  await act(async () =>
    button("Publish roster", document.querySelector("dialog")!).click(),
  );
  expect(changeStep).toHaveBeenCalledWith("announce");
  expect(button("Refresh draft").closest("[hidden]")).toBeNull();
  expect(host.textContent).toContain("Reload failed");
  expect(api.mock.calls.filter((c) => c[1] === "POST")).toHaveLength(1);
});
it("each check chip passes its exact navigation target, with singular labels", async () => {
  const data = base();
  data.preview.accounts = Array.from({ length: 16 }, (_, i) => ({
    ...data.preview.accounts[0],
    tag: `#P${i}`,
  }));
  data.preview.accounts.push({
    ...data.preview.accounts[0],
    tag: "#U",
    assigned_clan_tag: null,
    effective_weight: null,
  } as never);
  data.preview.unassigned_count = 1;
  api.mockResolvedValue(data);
  await render();
  for (const [label, target] of [
    ["1 missing weight ›", "missing_weight"],
    ["1 account awaiting placement ›", "unassigned"],
    ["1 clan over capacity · +1 ›", "over_capacity"],
  ]) {
    await act(async () => button(label).click());
    expect(navigate).toHaveBeenLastCalledWith(target);
  }
});
it("uses archived wording and old-backend version fallback without undefined", async () => {
  api.mockResolvedValue({ ...base(), next_version: undefined });
  await render();
  expect(host.textContent).toContain("Publishing creates a new version");
  await act(async () => button("Publish roster").click());
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Publish roster?",
  );
  await act(async () =>
    button("Cancel", document.querySelector("dialog")!).click(),
  );
  await render(true, "review", "archived");
  expect(host.textContent).not.toContain("Publishing creates");
  expect(host.textContent?.match(/This season is archived/g)).toHaveLength(1);
  expect(host.textContent).not.toContain("undefined");
});
it("formats the 1850 counter and includes the preview marker", async () => {
  await render();
  await type("x".repeat(1850));
  expect(host.textContent).toContain("1,850 / 2,000 characters");
  expect(host.textContent).toContain("Preview as members see it ›");
});

it("shows only one refresh instruction for a rejected publish conflict", async () => {
  await render();
  await act(async () => button("Publish roster").click());
  api.mockRejectedValue(new ApiError("Roster changed", 409));
  await act(async () =>
    button("Publish roster", document.querySelector("dialog")!).click(),
  );
  const alert = host.querySelector('[role="alert"]')!;
  expect(alert.textContent?.match(/Refresh draft/g)).toHaveLength(1);
  expect(alert.textContent).toContain("Roster changed");
});
