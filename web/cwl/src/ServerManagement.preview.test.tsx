import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ManagementDocument } from "./serverManagement";
const hooks = vi.hoisted(() => ({
  index: 0,
  values: [] as unknown[],
  setters: [] as ReturnType<typeof vi.fn>[],
  effects: [] as (() => void | (() => void))[],
}));
const transport = vi.hoisted(() => vi.fn());
const viewport = vi.hoisted(() => ({ compact: false }));
vi.mock("./useCompactPreview", () => ({ default: () => viewport.compact }));
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useState: (initial: unknown) => {
      const index = hooks.index++;
      const value =
        index < hooks.values.length
          ? hooks.values[index]
          : typeof initial === "function"
            ? (initial as () => unknown)()
            : initial;
      const setter = vi.fn();
      hooks.setters[index] = setter;
      return [value, setter];
    },
    useEffect: (effect: () => void | (() => void)) => {
      hooks.effects.push(effect);
    },
  };
});
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: transport,
}));
import ServerManagement from "./ServerManagement";
const document: ManagementDocument = {
  id: "recruit",
  label: "Recruitment",
  description: "Message",
  group: "Messages",
  endpoint: "/manage/content/recruit",
  revision: "reviewed",
  preview_supported: true,
  fields: [
    { key: "message", label: "Message", type: "textarea", value: "Saved text" },
  ],
  preview: [{ type: "text", text: "Saved text" }],
};
function renderDraft(pane: "edit" | "preview" = "edit") {
  hooks.values = [
    [],
    "",
    [],
    document,
    document,
    { message: "My unsaved text" },
    false,
    "",
    "",
    document.preview,
    false,
    0,
    "",
    null,
    "",
    pane,
  ];
  const html = renderToStaticMarkup(
    <ServerManagement area="applications-settings" />,
  );
  return { effect: hooks.effects[3], html };
}
beforeEach(() => {
  vi.useFakeTimers();
  viewport.compact = false;
  hooks.index = 0;
  hooks.values = [];
  hooks.effects = [];
  hooks.setters = [];
  transport.mockReset();
  vi.stubGlobal("window", { setTimeout, clearTimeout });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("draft preview debounces, sends only edits, and never replaces the saved draft", async () => {
  transport.mockResolvedValue({
    preview: [{ type: "text", text: "Rendered draft" }],
  });
  const { effect } = renderDraft();
  const cleanup = effect();
  await vi.advanceTimersByTimeAsync(699);
  expect(transport).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(transport).toHaveBeenCalledWith(
    "/manage/content/recruit/preview",
    "POST",
    { revision: "reviewed", values: { message: "My unsaved text" } },
  );
  expect(hooks.setters[9]).toHaveBeenCalledWith([
    { type: "text", text: "Rendered draft" },
  ]);
  expect(hooks.setters[5]).not.toHaveBeenCalled();
  expect(hooks.setters[4]).not.toHaveBeenCalled();
  if (cleanup) cleanup();
});
it("a late preview response cannot replace the next draft preview", async () => {
  let resolve!: (value: unknown) => void;
  transport.mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const cleanup = renderDraft().effect();
  await vi.advanceTimersByTimeAsync(700);
  if (cleanup) cleanup();
  resolve({ preview: [{ type: "text", text: "Outdated text" }] });
  await Promise.resolve();
  await Promise.resolve();
  expect(hooks.setters[9]).not.toHaveBeenCalled();
  expect(hooks.setters[5]).not.toHaveBeenCalled();
});
it("preview errors preserve draft text and the previous valid preview", async () => {
  transport.mockRejectedValue(new Error("Image cannot be loaded"));
  const cleanup = renderDraft().effect();
  await vi.advanceTimersByTimeAsync(700);
  expect(hooks.setters[14]).toHaveBeenCalledWith(
    "Showing the last valid preview. Image cannot be loaded",
  );
  expect(hooks.setters[9]).not.toHaveBeenCalled();
  expect(hooks.setters[5]).not.toHaveBeenCalled();
  if (cleanup) cleanup();
});
it("leaving before debounce prevents an obsolete preview request entirely", async () => {
  const cleanup = renderDraft().effect();
  if (cleanup) cleanup();
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport).not.toHaveBeenCalled();
});
it("saved preview is available before any edits", () => {
  hooks.values = [
    [],
    "",
    [],
    document,
    document,
    { message: "Saved text" },
    false,
    "",
    "",
    null,
    false,
    0,
    "",
    null,
    "",
    "edit",
  ];
  renderToStaticMarkup(<ServerManagement area="applications-settings" />);
  hooks.effects[3]();
  expect(hooks.setters[9]).toHaveBeenCalledWith(document.preview);
  expect(transport).not.toHaveBeenCalled();
});
it("reset tools are inside a closed More options disclosure", () => {
  const withActions = {
    ...document,
    actions: [{ id: "reset", label: "Reset to default", advanced: true }],
  };
  hooks.values = [
    [],
    "",
    [],
    withActions,
    withActions,
    { message: "Saved text" },
    false,
    "",
    "",
    document.preview,
    false,
    0,
    "",
    null,
    "",
    "edit",
  ];
  const html = renderToStaticMarkup(
    <ServerManagement area="applications-settings" />,
  );
  expect(html).toMatch(
    /<details class="manage-more-options"><summary>More options<\/summary>/,
  );
  expect(html).toContain("Reset to default");
});

it("mobile edit pane does not mount or request the preview", async () => {
  viewport.compact = true;
  const { effect, html } = renderDraft("edit");
  expect(html).not.toContain("Loading message preview");
  const cleanup = effect();
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport).not.toHaveBeenCalled();
  if (cleanup) cleanup();
});
it("mobile preview pane requests a draft preview and ignores it after hiding", async () => {
  viewport.compact = true;
  let resolve!: (value: unknown) => void;
  transport.mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const { effect, html } = renderDraft("preview");
  expect(html).toContain('class="discord-preview"');
  const cleanup = effect();
  await vi.advanceTimersByTimeAsync(700);
  expect(transport).toHaveBeenCalledOnce();
  if (cleanup) cleanup();
  resolve({ preview: [{ type: "text", text: "Stale" }] });
  await Promise.resolve();
  await Promise.resolve();
  expect(hooks.setters[9]).not.toHaveBeenCalled();
});

