// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ParticipationRecord from "./ParticipationRecord";
import { ApiError } from "./api";
import type { ParticipationAccount } from "./participation";
import type { Infractions } from "./useInfractions";
vi.mock("./useDiscordIdentities", () => ({
  default: () => ({ members: {}, loading: false }),
}));
const account = {
  tag: "#PYY",
  player_name: "Fixture",
  pool: "lazy",
  town_hall: 16,
  user_id: null,
  assigned_clan_tag: "#PQQ",
  assigned_clan_name: "Family",
  attacks: 4,
  stars: 9,
  notes: "",
  revision: 1,
  updated_by: null,
  updated_at: null,
  in_latest_publication: true,
  source_status: "complete",
  source_complete: true,
} as ParticipationAccount;
const raffle = (review: object | null = null) =>
  ({
    revision: 4,
    cycle: "2026-11",
    season_status: "draft",
    draws: [],
    accounts: [{ ...account, bonus_review: review }],
  }) as unknown as NonNullable<Infractions["data"]>;
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const load = vi.fn();
const saveInfractions = vi.fn();
const onDirty = vi.fn();
const infractions = (patch: Partial<Infractions> = {}): Infractions => ({
  data: raffle(),
  state: "idle",
  load,
  save: saveInfractions,
  lock: () => null,
  ...patch,
});
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
        open
        onOpen={() => {}}
        onClose={() => {}}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onDirty={onDirty}
        infractions={infractions()}
        {...props}
      />,
    ),
  );
const section = () => host.querySelector(".participation-infractions");
const named = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.trim() === name,
  )!;
beforeEach(() => {
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
  load.mockReset();
  saveInfractions.mockReset().mockResolvedValue(undefined);
  saveNotes.mockReset();
  onDirty.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows Infractions for a Lazy player with a hosting clan", async () => {
  await render();
  expect(section()?.querySelector("h3")?.textContent).toBe("Infractions");
  expect(section()?.querySelectorAll('input[type="checkbox"]')).toHaveLength(3);
  expect(section()?.querySelector("textarea")).not.toBeNull();
});

it("hides Infractions for Main, without a bonus grant and without a clan", async () => {
  await render({ account: { ...account, pool: "main" } });
  expect(section()).toBeNull();
  await render({ infractions: undefined });
  expect(section()).toBeNull();
  await render({ account: { ...account, assigned_clan_tag: null } });
  expect(section()).toBeNull();
});

it("reads the bonus data only when Details opens", async () => {
  await render({ open: false, infractions: infractions({ data: null }) });
  expect(load).not.toHaveBeenCalled();
  await render({ open: true, infractions: infractions({ data: null }) });
  expect(load).toHaveBeenCalledTimes(1);
});

it("shows Loading while it loads and keeps the rest of Details usable", async () => {
  await render({
    infractions: infractions({ data: null, state: "loading" }),
  });
  expect(section()?.textContent).toContain("Loading infractions…");
  expect(host.querySelector("textarea[name='notes']")).not.toBeNull();
});

it("shows Unavailable with Retry when the read fails", async () => {
  await render({ infractions: infractions({ data: null, state: "failed" }) });
  expect(section()?.textContent).toContain("Infractions unavailable ·");
  await act(async () => named("Retry").click());
  expect(load).toHaveBeenCalledTimes(1);
});

it("saves the selected flags and the reason, then says what changed", async () => {
  await render();
  await act(async () =>
    section()!
      .querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[2]
      .click(),
  );
  expect(onDirty).toHaveBeenLastCalledWith("#PYY", true);
  await act(async () => named("Save").click());
  expect(saveInfractions).toHaveBeenCalledWith("#PYY", ["left_family"], "");
  expect(section()?.textContent).toContain(
    "Infractions saved · Family eligibility updated.",
  );
});

it("is read only once the draw is saved", async () => {
  await render({ infractions: infractions({ lock: () => "draw" }) });
  expect(section()?.textContent).toContain("Draw saved · read only");
  expect(named("Save infractions")).toBeUndefined();
  expect(section()?.querySelector("button")).toBeNull();
  expect(named("Save").disabled).toBe(true);
  expect(section()?.querySelector("fieldset")?.disabled).toBe(true);
});

it("is read only for an archived season or without the manage grant", async () => {
  await render({ infractions: infractions({ lock: () => "locked" }) });
  expect(section()?.textContent).toContain("Read only");
  expect(named("Save infractions")).toBeUndefined();
  expect(section()?.querySelector("textarea")?.disabled).toBe(true);
});

it("puts no infraction chips on the overview card", async () => {
  await render({
    open: false,
    infractions: infractions({
      data: raffle({ flags: ["lingering"], override_reason: "Played" }),
    }),
  });
  expect(host.querySelectorAll(".roster-ui-chip")).toHaveLength(0);
});

it("closing with unsaved infractions asks before discarding", async () => {
  await render();
  await act(async () =>
    section()!
      .querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[0]
      .click(),
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(".participation-dialog-actions button")!
      .click(),
  );
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved changes for Fixture?",
  );
  expect(saveInfractions).not.toHaveBeenCalled();
});

