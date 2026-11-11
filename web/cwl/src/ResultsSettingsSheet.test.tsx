// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { pickerByLabel, pickOption } from "./searchPickerTestUtils";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import ResultsSettingsSheet from "./ResultsSettingsSheet";

const sync = {
  cycle: "2026-11",
  enabled: false,
  cycle_source: "settings",
  status: "waiting",
  warning: null,
  last_checked_at: null,
  last_success_at: null,
  updated_at: "2026-11-01T00:00:00Z",
};
const participation = { accounts: [], publication_version: 1, sync };
const raffle = {
  season_status: "draft",
  revision: 7,
  lazy_settings: { representative_role_id: "769130325460254740" },
};
const roles = {
  roles: [
    { id: "111111111111111111", name: "Rep" },
    { id: "769130325460254740", name: "FWA Rep" },
  ],
};
let host: HTMLDivElement;
let root: Root;
const onClose = vi.fn();
const onSaved = vi.fn();
const onDirty = vi.fn();
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent?.trim() === name,
  )!;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const type = async (input: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
async function open(
  props: Partial<Parameters<typeof ResultsSettingsSheet>[0]> = {},
) {
  await act(async () =>
    root.render(
      <ResultsSettingsSheet
        seasonId="1"
        canCapture
        canOdds
        archived={false}
        trigger={null}
        onDirty={onDirty}
        onClose={onClose}
        onSaved={onSaved}
        {...props}
      />,
    ),
  );
  await settle();
}
const month = () =>
  document.querySelector<HTMLInputElement>('input[type="month"]')!;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  onClose.mockReset();
  onSaved.mockReset();
  onDirty.mockReset();
  api
    .mockReset()
    .mockImplementation(async (route: string) =>
      route === "/announcement-roles"
        ? roles
        : route.endsWith("/bonus-raffle/lazy-settings")
          ? { ...raffle, revision: 8 }
          : route.endsWith("/participation/sync-settings")
            ? { sync: { ...sync, cycle: "2026-12", enabled: true } }
            : route.endsWith("/bonus-raffle")
              ? raffle
              : participation,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("Settings sheet", () => {
  it("holds CWL capture and Lazy draw odds, and no disclosure", async () => {
    await open();
    const sections = [
      ...document.querySelectorAll(".results-settings-section h3"),
    ].map((node) => node.textContent);
    expect(sections).toEqual(["CWL capture", "Lazy draw odds"]);
    expect(document.querySelector("dialog.results-settings")).not.toBeNull();
    expect(document.querySelector("details")).toBeNull();
    expect(month().value).toBe("2026-11");
    expect(writes()).toHaveLength(0);
  });
  it("shows only the section a user can use", async () => {
    await open({ canOdds: false });
    expect(document.querySelector('[aria-label="Lazy draw odds"]')).toBeNull();
    expect(
      api.mock.calls.some((call) => String(call[0]).includes("bonus-raffle")),
    ).toBe(false);
    await act(async () => root.render(<></>));
    await open({ canCapture: false });
    expect(document.querySelector('[aria-label="CWL capture"]')).toBeNull();
    expect(
      document.querySelector('[aria-label="Lazy draw odds"]'),
    ).not.toBeNull();
    expect(
      api.mock.calls.filter((call) =>
        String(call[0]).endsWith("/participation"),
      ),
    ).toHaveLength(1);
  });
  it("saves capture settings with the revision it loaded", async () => {
    await open();
    expect(document.querySelector(".results-settings-actions")).toBeNull();
    await type(month(), "2026-12");
    await act(async () =>
      document
        .querySelector<HTMLInputElement>('input[name="capture-enabled"]')!
        .click(),
    );
    expect(onDirty).toHaveBeenLastCalledWith(true);
    await act(async () => button("Save capture settings").click());
    expect(writes()).toEqual([
      [
        "/seasons/1/participation/sync-settings",
        "POST",
        {
          cycle: "2026-12",
          enabled: true,
          expected_updated_at: "2026-11-01T00:00:00Z",
        },
      ],
    ]);
    expect(onSaved).toHaveBeenCalledExactlyOnceWith({
      kind: "capture",
      cycleChanged: true,
      enabled: true,
    });
    expect(onDirty).toHaveBeenLastCalledWith(false);
  });
  it("saves the representative role with the draw revision it loaded", async () => {
    await open();
    expect(button("Save role").disabled).toBe(true);
    await pickOption(
      pickerByLabel(document.body, "Representative role"),
      "Rep",
    );
    expect(button("Save role").disabled).toBe(false);
    await act(async () => button("Save role").click());
    expect(writes()).toEqual([
      [
        "/seasons/1/bonus-raffle/lazy-settings",
        "PATCH",
        { representative_role_id: "111111111111111111", revision: 7 },
      ],
    ]);
    expect(onSaved).toHaveBeenCalledExactlyOnceWith({ kind: "odds" });
    expect(button("Save role").disabled).toBe(true);
  });
  it("blocks a second save while one is running", async () => {
    await open();
    await type(month(), "2026-12");
    let release!: (value: object) => void;
    api.mockImplementation(
      (route: string) =>
        new Promise((resolve) => {
          if (route.endsWith("/sync-settings")) release = resolve;
        }),
    );
    await act(async () => {
      button("Save capture settings").click();
      button("Save capture settings").click();
    });
    expect(writes()).toHaveLength(1);
    await act(async () => release({ sync }));
  });
  it("shows a revision conflict, reloads and writes nothing more", async () => {
    await open();
    await type(month(), "2026-12");
    api.mockImplementation(async (route: string, method?: string) => {
      if (method === "POST")
        throw new ApiError("Settings changed elsewhere. Refresh.", 409);
      return route === "/announcement-roles" ? roles : participation;
    });
    await act(async () => button("Save capture settings").click());
    await settle();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "Settings changed elsewhere",
    );
    expect(writes()).toHaveLength(1);
    expect(onSaved).not.toHaveBeenCalled();
  });
  it("asks before closing with unsaved edits and closes at once without", async () => {
    await open();
    await act(async () => button("Close").click());
    expect(onClose).toHaveBeenCalledTimes(1);
    onClose.mockReset();
    await type(month(), "2026-12");
    await act(async () => button("Close").click());
    expect(onClose).not.toHaveBeenCalled();
    const dialog = document.querySelector(".confirm-dialog")!;
    expect(dialog.textContent).toContain("Discard unsaved settings?");
    await act(async () => button("Cancel", dialog).click());
    expect(onClose).not.toHaveBeenCalled();
    expect(month().value).toBe("2026-12");
    await act(async () => button("Close").click());
    await act(async () =>
      button(
        "Discard settings",
        document.querySelector(".confirm-dialog")!,
      ).click(),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(writes()).toHaveLength(0);
  });
  it("Escape closes through the same guard", async () => {
    await open();
    await type(month(), "2026-12");
    const panel = document.querySelector("dialog.results-settings")!;
    await act(async () => {
      panel.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  });
  it("confirms a CWL month change that discards result edits, once", async () => {
    await open({ dirtyResults: 2 });
    await type(month(), "2026-12");
    await act(async () => {
      button("Save capture settings").click();
      button("Save capture settings").click();
    });
    expect(writes()).toHaveLength(0);
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "unsaved result edits for 2 accounts",
    );
    await act(async () => {
      const confirm = button(
        "Change CWL month",
        document.querySelector(".confirm-dialog")!,
      );
      confirm.click();
      confirm.click();
    });
    expect(writes()).toHaveLength(1);
  });
  it("is read only for an archived season", async () => {
    await open({ archived: true });
    expect(month().disabled).toBe(true);
    expect(button("Save role").disabled).toBe(true);
    expect(document.body.textContent).toContain("Read only");
  });
});
