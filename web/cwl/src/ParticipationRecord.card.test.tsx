// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ParticipationRecord, {
  participationMenuItems,
} from "./ParticipationRecord";
import type { ParticipationAccount } from "./participation";
vi.mock("./useDiscordIdentities", () => ({
  default: () => ({ members: {}, loading: false }),
}));
const account: ParticipationAccount = {
  tag: "#PYY",
  player_name: "Fixture",
  pool: "lazy",
  town_hall: 16,
  user_id: "100000000000000001",
  assigned_clan_tag: "#PQQ",
  assigned_clan_name: "Family",
  attacks: 4,
  stars: 9,
  notes: "Saved",
  revision: 1,
  updated_by: null,
  updated_at: null,
  in_latest_publication: true,
  source_status: "complete",
  source_complete: true,
  source_attacks: 4,
  source_stars: 9,
  source_checked_at: "2026-11-01T12:00:00Z",
  previous_results: {
    pool: "lazy",
    assigned_clan_tag: "#OLD",
    assigned_clan_name: "Old host",
    attacks: 1,
    stars: 2,
  },
} as ParticipationAccount;
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const save = vi.fn(),
  reset = vi.fn(),
  open = vi.fn(),
  close = vi.fn();
const render = (
  props: Partial<Parameters<typeof ParticipationRecord>[0]> = {},
) =>
  act(async () =>
    root.render(
      <ParticipationRecord
        account={account}
        publicationVersion={1}
        readonly={false}
        locked={false}
        open={false}
        onOpen={open}
        onClose={close}
        onSave={save}
        onReset={reset}
        onDirty={() => {}}
        {...props}
      />,
    ),
  );
const cardButton = () =>
  host.querySelector<HTMLButtonElement>(
    'button[aria-label="Details for Fixture"]',
  )!;
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  save.mockReset();
  reset.mockReset();
  open.mockReset();
  close.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("opens Details from the card button and has no Details text link", async () => {
  await render();
  const body = cardButton();
  expect(body.tagName).toBe("BUTTON");
  expect(body.getAttribute("type")).toBe("button");
  expect(body.textContent).toBe("Fixture");
  expect(
    [...host.querySelectorAll("button")].some((button) =>
      button.textContent?.trim().startsWith("Details"),
    ),
  ).toBe(false);
  await act(async () => body.click());
  expect(open).toHaveBeenCalledTimes(1);
});

it("the ⋯ menu sits outside the card button and does not open Details", async () => {
  await render();
  const trigger = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Actions for Fixture"]',
  )!;
  expect(trigger).not.toBeNull();
  expect(cardButton().contains(trigger)).toBe(false);
  await act(async () => trigger.click());
  expect(open).not.toHaveBeenCalled();
});

it("menu items are an extendable list with DM and Details", () => {
  const details = vi.fn();
  const items = participationMenuItems({ account, onDetails: details });
  expect(items.map((item) => item.id)).toEqual(["dm", "details"]);
  expect(items[0].href).toBe("https://discord.com/users/100000000000000001");
  items[1].onAction?.(document.createElement("button"));
  expect(details).toHaveBeenCalledTimes(1);
  const unlinked = participationMenuItems({
    account: { ...account, user_id: null },
    onDetails: details,
  });
  expect(unlinked[0]).toMatchObject({ id: "dm", disabled: true });
});

it("Details is a read-only summary with notes and no result inputs", async () => {
  await render({ open: true });
  const dialog = host.querySelector(".participation-dialog")!;
  expect(dialog.querySelector('input[name="attacks"]')).toBeNull();
  expect(dialog.querySelector('input[name="stars"]')).toBeNull();
  expect(dialog.querySelector('input[type="number"]')).toBeNull();
  expect(dialog.textContent).toContain("Family");
  expect(dialog.textContent).toContain("Attacks");
  expect(dialog.textContent).toContain("Stars");
  expect(dialog.textContent).toContain("Old host");
  expect(dialog.querySelector("textarea")!.value).toBe("Saved");
  expect(
    [...dialog.querySelectorAll("button")].some(
      (button) => button.textContent === "Use synced results",
    ),
  ).toBe(false);
});

it("Save sends notes only", async () => {
  save.mockResolvedValue({ ...account, notes: "Changed", revision: 2 });
  await render({ open: true });
  const notes = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(notes, "Changed");
    notes.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const button = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Save notes",
  )!;
  await act(async () => button.click());
  expect(save).toHaveBeenCalledWith(
    account,
    1,
    1,
    "2026-11-01T12:00:00Z",
    "Changed",
  );
});

it("returns focus to the card button when Details closes", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 0;
  });
  await render({ open: true });
  await render({ open: false });
  expect(close).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(cardButton());
  vi.unstubAllGlobals();
});

it("returns focus to the ⋯ trigger when the menu opened Details", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 0;
  });
  await render();
  const trigger = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Actions for Fixture"]',
  )!;
  await act(async () => trigger.click());
  const details = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((item) => item.textContent === "Details")!;
  await act(async () => details.click());
  expect(open).toHaveBeenCalledTimes(1);
  await render({ open: true });
  await render({ open: false });
  expect(document.activeElement).toBe(trigger);
  vi.unstubAllGlobals();
});

it("pressing the card button keeps its overlay in place", () => {
  // Global press feedback scales buttons; a scaled button would become the
  // overlay's containing block and pointerup would miss it.
  const css = readFileSync("src/ParticipationWorkspace.css", "utf8");
  const rule = css.match(/\.participation-card-open:active\s*\{([^}]*)\}/);
  expect(rule?.[1]).toMatch(/scale:\s*none/);
  expect(rule?.[1]).toMatch(/transform:\s*none/);
});