const tick = (index: number) =>
  act(async () =>
    section()!
      .querySelectorAll<HTMLInputElement>('input[type="checkbox"]')
      [index].click(),
  );
const typeNotes = (value: string) =>
  act(async () => {
    const notes = host.querySelector<HTMLTextAreaElement>(
      "textarea[name='notes']",
    )!;
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(notes, value);
    notes.dispatchEvent(new Event("input", { bubbles: true }));
  });
const footer = () => host.querySelector(".participation-dialog-actions")!;
const saveNotes = vi.fn();
const withNotes = () =>
  saveNotes.mockImplementation(async (...args: unknown[]) => ({
    ...account,
    notes: args[4] as string,
    revision: 2,
  }));

it("the footer has one Cancel and one Save, and the section has none", async () => {
  await render();
  expect(
    [...footer().querySelectorAll("button")].map(
      (button) => button.textContent,
    ),
  ).toEqual(["Cancel", "Save"]);
  expect(section()?.querySelector("button")).toBeNull();
  expect(named("Save").disabled).toBe(true);
});

it("Save writes notes only when only notes changed", async () => {
  withNotes();
  await render({ onSave: saveNotes });
  await typeNotes("Hello");
  await act(async () => named("Save").click());
  expect(saveNotes).toHaveBeenCalledTimes(1);
  expect(saveInfractions).not.toHaveBeenCalled();
});

it("Save writes infractions only when only infractions changed", async () => {
  await render({ onSave: saveNotes });
  await tick(1);
  await act(async () => named("Save").click());
  expect(saveNotes).not.toHaveBeenCalled();
  expect(saveInfractions).toHaveBeenCalledWith("#PYY", ["lingering"], "");
});

it("Save writes notes then infractions when both changed", async () => {
  withNotes();
  const order: string[] = [];
  saveNotes.mockImplementationOnce(async (...args: unknown[]) => {
    order.push("notes");
    return { ...account, notes: args[4] as string, revision: 2 };
  });
  saveInfractions.mockImplementationOnce(async () => {
    order.push("infractions");
  });
  await render({ onSave: saveNotes });
  await typeNotes("Hello");
  await tick(0);
  await act(async () => named("Save").click());
  expect(order).toEqual(["notes", "infractions"]);
});

it("a failed infractions part keeps the sheet open and dirty, and says so", async () => {
  withNotes();
  saveInfractions.mockRejectedValueOnce(new Error("Revision changed."));
  const close = vi.fn();
  await render({ onSave: saveNotes, onClose: close });
  await typeNotes("Hello");
  await tick(0);
  await act(async () => named("Save").click());
  expect(saveNotes).toHaveBeenCalledTimes(1);
  expect(section()?.textContent).toContain(
    "Infractions not saved · Revision changed.",
  );
  expect(section()?.textContent).not.toContain("Infractions saved");
  expect(close).not.toHaveBeenCalled();
  expect(
    section()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!
      .checked,
  ).toBe(true);
  expect(named("Save").disabled).toBe(false);
});

it("a failed notes part still saves infractions and says what failed", async () => {
  saveNotes.mockRejectedValueOnce(new Error("Changed by someone else."));
  const close = vi.fn();
  await render({ onSave: saveNotes, onClose: close });
  await typeNotes("Hello");
  await tick(0);
  await act(async () => named("Save").click());
  expect(host.textContent).toContain(
    "Notes not saved · Changed by someone else.",
  );
  expect(saveInfractions).toHaveBeenCalledTimes(1);
  expect(section()?.textContent).toContain("Infractions saved");
  expect(close).not.toHaveBeenCalled();
  expect(
    host.querySelector<HTMLTextAreaElement>("textarea[name='notes']")!.value,
  ).toBe("Hello");
});

it("a conflict shows the error, keeps the draft, and replaces it only after the reload", async () => {
  saveInfractions.mockRejectedValueOnce(new ApiError("Data moved on.", 409));
  await render();
  await tick(2);
  await act(async () => named("Save").click());
  expect(section()?.textContent).toContain(
    "Infractions not saved · Data moved on.",
  );
  expect(section()?.textContent).not.toContain("Infractions saved");
  const boxes = () =>
    [
      ...section()!.querySelectorAll<HTMLInputElement>(
        'input[type="checkbox"]',
      ),
    ].map((box) => box.checked);
  expect(boxes()).toEqual([false, false, true]);
  await render({
    infractions: infractions({
      data: raffle({
        flags: ["missed_sync"],
        override_reason: "",
        revision: 5,
        updated_at: "2026-11-12T10:00:00Z",
      }),
    }),
  });
  expect(boxes()).toEqual([true, false, false]);
});

it("unsaved infractions alone mark the player dirty, and clearing them clears it", async () => {
  await render();
  await tick(0);
  expect(onDirty).toHaveBeenLastCalledWith("#PYY", true);
  await tick(0);
  expect(onDirty).toHaveBeenLastCalledWith("#PYY", false);
});
