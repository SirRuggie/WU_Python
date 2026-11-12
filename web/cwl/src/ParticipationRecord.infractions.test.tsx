// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ParticipationRecord from "./ParticipationRecord";
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
  await act(async () => named("Save infractions").click());
  expect(saveInfractions).toHaveBeenCalledWith("#PYY", ["left_family"], "");
  expect(section()?.textContent).toContain(
    "Infractions saved · Family eligibility updated.",
  );
});

it("is read only once the draw is saved", async () => {
  await render({ infractions: infractions({ lock: () => "draw" }) });
  expect(section()?.textContent).toContain("Draw saved · read only");
  expect(named("Save infractions")).toBeUndefined();
  expect(section()?.querySelector("fieldset")?.disabled).toBe(true);
});

it("is read only for an archived season or without the manage grant", async () => {
  await render({ infractions: infractions({ lock: () => "locked" }) });
  expect(section()?.textContent).toContain("Read only");
  expect(named("Save infractions")).toBeUndefined();
  expect(section()?.querySelector("textarea")?.disabled).toBe(true);
});

it("puts a chip on the card for each set flag and the staff reason", async () => {
  await render({
    open: false,
    infractions: infractions({
      data: raffle({ flags: ["lingering"], override_reason: "Played" }),
    }),
  });
  const chips = [...host.querySelectorAll(".roster-ui-chip")].map(
    (chip) => chip.textContent,
  );
  expect(chips).toEqual(["Lingering", "Staff reason"]);
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
