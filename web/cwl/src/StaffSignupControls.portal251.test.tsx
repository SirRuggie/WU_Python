// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
const status = vi.hoisted(() => ({
  hiddenOpen: false,
  busy: false,
  error: "",
  notice: "",
  dialog: null,
  visibilityCheck: null,
  begin: vi.fn(),
}));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
vi.mock("./useSignupAction", () => ({ default: () => status }));
const api = vi.hoisted(() =>
  vi.fn(async (_path: string, _method?: string) => ({ options: [] })),
);
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import StaffSignupControls from "./StaffSignupControls";
it("keeps one Add controller, status and settings while its toolbar target appears and disappears", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const host = document.createElement("div"),
    toolbar = document.createElement("div"),
    root = createRoot(host);
  document.body.append(host, toolbar);
  const buttons = () =>
    [...document.querySelectorAll<HTMLButtonElement>("button")].filter(
      (button) => button.textContent?.trim() === "Add signup",
    );
  const render = (target: HTMLElement | null) =>
    act(async () =>
      root.render(
        <StaffSignupControls
          season={{
            id: 1,
            label: "November",
            status: "draft",
            signup_open: true,
          }}
          addTarget={target}
          primaryAction
          onChanged={async () => {}}
          onDirty={() => {}}
          onBusy={() => {}}
        />,
      ),
    );
  try {
    await render(null);
    expect(buttons()).toHaveLength(1);
    expect(host.contains(buttons()[0])).toBe(true);
    await render(toolbar);
    expect(buttons()).toHaveLength(1);
    expect(toolbar.contains(buttons()[0])).toBe(true);
    expect(buttons()[0].classList.contains("is-primary")).toBe(true);
    expect(host.textContent).toContain("Signups open");
    expect(
      host.querySelector('[aria-label="Signup window settings"]'),
    ).not.toBeNull();
    await act(async () => buttons()[0].click());
    expect(document.querySelector(".staff-signup-form")).not.toBeNull();
    await render(null);
    expect(buttons()).toHaveLength(1);
    expect(host.contains(buttons()[0])).toBe(true);
    expect(document.querySelector(".staff-signup-form")).not.toBeNull();
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[aria-label="Close panel"]')!
        .click(),
    );
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)));
    expect(document.querySelector(".staff-signup-form")).toBeNull();
    expect(document.activeElement).toBe(buttons()[0]);
    expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
      true,
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
    toolbar.remove();
    api.mockClear();
  }
});
