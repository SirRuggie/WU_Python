// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act, useState } from "react";
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
  for (const label of ["Main CWL", "15v15"]) {
    await act(async () =>
      [...document.querySelectorAll<HTMLButtonElement>(".roster-menu-trigger")]
        .find((item) => item.textContent?.includes(label))!
        .click(),
    );
    const options = [...document.querySelectorAll('[role="menuitem"]')];
    expect(options.length).toBe(2);
    expect(options.map((item) => item.textContent).join(" ")).not.toContain(
      "Not set",
    );
    await act(async () =>
      [
        ...document.querySelectorAll<HTMLButtonElement>(
          '[aria-label="Close panel"]',
        ),
      ]
        .at(-1)!
        .click(),
    );
  }
  expect(document.querySelector("button [role=progressbar]")).toBeNull();
  expect(document.querySelector("button div")).toBeNull();
  for (const input of document.querySelectorAll("input")) {
    expect(
      document.getElementById(input.getAttribute("aria-describedby")!)
        ?.textContent,
    ).toContain("in thousands (k)");
  }
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
  let finish!: (reason: Error) => void;
  const save = vi.fn(
    () =>
      new Promise<boolean>((_resolve, reject) => {
        finish = reject;
      }),
  );
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
  await type("Minimum weight", "152");
  await act(async () => {
    button("Save settings").click();
    button("Save settings").click();
  });
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () =>
    finish(new Error("Another staff member changed this roster.")),
  );
  expect(document.querySelector("dialog")!.textContent).toContain(
    "Another staff member changed this roster.",
  );
  expect(button("Save settings").disabled).toBe(false);
});
it("zero shows an inline error and disables Save; blank is allowed; e and negatives are rejected", async () => {
  const save = vi.fn().mockResolvedValue(true);
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
  await type("Minimum weight", "0");
  expect(document.body.textContent).toContain(
    "Enter a weight above 0, or leave blank for no limit.",
  );
  expect(button("Save settings").disabled).toBe(true);
  await type("Minimum weight", "");
  await type("Maximum weight", "");
  expect(button("Save settings").disabled).toBe(false);
  expect(document.body.textContent).toContain("Range: Any weight");
  await type("Minimum weight", "1e3");
  await type("Maximum weight", "-1");
  expect([...document.querySelectorAll("input")].map((e) => e.value)).toEqual([
    "",
    "",
  ]);
  await act(async () => button("Save settings").click());
  expect(save).toHaveBeenCalledWith({
    pool: "main",
    capacity: 15,
    min_weight: null,
    max_weight: null,
  });
});
it("validates ranges live and shows changed-only impact with missing weights excluded", async () => {
  const accounts = [149000, 150000, 168000, 169000, 170000, null].map(
    (effective_weight, index) => ({
      tag: String(index),
      player_name: `Player ${index}`,
      assigned_clan_tag: clan.tag,
      effective_weight,
    }),
  ) as import("./roster").RosterAccount[];
  await act(async () =>
    root.render(
      <ClanSettingsEditor
        clan={clan}
        accounts={accounts}
        archived={false}
        busy={false}
        trigger={null}
        onClose={() => true}
        onDirty={() => {}}
        onSave={vi.fn()}
      />,
    ),
  );
  expect(document.querySelector(".clan-settings-impact")).toBeNull();
  await type("Maximum weight", "150");
  expect(button("Save settings").disabled).toBe(true);
  expect(document.body.textContent).toContain("Maximum weight must be greater");
  await type("Maximum weight", "169");
  expect(document.body.textContent).toContain(
    "1 more assigned player would be outside the range",
  );
  expect(button("Save settings").disabled).toBe(false);
  await type("Maximum weight", "168");
  expect(
    document.querySelector(".clan-settings-impact summary")?.textContent,
  ).toBe("2 more assigned players would be outside the range");
  await type("Minimum weight", "148");
  expect(
    document.querySelector(".clan-settings-impact summary")?.textContent,
  ).toBe(
    "2 more assigned players would be outside the range · 1 would move inside",
  );
  expect(document.querySelectorAll(".clan-settings-impact li")).toHaveLength(3);
  await type("Maximum weight", "170");
  expect(
    document.querySelector(".clan-settings-impact summary")?.textContent,
  ).toBe("1 would move inside");
  await type("Minimum weight", "150");
  expect(document.querySelector(".clan-settings-impact")).toBeNull();
  await act(async () => button("15v15").click());
  await act(async () =>
    [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')]
      .find((item) => item.textContent === "30v30")!
      .click(),
  );
  expect(document.querySelector(".clan-settings-impact")).toBeNull();
});

it("saving an empty clan in another pool offers View and switches to its highlighted row", async () => {
  function Harness() {
    const [pool, setPool] = useState<"main" | "lazy">("main");
    const [current, setClan] = useState({ ...clan, assigned_count: 0 });
    return (
      <ClanSettings
        clans={[current]}
        pool={pool}
        archived={false}
        busy={false}
        onPoolChange={setPool}
        onDirty={() => {}}
        onLeave={() => true}
        onSave={async (_, rules) => {
          setClan({ ...current, ...rules });
          return true;
        }}
      />
    );
  }
  await act(async () => root.render(<Harness />));
  await act(async () => button("Amber Knights").click());
  await act(async () => button("Main CWL").click());
  const lazy = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((e) => e.textContent === "Lazy CWL")!;
  await act(async () => lazy.click());
  await act(async () => button("Save settings").click());
  expect(document.body.textContent).toContain(
    "Amber Knights moved to Lazy CWL",
  );
  expect(document.querySelector(".clan-settings-row")).toBeNull();
  await act(async () => button("View").click());
  expect(
    document.querySelector(".clan-settings-row.is-selected")?.textContent,
  ).toContain("Amber Knights");
  const css = readFileSync("src/ClanSettings.css", "utf8");
  expect(css).toMatch(
    /\.clan-settings-row\.is-selected\s*\{\s*border-color: var\(--roster-gold\)/,
  );
  expect(document.querySelector(".clan-settings-moved")).toBeNull();
  await act(async () => button("Amber Knights").click());
  expect(document.querySelector(".clan-settings-row.is-selected")).toBeNull();
  expect(document.querySelector(".clan-settings-impact")).toBeNull();
});
it("blocks a previously chosen pool if assigned players arrive during editing", async () => {
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
      <ClanSettingsEditor {...props} clan={{ ...clan, assigned_count: 0 }} />,
    ),
  );
  await act(async () => button("Main CWL").click());
  const lazy = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((e) => e.textContent === "Lazy CWL")!;
  await act(async () => lazy.click());
  await act(async () =>
    root.render(<ClanSettingsEditor {...props} clan={clan} />),
  );
  expect(button("Save settings").disabled).toBe(true);
  expect(
    document.querySelector(".clan-settings-panel > .action-panel-content")
      ?.textContent,
  ).toContain("Can't move to Lazy CWL: 16 players are assigned here.");
  expect(props.onSave).not.toHaveBeenCalled();
});

