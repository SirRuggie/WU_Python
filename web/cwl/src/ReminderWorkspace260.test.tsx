// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ReminderWorkspace from "./ReminderWorkspace";
import initial from "../tests/fixtures/signup-reminders-data.json";
import { api, ApiError } from "./api";
import type { CampaignState } from "./reminderCampaign";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let host: HTMLDivElement;
let root: Root;
let compact = false;
let value: CampaignState;
let failLookup = false;
let failure: number | null = null;
const dirty = vi.fn();
const button = (name: string, owner: ParentNode = host) =>
  [...owner.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      (node.getAttribute("aria-label") || node.textContent)?.trim() === name,
  )!;
const press = async (name: string, owner: ParentNode = host) => {
  const target = button(name, owner);
  expect(target, name).toBeTruthy();
  await act(async () => target.click());
};
const input = (label: string, owner: ParentNode = host) =>
  [...owner.querySelectorAll("label")]
    .find(
      (node) =>
        [...node.childNodes]
          .filter((child) => child.nodeType === Node.TEXT_NODE)
          .map((child) => child.textContent)
          .join("")
          .trim() === label,
    )
    ?.querySelector<HTMLInputElement>("input")!;
const change = async (
  target: HTMLInputElement | HTMLSelectElement,
  text: string,
) => {
  expect(target).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      target instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype,
      "value",
    )!.set!.call(target, text);
    target.dispatchEvent(
      new Event(target instanceof HTMLSelectElement ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
};
const row = (id: string) =>
  host.querySelector<HTMLButtonElement>(`[data-reminder-message="${id}"]`)!;
const writes = () =>
  vi.mocked(api).mock.calls.filter(([, method]) => method && method !== "GET");
async function render(archived = false) {
  await act(async () =>
    root.render(
      <ReminderWorkspace seasonId="42" archived={archived} onDirty={dirty} />,
    ),
  );
}
beforeEach(() => {
  compact = false;
  failLookup = false;
  failure = null;
  dirty.mockClear();
  value = {
    cycle: "2026-11",
    generation: "fixture:7",
    activated: true,
    worker_ready: true,
    schedule_synced: true,
    campaign: structuredClone(initial),
    schedule: [],
    history: [],
    signup_open: true,
  } as CampaignState;
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        matches: compact && query.includes("1099"),
        media: query,
        addEventListener() {},
        removeEventListener() {},
        onchange: null,
        addListener() {},
        removeListener() {},
        dispatchEvent() {
          return true;
        },
      }) as MediaQueryList,
  );
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path.includes("manage-reminders")) {
        if (failure) throw new ApiError("Fixture request failed", failure);
        return structuredClone(value) as never;
      }
      if (failLookup) throw new ApiError("Names offline", 500);
      return path.includes("roles")
        ? ({
            roles: [
              { id: "role-main", name: "Main members" },
              { id: "role-lazy", name: "Lazy members" },
            ],
          } as never)
        : ({
            channels: [
              { id: "channel-main", name: "Main announcements" },
              { id: "channel-lazy", name: "Lazy announcements" },
            ],
          } as never);
    });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("opens Messages with All and no clean save bar; remount resets local scope", async () => {
  await render();
  expect(
    host.querySelector('[role="tab"][aria-selected="true"]')?.textContent,
  ).toBe("Messages");
  expect(button("All messages").getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelectorAll(".reminder-message-row")).toHaveLength(6);
  expect(host.querySelector(".reminder-error-line")).toBeNull();
  expect(host.querySelector(".reminder-save")).toBeNull();
  expect(host.querySelectorAll(".roster-pool-label-extra")).toHaveLength(3);
  expect(
    [...host.querySelectorAll('[role="tab"]')].map((node) => node.textContent),
  ).toEqual(["Messages", "Schedule", "History"]);
  await press(
    "Lazy CWL",
    host.querySelector('[aria-label="Version to edit"]')!,
  );
  expect(host.querySelector(".reminder-editor h2")?.textContent).toContain(
    "Lazy CWL",
  );
  await press("Lazy CWL", host.querySelector('[aria-label="Message pool"]')!);
  await act(async () => root.unmount());
  root = createRoot(host);
  await render();
  expect(button("All messages").getAttribute("aria-pressed")).toBe("true");
});
it("chooses only Lazy's error, permits red Save, and keeps per-pool versus global toggles distinct", async () => {
  value.campaign!.messages.signup.variants.lazy.title = "";
  await render();
  expect(host.querySelector(".reminder-error-line")?.textContent).toBe(
    "1 message has an error",
  );
  await act(async () => row("signup").click());
  expect(host.querySelector(".reminder-editor h2")?.textContent).toContain(
    "Lazy CWL",
  );
  await change(input("Title"), "Changed lazy title");
  expect(button("Save changes").disabled).toBe(false);
  await act(async () => input("Send Lazy version").click());
  await press(
    "Main CWL",
    host.querySelector('[aria-label="Version to edit"]')!,
  );
  expect(input("Send Main version").checked).toBe(true);
  expect(input("Send this message (Main and Lazy)").checked).toBe(true);
  await act(async () => input("Send this message (Main and Lazy)").click());
  await press(
    "Lazy CWL",
    host.querySelector('[aria-label="Version to edit"]')!,
  );
  expect(input("Send this message (Main and Lazy)").checked).toBe(false);
  expect(input("Send Lazy version").checked).toBe(false);
  expect(writes()).toEqual([]);
});
it("filters errors and Off, Clear keeps the pool, and hidden draft edits remain dirty", async () => {
  value.campaign!.messages["reminder:3"].variants.lazy.title = "";
  value.campaign!.messages["reminder:4"].variants.lazy.enabled = false;
  await render();
  await act(async () => row("signup").click());
  await change(input("Title"), "Hidden changed title");
  await press("Lazy CWL", host.querySelector('[aria-label="Message pool"]')!);
  expect(host.querySelector('[aria-label="Version to edit"]')).toBeNull();
  await press("Filters");
  await act(async () => input("Has error", document).click());
  expect(host.querySelectorAll(".reminder-message-row")).toHaveLength(1);
  expect(row("reminder:3")).toBeTruthy();
  await act(async () => input("Off", document).click());
  expect(host.textContent).toContain("No messages match these filters.");
  await press("Clear", document.querySelector("dialog")!);
  expect(host.querySelectorAll(".reminder-message-row")).toHaveLength(6);
  expect(
    button(
      "Lazy CWL",
      host.querySelector('[aria-label="Message pool"]')!,
    ).getAttribute("aria-pressed"),
  ).toBe("true");
  await press("Done", document.querySelector("dialog")!);
  expect(host.textContent).toContain("Unsaved changes");
  expect(row("signup").textContent).toContain("Unsaved");
  expect(writes()).toEqual([]);
});
it("keeps draft through phone Back, Previous/Next and browser Back", async () => {
  compact = true;
  await render();
  await act(async () => row("signup").click());
  await change(input("Title"), "Phone kept title");
  await press("Previous");
  await press("Next");
  expect(input("Title").value).toBe("Phone kept title");
  await press("Back to messages");
  expect(host.querySelector(".reminder-editor")).toBeNull();
  await act(async () => row("signup").click());
  expect(input("Title").value).toBe("Phone kept title");
  await act(async () =>
    window.dispatchEvent(new PopStateEvent("popstate", { state: {} })),
  );
  expect(host.querySelector(".reminder-editor")).toBeNull();
  await act(async () => row("signup").click());
  expect(input("Title").value).toBe("Phone kept title");
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(writes()).toEqual([]);
});
it("protects an empty unchanged numeric buffer across tabs, beforeunload and Refresh until restored", async () => {
  value.campaign!.reminder_sequence = {
    enabled: true,
    mode: "evenly",
    count: 4,
    final_hours: 3,
    min_gap_hours: 3,
  };
  await render();
  await press("Schedule");
  await change(input("Total reminders"), "");
  expect(input("Total reminders").getAttribute("aria-invalid")).toBe("true");
  expect(host.textContent).toContain("Enter a number");
  expect(button("Save changes").disabled).toBe(true);
  expect(button("Preview schedule").disabled).toBe(true);
  expect(dirty).toHaveBeenLastCalledWith(true);
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  await press("History");
  expect(host.querySelector(".reminder-save")).toBeNull();
  expect(dirty).toHaveBeenLastCalledWith(true);
  await press("Schedule");
  expect(input("Total reminders").value).toBe("");
  await press("Messages");
  await press("Refresh reminders");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Discard unsaved reminder edits",
  );
  await press("Cancel", document.querySelector("dialog")!);
  await press("Schedule");
  await change(input("Total reminders"), "4");
  expect(host.querySelector(".reminder-save")).toBeNull();
  expect(dirty).toHaveBeenLastCalledWith(false);
  expect(writes()).toEqual([]);
});
it("shows no unknown name errors on lookup failure and never renders raw lookup IDs", async () => {
  failLookup = true;
  const variant = value.campaign!.messages.signup.variants.main;
  Object.assign(variant, {
    destination_channel_id: "123456789012345678",
    role_ids: ["987654321098765432"],
    title: "Fixture",
    body: "Fixture",
  });
  await render();
  expect(host.querySelector(".reminder-error-line")).toBeNull();
  expect(host.textContent).toContain("Names unavailable");
  expect(host.textContent).not.toMatch(/123456789012345678|987654321098765432/);
  expect(host.textContent).not.toContain("Role IDs");
  expect(button("Remove unknown role")).toBeTruthy();
});
it("hides Pause when Off and describes the dirty pause restriction", async () => {
  value.activated = false;
  await render();
  expect(button("Pause reminders")).toBeUndefined();
  expect(host.textContent).toContain("Save changes to turn reminders on.");
  await change(input("Title"), "A change");
  expect(writes()).toEqual([]);
});
it("dirty Refresh requires confirmation, cancellation keeps draft, failures retain it and authorization clears it", async () => {
  await render();
  await change(input("Title"), "Kept edit");
  expect(button("Pause reminders").disabled).toBe(true);
  expect(button("Pause reminders").getAttribute("aria-describedby")).toBe(
    "reminder-pause-reason",
  );
  expect(host.textContent).toContain("Save or discard edits first.");
  await press("Refresh reminders");
  await press("Cancel", document.querySelector("dialog")!);
  expect(input("Title").value).toBe("Kept edit");
  failure = 500;
  await press("Refresh reminders");
  await press("Confirm", document.querySelector("dialog")!);
  expect(input("Title").value).toBe("Kept edit");
  failure = 403;
  await press("Refresh reminders");
  await press("Confirm", document.querySelector("dialog")!);
  expect(host.querySelectorAll(".reminder-message-row")).toHaveLength(0);
  expect(writes()).toEqual([]);
});
it("archived fields and write controls stay disabled, absent signup is safe", async () => {
  delete value.campaign!.messages.signup;
  await render(true);
  await press("Schedule");
  expect(input("Opening announcement date and time")).toBeUndefined();
  expect(
    input("Advertised signup deadline date and time").disabled ||
      input("Advertised signup deadline date and time").closest("fieldset")!
        .disabled,
  ).toBe(true);
  expect(button("Pause reminders").disabled).toBe(true);
  expect(writes()).toEqual([]);
});

