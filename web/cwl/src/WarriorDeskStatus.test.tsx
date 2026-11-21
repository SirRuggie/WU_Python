// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import WarriorDeskStatus from "./WarriorDeskStatus";
import type { ManagementDocument } from "./serverManagement";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const doc = (ready = false, live = false): ManagementDocument => ({
  id: "ticket_settings",
  label: "Warrior Desk",
  description: "Fixture",
  group: "Recruitment",
  revision: "fixture",
  fields: [],
  desk_readiness: {
    ready,
    live,
    missing: ready
      ? []
      : [
          {
            key: "account_thread_recruiter_role",
            label: "Add account staff role",
          },
          { key: "", label: "Thread-default or thread-only rollout" },
        ],
  },
});
it("names missing prerequisites and focuses the exact field", async () => {
  await act(async () =>
    root.render(
      <>
        <WarriorDeskStatus document={doc()} dirty={false} />
        <input id="manage-account-thread-recruiter-role" />
      </>,
    ),
  );
  expect(host.textContent).toContain("Complete setup");
  expect(host.textContent).toContain("Enable the ticket thread workflow");
  expect(host.textContent).toContain("Select Add account staff role");
  expect(host.textContent).not.toContain("Thread-default");
  await act(async () => host.querySelector<HTMLAnchorElement>("a")!.click());
  expect(document.activeElement?.id).toBe(
    "manage-account-thread-recruiter-role",
  );
});
it("keeps unsaved edits visible even when saved prerequisites are ready", async () => {
  await act(async () =>
    root.render(<WarriorDeskStatus document={doc(true)} dirty />),
  );
  expect(host.textContent).toContain("Save your changes before posting");
});
it("describes repair as the live-panel action", async () => {
  await act(async () =>
    root.render(<WarriorDeskStatus document={doc(true, true)} dirty={false} />),
  );
  expect(host.textContent).toContain("Panel is live");
  expect(host.textContent).toContain("Repair the existing panel");
});
