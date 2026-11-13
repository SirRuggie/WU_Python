// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import DashboardIssues from "./DashboardIssues";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));

it("copies an issue row reference and announces it outside the list", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const write = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: write },
    configurable: true,
  });
  api.mockResolvedValue({
    items: [
      {
        id: "abc123",
        at: 1,
        member: null,
        kind: "server_error",
        status: 500,
        action: "/api/cwl/roster",
        method: "GET",
      },
    ],
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<DashboardIssues />));
    const copy = host.querySelector<HTMLButtonElement>(
      ".issue-reference button",
    )!;
    expect(copy.textContent).toBe("Copy");
    await act(async () => copy.click());
    expect(write).toHaveBeenCalledWith("abc123");
    expect(copy.textContent).toBe("Copied");
    expect(
      host.querySelector('[role="status"].load-error-status')?.textContent,
    ).toBe("Reference copied");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
