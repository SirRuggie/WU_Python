// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import UsageLinks from "./UsageLinks";
import { api } from "../api";
vi.mock("../api", () => ({ api: vi.fn() }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  vi.mocked(api).mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("shows only returned usage, with new tabs preserving the current clan draft", async () => {
  vi.mocked(api).mockResolvedValue({
    links: [{ label: "Strikes tracking", href: "/clans/strikes" }],
  });
  await act(async () =>
    root.render(<UsageLinks tag="#P0LYQ" revision="one" />),
  );
  expect(host.querySelectorAll("a")).toHaveLength(1);
  expect(host.textContent).not.toContain("weights");
  expect(host.querySelector("a")?.target).toBe("_blank");
  expect(host.querySelector("a")?.getAttribute("aria-label")).toContain(
    "opens in a new tab",
  );
});
it("ignores an earlier clan's late response", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () =>
    root.render(<UsageLinks tag="#P0LYQ" revision="one" />),
  );
  vi.mocked(api).mockResolvedValue({
    links: [{ label: "New clan usage", href: "/clans/strikes" }],
  });
  await act(async () => root.render(<UsageLinks tag="#P2Y" revision="two" />));
  await act(async () =>
    finish({ links: [{ label: "Old clan usage", href: "/wrong" }] }),
  );
  expect(host.textContent).toContain("New clan usage");
  expect(host.textContent).not.toContain("Old clan usage");
});
