// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import AccessSettings from "./AccessSettings";

const ROLE_ID = "123456789012345678";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const data = {
  revision: 1,
  owners: [],
  groups: [
    {
      label: "CWL management",
      permissions: [{ id: "roster", label: "Edit rosters", description: "x" }],
    },
  ],
  history: [],
  grants: [
    { kind: "role", id: ROLE_ID, label: ROLE_ID, permissions: ["roster"] },
  ],
};
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes(text),
  )!;
const click = async (text: string) => {
  const target = button(text);
  expect(target).toBeTruthy();
  await act(async () => target.click());
};

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLElement.prototype.scrollIntoView = vi.fn();
  api.mockReset();
  api.mockImplementation(async (path: string) =>
    path === "/access/roles" ? { roles: [] } : data,
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("names an unresolved role Unknown role, never shows its ID, and removes with the danger button", async () => {
  await act(async () => root.render(<AccessSettings />));
  expect(host.textContent).toContain("Unknown role");
  await click("Unknown role");
  await click("Remove this access entry");
  expect(host.textContent).toContain("Remove access for Unknown role?");
  const confirm = button("Confirm removal");
  expect(confirm.className).toContain("is-danger");
  expect(host.textContent).not.toContain(ROLE_ID);
});
