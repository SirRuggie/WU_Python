// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it } from "vitest";
import DeclarationExtras from "./DeclarationExtras";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
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
const base = {
  tag: "#PYY",
  name: "Fixture",
  capacity: 15,
  status: "current" as const,
  checked_at: new Date().toISOString(),
  count: 0,
  extras: [],
};
it("distinguishes empty, failed and never-checked observations", async () => {
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={base}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("0 not on roster");
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{ ...base, status: "unavailable", count: null, extras: null }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("Couldn't check");
  expect(host.textContent).not.toContain("0 not on roster");
  expect(host.textContent).toContain("Last checked");
  await act(async () =>
    root.render(<DeclarationExtras loading={true} error="" now={Date.now()} />),
  );
  expect(host.textContent).toBe("Checking clan members…");
});
it("lists account identity and context without a send action or external HTML", async () => {
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{
          ...base,
          count: 1,
          extras: [
            {
              tag: "#QYY",
              name: "<img src=x> @everyone",
              town_hall: 16,
              context: "Assigned to Other clan",
              assigned_clan_tag: "#RYY",
            },
          ],
        }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("⚠ 1 not on roster");
  expect(host.textContent).toContain("TH 16");
  expect(host.textContent).toContain("Assigned to Other clan");
  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector("button")).toBeNull();
});