it("FWA edit pane does not request or mount previews on desktop", async () => {
  hooks.values = [
    [],
    "",
    [],
    document,
    document,
    { message: "My unsaved text" },
    false,
    "",
    "",
    document.preview,
    false,
    0,
    "",
    null,
    "",
    "edit",
  ];
  const html = renderToStaticMarkup(<ServerManagement area="fwa-settings" />);
  const cleanup = hooks.effects[3]();
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport).not.toHaveBeenCalled();
  expect(html).not.toContain('class="discord-preview"');
  expect(html).toContain("Preview message");
  if (cleanup) cleanup();
});
it("integration status shows every value as readable status rather than disabled inputs", () => {
  const status = {
    ...document,
    id: "band_monitor",
    readonly: true,
    preview_supported: false,
    fields: Array.from({ length: 8 }, (_, i) => ({
      key: `field${i}`,
      label: `Status ${i}`,
      type: "text",
      value: `Value ${i}`,
    })),
  };
  hooks.values = [
    [],
    "",
    [],
    status,
    status,
    {},
    false,
    "",
    "",
    null,
    false,
    0,
    "",
    null,
    "",
    "edit",
  ];
  const html = renderToStaticMarkup(
    <ServerManagement area="connections-settings" />,
  );
  expect(html).toContain('aria-label="Current status"');
  expect(html).toContain("Value 7");
  expect(html).not.toContain("Message or setting to edit");
  expect(html).not.toContain("Save changes");
});
it("shows a status notice once", () => {
  renderDraft();
  hooks.index = 0;
  hooks.effects = [];
  hooks.values[8] = "Queued. Waiting for the bot.";
  const html = renderToStaticMarkup(
    <ServerManagement area="applications-settings" />,
  );
  expect(html.split('class="manage-status" role="status"').length - 1).toBe(1);
  expect(html).toContain("Queued. Waiting for the bot.");
  expect(html).not.toContain('class="manage-notice"');
});

it("only preview-supported editors expose linked tab panels", () => {
  const { html: supported } = renderDraft();
  expect(supported).toContain('role="tablist"');
  for (const pane of ["edit", "preview"]) {
    expect(supported).toContain(
      `aria-controls="management-editor-panel-${pane}"`,
    );
    expect(supported).toContain(`id="management-editor-panel-${pane}"`);
    expect(supported).toContain(
      `aria-labelledby="management-editor-tab-${pane}"`,
    );
  }
  hooks.values[3] = { ...document, preview_supported: false };
  hooks.values[4] = hooks.values[3];
  hooks.index = 0;
  const unsupported = renderToStaticMarkup(
    <ServerManagement area="applications-settings" />,
  );
  expect(unsupported).not.toContain('role="tabpanel"');
  expect(unsupported).not.toContain("management-editor-panel-");
  expect(unsupported).not.toContain("management-editor-tab-");
});

