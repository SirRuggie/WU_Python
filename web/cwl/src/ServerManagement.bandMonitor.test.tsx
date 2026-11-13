// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
import ServerManagement from "./ServerManagement";

const section = {
  id: "band_monitor",
  // The backend's own label; the page heading uses the area title.
  label: "BAND monitor",
  description: "Band monitor connection",
  group: "Connections",
  endpoint: "/manage/band_monitor",
};

it("opens the single Band monitor section directly, with no back link to a one-item list", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  transport.mockImplementation(async (path: string) =>
    path === "/manage"
      ? { sections: [section] }
      : {
          ...section,
          revision: "1",
          fields: [
            { key: "status", label: "Status", type: "text", value: "OK" },
          ],
          preview: [],
        },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(<ServerManagement area="connections-settings" />),
    );
    for (let i = 0; i < 3; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    const paths = transport.mock.calls.map(([path]) => path);
    expect(paths.filter((path) => path === "/manage")).toHaveLength(1);
    expect(paths.some((path) => String(path).includes("band_monitor"))).toBe(
      true,
    );
    expect(
      transport.mock.calls.every(([, method]) => !method || method === "GET"),
    ).toBe(true);
    expect(host.querySelector("h1")?.textContent).toBe("Band monitor");
    expect(host.textContent).not.toContain("← Band monitor");
    expect(host.textContent).toContain("Refresh");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
