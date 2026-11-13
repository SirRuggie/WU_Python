// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { Session } from "./api";
import DashboardHome from "./DashboardHome";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));

it("names the Refresh button by its visible text and hides the glyph", async () => {
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
    const button = [...host.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("Refresh"),
    )!;
    expect(button).toBeTruthy();
    expect(button.hasAttribute("aria-label")).toBe(false);
    expect(button.querySelector('[aria-hidden="true"]')?.textContent).toBe("↻");
    expect(button.textContent?.replace("↻", "").trim()).toBe("Refresh");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