it("preview stays an amber notice while hints and dirty-post warnings keep separate roles", () => {
  renderDraft();
  hooks.index = 0;
  hooks.effects = [];
  hooks.values[4] = {
    ...document,
    hint: "An advisory hint.",
    warning: "A real warning.",
  };
  hooks.values[8] = "Preview only. Nothing has been sent.";
  hooks.values[19] = true;
  const html = renderToStaticMarkup(
    <ServerManagement area="applications-settings" />,
  );
  expect(html).toContain('class="manage-hint"');
  expect(html).toContain("An advisory hint.");
  expect(html).toContain("A real warning.");
  expect(html).toContain(
    "Save or cancel the posting channel change before saving the",
  );
  expect(html).toContain("Preview only. Nothing has been sent.");
  expect(html).not.toContain('class="manage-status"');
  expect(html).not.toContain('class="manage-result"');
});

function renderCleanMissingPreview(
  pane: "edit" | "preview" = "edit",
  cached?: [],
) {
  const faq = { ...document, id: "gauntlet--wu-faq", preview: cached };
  hooks.values = [
    [],
    "",
    [],
    faq,
    faq,
    { message: "Saved text" },
    false,
    "",
    "",
    null,
    false,
    0,
    "",
    null,
    "",
    pane,
  ];
  const html = renderToStaticMarkup(
    <ServerManagement area="applications-settings" />,
  );
  return { html, effect: hooks.effects[3] };
}
it("clean FAQ loads one preview on desktop when GET deferred its registry read", async () => {
  transport.mockResolvedValue({
    preview: [{ type: "text", text: "All three clan lists" }],
  });
  const cleanup = renderCleanMissingPreview().effect();
  await vi.advanceTimersByTimeAsync(700);
  expect(transport).toHaveBeenCalledExactlyOnceWith(
    "/manage/content/recruit/preview",
    "POST",
    { revision: "reviewed", values: {} },
  );
  expect(hooks.setters[9]).toHaveBeenCalledWith([
    { type: "text", text: "All three clan lists" },
  ]);
  if (cleanup) cleanup();
});
it("clean FAQ does not load hidden mobile preview but loads after switching to Preview", async () => {
  viewport.compact = true;
  const hidden = renderCleanMissingPreview().effect();
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport).not.toHaveBeenCalled();
  if (hidden) hidden();
  hooks.index = 0;
  hooks.effects = [];
  transport.mockResolvedValue({ preview: [] });
  const shown = renderCleanMissingPreview("preview").effect();
  await vi.advanceTimersByTimeAsync(700);
  expect(transport).toHaveBeenCalledOnce();
  if (shown) shown();
});
it("an intentionally cached empty preview is already loaded", async () => {
  const cleanup = renderCleanMissingPreview("edit", []).effect();
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport).not.toHaveBeenCalled();
  expect(hooks.setters[9]).toHaveBeenCalledWith([]);
  if (cleanup) cleanup();
});
it("missing-preview registry failure is visible without claiming a last valid render", async () => {
  transport.mockRejectedValue(new Error("The clan registry is unavailable"));
  const cleanup = renderCleanMissingPreview().effect();
  await vi.advanceTimersByTimeAsync(700);
  expect(hooks.setters[14]).toHaveBeenCalledWith(
    "Preview unavailable. The clan registry is unavailable",
  );
  expect(hooks.setters[9]).not.toHaveBeenCalled();
  if (cleanup) cleanup();
});
it("a stale missing-preview failure cannot overwrite a newer success", async () => {
  let reject!: (error: Error) => void;
  transport.mockReturnValueOnce(
    new Promise((_, fail) => {
      reject = fail;
    }),
  );
  const old = renderCleanMissingPreview().effect();
  await vi.advanceTimersByTimeAsync(700);
  if (old) old();
  hooks.index = 0;
  hooks.effects = [];
  hooks.setters = [];
  transport.mockResolvedValueOnce({
    preview: [{ type: "text", text: "Fresh" }],
  });
  const current = renderCleanMissingPreview().effect();
  await vi.advanceTimersByTimeAsync(700);
  reject(new Error("Stale registry error"));
  await Promise.resolve();
  await Promise.resolve();
  expect(hooks.setters[9]).toHaveBeenCalledWith([
    { type: "text", text: "Fresh" },
  ]);
  expect(hooks.setters[14]).not.toHaveBeenCalledWith(
    expect.stringContaining("Stale registry error"),
  );
  if (current) current();
});