it("sort dialog changes natural row order without a request or lost edits", async () => {
  value.campaign!.messages.signup.label = "Reminder 10";
  value.campaign!.messages["reminder:2"].label = "Reminder 9";
  value.schedule = [
    {
      id: "next",
      message_id: "signup",
      variant: "main",
      run_at: "2090-01-01T00:00:00Z",
      status: "scheduled",
    },
  ];
  await render();
  expect(
    host
      .querySelector(".reminder-message-row")
      ?.getAttribute("data-reminder-message"),
  ).toBe("signup");
  await press("Sort: Send time");
  await act(async () => input("Name", document).click());
  await press("Done", document.querySelector("dialog")!);
  const labels = [...host.querySelectorAll(".reminder-message-row strong")].map(
    (node) => node.textContent,
  );
  expect(labels.indexOf("Reminder 9")).toBeLessThan(
    labels.indexOf("Reminder 10"),
  );
  expect(writes()).toEqual([]);
});

it("does not duplicate pending Preview and surfaces a generation conflict without PATCH or lost draft", async () => {
  await render();
  await change(input("Title"), "Concurrent fixture edit");
  let resolve!: (result: CampaignState) => void;
  const pending = new Promise<CampaignState>((done) => {
    resolve = done;
  });
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, body) =>
    path.endsWith("/preview")
      ? (pending as never)
      : original(path, method, body),
  );
  const save = button("Save changes");
  await act(async () => {
    save.click();
    save.click();
  });
  expect(writes()).toHaveLength(1);
  expect(button("Save changes").disabled).toBe(true);
  await act(async () => resolve(value));
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Save these reminder settings?",
  );
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (method === "PATCH") throw new ApiError("Generation conflict", 409);
    return original(path, method, body);
  });
  await press("Save", document.querySelector("dialog")!);
  expect(host.textContent).toContain("Generation conflict");
  expect(input("Title").value).toBe("Concurrent fixture edit");
  expect(
    vi.mocked(api).mock.calls.filter(([, method]) => method === "PATCH"),
  ).toHaveLength(1);
});

