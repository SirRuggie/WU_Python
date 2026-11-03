// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
const status = vi.hoisted(() => ({
  hiddenOpen: false,
  error: "",
  notice: "",
  visibilityCheck: null,
  busy: false,
  dialog: null,
  begin: vi.fn(),
}));
vi.mock("./useSignupAction", () => ({ default: () => status }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
import StaffSignupControls from "./StaffSignupControls";
it("reports hidden signups, errors and busy work so a closed summary cannot hide them", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div"),
    root = createRoot(host),
    attention = vi.fn();
  document.body.append(host);
  const render = () =>
    act(async () =>
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
          onAttentionChange={attention}
        />,
      ),
    );
  try {
    await render();
    expect(attention).toHaveBeenLastCalledWith(false);
    status.hiddenOpen = true;
    await render();
    expect(attention).toHaveBeenLastCalledWith(true);
    status.hiddenOpen = false;
    status.error = "Could not refresh";
    await render();
    expect(attention).toHaveBeenLastCalledWith(true);
    status.error = "";
    status.busy = true;
    await render();
    expect(attention).toHaveBeenLastCalledWith(true);
    status.busy = false;
    await render();
    expect(attention).toHaveBeenLastCalledWith(false);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    Object.assign(status, { hiddenOpen: false, error: "", busy: false });
  }
});
