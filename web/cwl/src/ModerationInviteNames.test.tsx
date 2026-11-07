// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import InviteNames, { rankInviteCodes } from "./ModerationInviteNames";
import type { InviteRow } from "./moderationSettingsModel";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
const rows: InviteRow[] = [
  {
    code: "alpha",
    name: null,
    uses: 5,
    max_uses: 100,
    inviter_id: "1",
    inviter_name: "Alice",
    channel_id: "2",
    channel_name: "welcome",
    expires_at: null,
    vanity: false,
  },
  {
    code: "beta",
    name: null,
    uses: 20,
    max_uses: null,
    inviter_id: null,
    inviter_name: "Bob",
    channel_id: null,
    channel_name: null,
    expires_at: null,
    vanity: false,
  },
  {
    code: "gamma",
    name: null,
    uses: 5,
    max_uses: null,
    inviter_id: null,
    inviter_name: null,
    channel_id: null,
    channel_name: null,
    expires_at: null,
    vanity: false,
  },
  {
    code: "warriors",
    name: null,
    uses: 40,
    max_uses: null,
    inviter_id: null,
    inviter_name: null,
    channel_id: null,
    channel_name: null,
    expires_at: null,
    vanity: true,
  },
];
let root: Root, host: HTMLDivElement;
function Harness({ initial = {} }: { initial?: Record<string, string> }) {
  const [names, setNames] = useState(initial);
  const [reset, setReset] = useState(0);
  return (
    <>
      <InviteNames
        names={names}
        savedNames={initial}
        resetKey={String(reset)}
        disabled={false}
        onName={(code, name) =>
          setNames((current) => {
            const next = { ...current };
            if (name) next[code] = name;
            else delete next[code];
            return next;
          })
        }
      />
      <button
        onClick={() => {
          setNames(initial);
          setReset((value) => value + 1);
        }}
      >
        Discard fixture edits
      </button>
    </>
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(api)
    .mockReset()
    .mockResolvedValue({ invites: rows, updated_at: null });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function render(initial: Record<string, string> = {}) {
  await act(async () => root.render(<Harness initial={initial} />));
}
function row(code: string, group = "") {
  return [
    ...host.querySelectorAll<HTMLElement>(`${group} [data-invite-code]`),
  ].find((node) => node.dataset.inviteCode === code)!;
}
async function edit(code: string) {
  const target = row(code);
  const details = target.closest("details");
  if (details && !details.open)
    await act(async () => details.querySelector("summary")!.click());
  await act(async () =>
    target.querySelector<HTMLButtonElement>("[data-invite-action]")!.click(),
  );
  return host.querySelector<HTMLInputElement>(`[data-invite-name="${code}"]`)!;
}
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const codes = () =>
  [...host.querySelectorAll<HTMLElement>("[data-invite-code]")]
    .map((node) => node.dataset.inviteCode)
    .sort();
it("ranks by uses then name and keeps stale names last", () => {
  expect(
    rankInviteCodes(["alpha", "gamma", "beta", "gone"], rows, {
      alpha: "Zulu",
      gamma: "Alpha",
      beta: "Beta",
      gone: "Old",
    }),
  ).toEqual(["beta", "gamma", "alpha", "gone"]);
});
it("starts empty saved links and closed other invites without dropping active links or vanity URLs", async () => {
  await render();
  expect(host.textContent).toContain("No saved links yet.");
  expect(
    host.querySelector<HTMLDetailsElement>(".moderation-other-invites")!.open,
  ).toBe(false);
  expect(host.querySelector("summary")!.textContent).toBe("4 other invites");
  expect(codes()).toEqual(rows.map((row) => row.code).sort());
  expect(
    host.querySelector('a[href="https://discord.gg/warriors"]')?.textContent,
  ).toBe("discord.gg/warriors");
});
it("moves on valid Enter and blur, preserves rank, follows focus and keeps every link", async () => {
  await render();
  const first = await edit("alpha");
  await type(first, "Reddit");
  expect(row("alpha", ".moderation-other-invites")).toBeTruthy();
  await act(async () =>
    first.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    ),
  );
  expect(row("alpha", ".moderation-saved-invites")).toBeTruthy();
  expect(document.activeElement?.getAttribute("data-invite-action")).toBe(
    "alpha",
  );
  expect(row("alpha").textContent).toContain("Reddit · 5 / 100");
  expect(row("alpha").textContent).toContain("Unsaved changes");
  const second = await edit("beta");
  await type(second, "Partner");
  await act(async () => second.blur());
  expect(
    [
      ...host.querySelectorAll<HTMLElement>(
        ".moderation-saved-invites [data-invite-code]",
      ),
    ].map((node) => node.dataset.inviteCode),
  ).toEqual(["beta", "alpha"]);
  expect(document.activeElement?.getAttribute("data-invite-action")).toBe(
    "beta",
  );
  expect(codes()).toEqual(rows.map((row) => row.code).sort());
  expect(
    vi
      .mocked(api)
      .mock.calls.every(([, method]) => !method || method === "GET"),
  ).toBe(true);
});
it("keeps empty/invalid drafts in other invites and Discard restores grouping", async () => {
  await render();
  const input = await edit("alpha");
  await act(async () =>
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    ),
  );
  expect(row("alpha", ".moderation-other-invites")).toBeTruthy();
  await type(input, "bad\u200bname");
  await act(async () => input.blur());
  expect(row("alpha", ".moderation-other-invites")).toBeTruthy();
  expect(
    host
      .querySelector('[data-invite-name="alpha"]')
      ?.getAttribute("aria-invalid"),
  ).toBe("true");
  expect(host.textContent).toContain("Remove control or invisible characters.");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Discard fixture edits")!
      .click(),
  );
  expect(host.querySelector(".moderation-invite-editor")).toBeNull();
  expect(host.textContent).toContain("No saved links yet.");
  expect(codes()).toEqual(rows.map((row) => row.code).sort());
});
it("Remove name moves an active link back without dropping links", async () => {
  await render({ alpha: "Reddit", beta: "Partner" });
  await edit("alpha");
  const remove = host.querySelector<HTMLButtonElement>(
    '[aria-label="Remove name for alpha"]',
  )!;
  await act(async () => {
    remove.focus();
    remove.click();
  });
  expect(row("alpha", ".moderation-other-invites")).toBeTruthy();
  expect(
    host.querySelector<HTMLDetailsElement>(".moderation-other-invites")!.open,
  ).toBe(true);
  expect(document.activeElement?.getAttribute("data-invite-action")).toBe(
    "alpha",
  );
  expect(row("beta", ".moderation-saved-invites")).toBeTruthy();
  expect(codes()).toEqual(rows.map((row) => row.code).sort());
});
it("keeps stale saved names and all links when refreshing fails", async () => {
  await render({ gone: "Old", beta: "Partner" });
  expect(
    [
      ...host.querySelectorAll<HTMLElement>(
        ".moderation-saved-invites [data-invite-code]",
      ),
    ].map((node) => node.dataset.inviteCode),
  ).toEqual(["beta", "gone"]);
  expect(row("gone").textContent).toContain("No longer active");
  vi.mocked(api).mockRejectedValueOnce(new Error("Invite list unavailable"));
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Refresh invites")!
      .click(),
  );
  expect(host.textContent).toContain("Invite list unavailable");
  expect(row("gone").textContent).toContain("Old");
  expect(codes()).toEqual([...rows.map((row) => row.code), "gone"].sort());
});

it("respects the next focused control when a saved-name blur does not move lists", async () => {
  await render({ alpha: "Reddit" });
  const input = await edit("alpha");
  await type(input, "Reddit revised");
  const next = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent === "Discard fixture edits",
  )!;
  await act(async () => next.focus());
  expect(document.activeElement).toBe(next);
  expect(row("alpha", ".moderation-saved-invites")).toBeTruthy();
  expect(host.querySelector(".moderation-invite-editor")).toBeNull();
});
