// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { Session } from "./api";
import DashboardHome from "./DashboardHome";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));

it("offers one Try again and hides the duplicate header Refresh on failure", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockRejectedValue(new Error("offline"));
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardHome
          session={{ user: { id: "1" }, can_edit: false } as unknown as Session}
          seasonId=""
          seasons={[]}
          onNavigate={vi.fn()}
          onStart={vi.fn()}
        />,
      ),
    );
    const buttons = [...host.querySelectorAll("button")].filter(
      (item) => item.textContent === "Try again",
    );
    expect(buttons).toHaveLength(1);
    expect(host.querySelector('button[aria-label="Refresh"]')).toBeNull();
    expect(buttons[0].getAttribute("aria-label")).toBe("Try again: dashboard");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
