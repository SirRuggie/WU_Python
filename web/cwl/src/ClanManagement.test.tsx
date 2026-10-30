// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ClanManagement from "./ClanManagement";
import { api } from "./api";
vi.mock("./api", () => ({ api: vi.fn(), apiUpload: vi.fn() }));
vi.mock("./clanManagement/ReminderOverview", () => ({ default: () => null }));
vi.mock("./ClanHistory", () => ({ default: () => null }));
const clan = {
  tag: "#AAA",
  revision: "clan-one",
  name: "Test clan",
  type: "CWL",
  logo: "",
  banner: "",
  leader_id: "",
  leader_role_id: "",
  role_id: "",
  chat_channel_id: "",
  announcement_id: "",
  rules_channel_id: "",
  leadership_channel_id: "",
  thread_id: "",
  profile: "",
  th_requirements: "",
  emoji: "",
};
const reminders = {
  settings: {
    enabled: false,
    channel_id: "",
    minutes: [60],
    war_started: false,
    audience: "remaining",
  },
  revision: "reminder-one",
  history: [],
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const onDirty = vi.fn();
const button = (text: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
async function click(text: string) {
  await act(async () => button(text).click());
}
async function open() {
  await act(async () => root.render(<ClanManagement onDirty={onDirty} />));
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".clan-directory button")!.click(),
  );
}
async function editBoth() {
  const name = host.querySelector<HTMLInputElement>('input[maxlength="120"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(name, "Changed clan");
    name.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((b) => b.textContent === "War reminders")!
      .click(),
  );
  await click("+ 12h");
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal(
    "confirm",
    vi.fn(() => {
      throw new Error("Native confirm forbidden");
    }),
  );
  vi.stubGlobal(
    "prompt",
    vi.fn(() => {
      throw new Error("Native prompt forbidden");
    }),
  );
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (url, method, body) => {
      if (url === "/manage/clan-choices")
        return { roles: [], channels: [] } as never;
      if (url === "/manage/clans")
        return {
          clans: [clan],
          types: ["CWL", "FWA"],
          town_halls: ["16"],
        } as never;
      if (url.endsWith("/war-reminders"))
        return (
          method === "PUT"
            ? {
                ...reminders,
                settings: (body as { settings: unknown }).settings,
                revision: "reminder-two",
              }
            : reminders
        ) as never;
      if (method === "PATCH")
        return {
          ...clan,
          ...(body as { values: object }).values,
          revision: "clan-two",
        } as never;
      throw new Error("Unexpected " + url);
    });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("defaults to Clans, exposes collapsible sections and one save for both revisions", async () => {
  await open();
  expect(button("Clans").getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelectorAll(".clan-section-toggle")).toHaveLength(5);
  await editBoth();
  expect(host.querySelector(".clan-actions")!.textContent).toContain(
    "2 unsaved changes",
  );
  expect(host.querySelectorAll(".clan-actions")).toHaveLength(1);
  await click("Save");
  expect(api).toHaveBeenCalledWith("/manage/clans/%23AAA", "PATCH", {
    revision: "clan-one",
    values: { name: "Changed clan" },
  });
  expect(api).toHaveBeenCalledWith(
    "/manage/clans/%23AAA/war-reminders",
    "PUT",
    {
      revision: "reminder-one",
      settings: { ...reminders.settings, minutes: [720, 60] },
    },
  );
  expect(host.querySelector(".clan-actions")!.textContent).toContain(
    "0 unsaved changes",
  );
  expect(window.confirm).not.toHaveBeenCalled();
  expect(window.prompt).not.toHaveBeenCalled();
});
it("keeps clan edits on conflict while saving reminder edits", async () => {
  await open();
  await editBoth();
  const implementation = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => {
    if (args[1] === "PATCH") throw new Error("Changed by someone else");
    return implementation(...args);
  });
  await click("Save");
  expect(host.textContent).toContain("Clan details: Changed by someone else");
  expect(
    host.querySelector<HTMLInputElement>('input[maxlength="120"]')!.value,
  ).toBe("Changed clan");
  expect(host.querySelector(".clan-actions")!.textContent).toContain(
    "1 unsaved changes",
  );
});
it("confirms leaving a dirty clan and names the clan in the removal dialog", async () => {
  await open();
  await editBoth();
  await click("‹ All clans");
  expect(document.querySelector("dialog")!.textContent).toContain(
    "Discard unsaved clan changes?",
  );
  await click("Cancel");
  expect(host.querySelector(".clan-editor")).not.toBeNull();
  await click("Remove clan");
  expect(document.querySelector("dialog")!.textContent).toContain(
    "Remove Test clan? You can restore it from History.",
  );
  expect(api).not.toHaveBeenCalledWith(
    expect.anything(),
    "DELETE",
    expect.anything(),
  );
});
it("keeps reminder edits on conflict after clan details save successfully", async () => {
  await open();
  await editBoth();
  const implementation = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => {
    if (args[1] === "PUT") throw new Error("Reminder revision conflict");
    return implementation(...args);
  });
  await click("Save");
  expect(host.textContent).toContain(
    "War reminders changed or could not be saved",
  );
  expect(
    host.querySelector<HTMLInputElement>('input[maxlength="120"]')!.value,
  ).toBe("Changed clan");
  expect(host.querySelector(".clan-actions")!.textContent).toContain(
    "1 unsaved changes",
  );
  expect(button("Save").disabled).toBe(false);
});
it("toggles section cards without discarding their edits", async () => {
  await open();
  await editBoth();
  const toggle = [
    ...host.querySelectorAll<HTMLButtonElement>(".clan-section-toggle"),
  ].find((b) => b.textContent?.startsWith("War reminders"))!;
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  await act(async () => toggle.click());
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelector("#clan-panel-4")!.hasAttribute("hidden")).toBe(
    true,
  );
  await act(async () => toggle.click());
  expect(host.querySelector(".clan-actions")!.textContent).toContain(
    "2 unsaved changes",
  );
});