it.each(["channels", "roles"] as const)(
  "treats malformed successful %s lookups as unavailable and recovers on retry",
  async (field) => {
    const original = vi.mocked(api).getMockImplementation()!;
    let payload: unknown;
    let malformed = true;
    const path =
      field === "channels" ? "/announcement-channels" : "/announcement-roles";
    vi.mocked(api).mockImplementation(async (request, method, body) =>
      request === path && malformed
        ? ({ [field]: payload } as never)
        : original(request, method, body),
    );
    for (payload of [
      undefined,
      null,
      {},
      "invalid",
      [null],
      [{ id: "missing-name" }],
    ]) {
      await render();
      expect(host.querySelectorAll(".reminder-message-row")).toHaveLength(6);
      expect(host.textContent).toContain("Names unavailable");
      expect(host.querySelector(".reminder-error-line")).toBeNull();
      expect(host.querySelectorAll(".reminder-row-error")).toHaveLength(0);
      expect(host.querySelector(".reminder-editor")).toBeTruthy();
      await act(async () => root.unmount());
      root = createRoot(host);
    }
    await render();
    malformed = false;
    await press("Try again", host.querySelector(".reminder-editor")!);
    expect(host.querySelector(".reminder-error-line")).toBeNull();
    expect(host.textContent).not.toContain("Names unavailable");
    expect(writes()).toEqual([]);
  },
);
