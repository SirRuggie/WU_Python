// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ClanSettings, { ClanSettingsEditor } from "./ClanSettings";
import { poolChangeReason, settingsClans } from "./clanSettingsModel";
import type { RosterClan } from "./roster";
const clan: RosterClan = {
  tag: "#P2Y",
  name: "Amber Knights",
  pool: "main",
  capacity: 15,
  effective_capacity: 15,
  assigned_count: 16,
  min_weight: 150000,
  max_weight: 170000,
  archived: false,

  cwl_league: "Master League II",
};
let root: Root, host: HTMLDivElement;
const button = (text: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find((e) =>
    e.textContent?.includes(text),
  )!;
const type = async (label: string, value: string) => {
  const input = [...document.querySelectorAll<HTMLInputElement>("input")].find(
    (e) =>
      document.querySelector(`label[for="${e.id}"]`)?.textContent === label,
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  HTMLElement.prototype.scrollIntoView = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("shows no-pool clans in both tabs, excludes archived and other-pool clans", () => {
  const unset = { ...clan, tag: "unset", pool: null },
    lazy = { ...clan, tag: "lazy", pool: "lazy" as const };
  const list = [clan, unset, lazy, { ...clan, tag: "old", archived: true }];
  expect(settingsClans(list, "main").map((c) => c.tag)).toEqual([
    clan.tag,
    "unset",
  ]);
  expect(settingsClans(list, "lazy").map((c) => c.tag)).toEqual([
    "unset",
    "lazy",
  ]);
  expect(poolChangeReason(clan, "lazy")).toContain(
    "16 players are assigned here",
  );
  expect(poolChangeReason({ ...clan, assigned_count: 0 }, "lazy")).toBe("");
  expect(poolChangeReason(unset, "lazy")).toBe("");
});
it("opens on row tap, focuses Close, respects dirty close guard and writes only on Save without lower_league", async () => {
  let dirty = false;
  const leave = vi.fn(() => !dirty),
    save = vi.fn().mockResolvedValue(true);
  await act(async () =>
    root.render(
      <ClanSettings
        clans={[clan]}
        pool="main"
        archived={false}
        busy={false}
        onPoolChange={() => {}}
        onDirty={(v) => {
          dirty = v;
        }}
        onLeave={leave}
        onSave={save}
      />,
    ),
  );
  await act(async () => button("Amber Knights").click());
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Close panel",
  );
  expect(document.body.textContent).not.toContain("Not set");
  await type("Minimum weight", "151");
  await act(async () => button("Close").click());
  expect(leave).toHaveBeenCalled();
  expect(document.querySelector("dialog")).not.toBeNull();
  expect(save).not.toHaveBeenCalled();
  await act(async () => button("Save settings").click());
  expect(save).toHaveBeenCalledWith(clan, {
    pool: "main",
    capacity: 15,
    min_weight: 151000,
    max_weight: 170000,
  });
});
it("archived settings are view-only with no save or inputs", async () => {
  await act(async () =>
    root.render(
      <ClanSettingsEditor
        clan={clan}
        archived
        busy={false}
        trigger={null}
        onClose={() => true}
        onDirty={() => {}}
        onSave={vi.fn()}
      />,
    ),
  );
  expect(document.body.textContent).toContain(
    "Archived season · settings are read-only.",
  );
  expect(document.querySelectorAll("input")).toHaveLength(0);
  expect(button("Save settings")).toBeUndefined();
});
it("requires both setup fields and preserves stale edits", async () => {
  const props = {
    busy: false,
    archived: false,
    trigger: null,
    onClose: () => true,
    onDirty: vi.fn(),
    onSave: vi.fn(),
  };
  await act(async () =>
    root.render(
      <ClanSettingsEditor {...props} clan={{ ...clan, pool: null }} />,
    ),
  );
  expect(button("Set up clan").disabled).toBe(true);
  await type("Minimum weight", "152");
  await act(async () =>
    root.render(
      <ClanSettingsEditor
        {...props}
        clan={{ ...clan, pool: null, min_weight: 153000 }}
      />,
    ),
  );
  expect(document.body.textContent).toContain(
    "Clan settings changed elsewhere",
  );
  expect(button("Set up clan").disabled).toBe(true);
});
it("explains disabled pool choices and never submits via a disabled option", async () => {
  const save = vi.fn();
  await act(async () =>
    root.render(
      <ClanSettingsEditor
        clan={clan}
        archived={false}
        busy={false}
        trigger={null}
        onClose={() => true}
        onDirty={() => {}}
        onSave={save}
      />,
    ),
  );
  await act(async () => button("Main CWL").click());
  const option = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((e) => e.textContent?.includes("Lazy CWL"))!;
  expect(option.getAttribute("aria-disabled")).toBe("true");
  expect(option.textContent).toContain(
    "Can't move to Lazy CWL: 16 players are assigned here. Assign them elsewhere first.",
  );
  await act(async () => option.click());
  expect(save).not.toHaveBeenCalled();
});
it("shows save failures inside the panel and blocks duplicate submissions", async () => {
  let finish!: (value: boolean) => void;
  const save = vi.fn(
    () =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () =>
    root.render(
      <ClanSettingsEditor
        clan={clan}
        archived={false}
        busy={false}
        trigger={null}
        saveError="Another staff member changed this roster."
        onClose={() => true}
        onDirty={() => {}}
        onSave={save}
      />,
    ),
  );
  await type("Minimum weight", "152");
  await act(async () => {
    button("Save settings").click();
    button("Save settings").click();
  });
  expect(save).toHaveBeenCalledTimes(1);
  expect(document.querySelector("dialog")!.textContent).toContain(
    "Another staff member changed this roster.",
  );
  await act(async () => finish(false));
  expect(button("Save settings").disabled).toBe(false);
});
