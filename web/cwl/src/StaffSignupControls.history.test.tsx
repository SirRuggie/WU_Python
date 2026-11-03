// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
vi.mock("./useSignupAction", () => ({
  default: () => ({
    hiddenOpen: false,
    busy: false,
    error: "",
    notice: "",
    dialog: null,
    visibilityCheck: null,
    begin: () => {},
  }),
}));
import StaffSignupControls from "./StaffSignupControls";
it("Back on a clean actual signup panel closes synchronously without restoring its history marker", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  history.replaceState({ wuDashboardIndex: 9 }, "", "/cwl/roster?season=1");
  const before = history.state;
  const host = document.createElement("div"),
    root = createRoot(host);
  document.body.append(host);
  const push = vi.spyOn(history, "pushState");
  try {
    await act(async () =>
      root.render(
        <StaffSignupControls
          season={{
            id: 1,
            label: "November",
            status: "draft",
            signup_open: true,
          }}
          onChanged={async () => {}}
          onDirty={() => {}}
          onBusy={() => {}}
        />,
      ),
    );
    const open = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (b) => b.textContent?.trim() === "Add signup",
    )!;
    await act(async () => open.click());
    expect(push).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".staff-signup-form")).not.toBeNull();
    history.replaceState(before, "", "/cwl/roster?season=1");
    await act(async () =>
      window.dispatchEvent(new PopStateEvent("popstate", { state: before })),
    );
    expect(document.querySelector(".staff-signup-form")).toBeNull();
    expect(push).toHaveBeenCalledTimes(1);
    expect(history.state).toEqual(before);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    push.mockRestore();
  }
});