it("puts the archived notice first in the list at muted 12px", async () => {
  await act(async () =>
    root.render(
      <ClanSettings
        clans={[clan]}
        pool="main"
        archived
        busy={false}
        onPoolChange={() => {}}
        onDirty={() => {}}
        onLeave={() => true}
        onSave={vi.fn()}
      />,
    ),
  );
  expect(
    document.querySelector(".clan-settings-list")?.firstElementChild
      ?.textContent,
  ).toBe("Archived season · settings are read-only.");
  const css = readFileSync("src/ClanSettings.css", "utf8");
  expect(css).toMatch(
    /\.clan-settings-panel \.clan-settings-archived\s*\{\s*font-size: 12px;\s*color: var\(--roster-text-muted\)/,
  );
});

it("hides the weight-unit description using always-imported roster CSS, without the Bonus chunk", async () => {
  await act(async () =>
    root.render(
      <ClanSettingsEditor
        clan={clan}
        archived={false}
        busy={false}
        trigger={null}
        onClose={() => true}
        onDirty={() => {}}
        onSave={vi.fn()}
      />,
    ),
  );
  const unit = document.querySelector(".clan-settings-panel .sr-only")!;
  expect(unit.textContent).toBe("Weights in thousands (k)");
  const css = readFileSync("src/rosterUi/primitives.css", "utf8");
  const rule = css.match(/\.roster-ui \.sr-only\s*\{([^}]+)\}/)?.[1];
  expect(rule).toBeDefined();
  for (const declaration of [
    "position: absolute",
    "width: 1px",
    "height: 1px",
    "margin: -1px",
    "overflow: hidden",
    "clip-path: inset(50%)",
    "white-space: nowrap",
  ])
    expect(rule).toContain(declaration);
  expect(readFileSync("src/rosterUi/primitives.tsx", "utf8")).toContain(
    'import "./primitives.css"',
  );
  expect(readFileSync("src/ClanSettings.tsx", "utf8")).toContain(
    'from "./rosterUi/primitives"',
  );
});
