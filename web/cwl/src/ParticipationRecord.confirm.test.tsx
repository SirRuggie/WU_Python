// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ParticipationRecord from "./ParticipationRecord";
import type { ParticipationAccount } from "./participation";
vi.mock("./useDiscordIdentities", () => ({
  default: () => ({ members: {}, loading: false }),
}));
const account: ParticipationAccount = {
  tag: "#PYY",
  player_name: "Fixture",
  pool: "main",
  town_hall: 16,
  assigned_clan_tag: "#PQQ",
  assigned_clan_name: "Family",
  attacks: 2,
  stars: 6,
  notes: "Saved",
  revision: 1,
  updated_by: null,
  updated_at: null,
  in_latest_publication: true,
  source_status: "ready",
  source_complete: true,
  source_attacks: 3,
  source_stars: 9,
  attacks_override: true,
  stars_override: true,
};
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const reset = vi.fn(),
  save = vi.fn(),
  close = vi.fn();
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
const render = (locked = false) =>
  act(async () =>
    root.render(
      <ParticipationRecord
        account={account}
        publicationVersion={1}
        readonly={false}
        locked={locked}
        open
        onOpen={() => {}}
        onClose={close}
        onSave={save}
        onReset={reset}
        onDirty={() => {}}
      />,
    ),
  );
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
  reset.mockReset().mockResolvedValue(account);
  save.mockReset();
  close.mockReset();
  await render();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("Use synced results cancels without writes and confirms once despite double tap", async () => {
  await act(async () => button("Use synced results").click());
  expect(reset).not.toHaveBeenCalled();
  expect(save).not.toHaveBeenCalled();
  const dialog = document.querySelector(".confirm-dialog")!;
  await act(async () => button("Cancel", dialog).click());
  expect(reset).not.toHaveBeenCalled();
  await act(async () => {
    button("Use synced results").click();
    button("Use synced results").click();
  });
  await act(async () => {
    const confirm = button(
      "Use synced results",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(reset).toHaveBeenCalledTimes(1);
  expect(reset).toHaveBeenCalledWith(account);
  expect(save).not.toHaveBeenCalled();
});
it("permission/lock change cancels a pending decision", async () => {
  await act(async () => button("Use synced results").click());
  await render(true);
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(reset).not.toHaveBeenCalled();
});
it("closing during reset cannot write twice", async () => {
  let finish!: (value: ParticipationAccount) => void;
  reset.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () => button("Use synced results").click());
  await act(async () =>
    button(
      "Use synced results",
      document.querySelector(".confirm-dialog")!,
    ).click(),
  );
  await act(async () => button("Close").click());
  expect(close).not.toHaveBeenCalled();
  await act(async () => finish(account));
  expect(reset).toHaveBeenCalledTimes(1);
});
it("discard editor cancellation retains the draft; confirmed discard closes without writes", async () => {
  const notes = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(notes, "Changed");
    notes.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Close").click());
  expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(notes.value).toBe("Changed");
  expect(close).not.toHaveBeenCalled();
  await act(async () => button("Close").click());
  await act(async () =>
    button(
      "Discard results",
      document.querySelector(".confirm-dialog")!,
    ).click(),
  );
  expect(close).toHaveBeenCalledTimes(1);
  expect(reset).not.toHaveBeenCalled();
  expect(save).not.toHaveBeenCalled();
});
