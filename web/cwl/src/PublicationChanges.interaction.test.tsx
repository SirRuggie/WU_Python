// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import PublicationChanges from "./PublicationChanges";
import type { PublicationDraft } from "./publication";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
it("loads comparison only when mounted, rejects stale versions and ignores closed requests", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const ready = vi.fn();
  const draft = {
    published: { version: 2 },
    draft_changed: true,
    preview: { accounts: [], clans: [] },
  } as unknown as PublicationDraft;
  let resolve!: (value: unknown) => void;
  api.mockImplementation(() => new Promise((r) => (resolve = r)));
  expect(api).not.toHaveBeenCalled();
  await act(async () =>
    root.render(
      <PublicationChanges seasonId="1" draft={draft} onReady={ready} />,
    ),
  );
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => root.render(null));
  await act(async () =>
    resolve({ summary: { published_version: 2 }, rows: [] }),
  );
  expect(ready).not.toHaveBeenCalledWith(true);
  await act(async () =>
    root.render(
      <PublicationChanges seasonId="1" draft={draft} onReady={ready} />,
    ),
  );
  await act(async () =>
    resolve({ summary: { published_version: 3 }, rows: [] }),
  );
  expect(host.textContent).toContain("Published version changed");
  expect(ready).not.toHaveBeenCalledWith(true);
  act(() => root.unmount());
  host.remove();
  api.mockReset();
});
