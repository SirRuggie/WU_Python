// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import LoadError, { splitReference } from "./LoadError";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let host: HTMLDivElement | undefined;
let root: ReturnType<typeof createRoot> | undefined;
async function render(node: React.ReactNode) {
  const el = document.createElement("div");
  document.body.append(el);
  const r = createRoot(el);
  host = el;
  root = r;
  await act(async () => r.render(node));
  return el;
}
afterEach(async () => {
  const r = root;
  if (r) await act(async () => r.unmount());
  host?.remove();
  host = root = undefined;
});

it("splits the issue reference off the message", () => {
  expect(splitReference("Could not load. Reference: AB12")).toEqual({
    text: "Could not load.",
    reference: "AB12",
  });
  expect(splitReference("Could not load.")).toEqual({
    text: "Could not load.",
    reference: "",
  });
});

it("renders nothing without a message", async () => {
  const host = await render(<LoadError message="" onRetry={() => {}} />);
  expect(host.innerHTML).toBe("");
});

it("shows the message, note and Try again, and retries once per select", async () => {
  const retry = vi.fn();
  const host = await render(
    <LoadError
      message="Could not load clans."
      note="Showing the last update."
      onRetry={retry}
    />,
  );
  const alert = host.querySelector('[role="alert"]')!;
  expect(alert.textContent).toContain(
    "Could not load clans. Showing the last update.",
  );
  const button = alert.querySelector("button")!;
  expect(button.textContent).toBe("Try again");
  await act(async () => button.click());
  expect(retry).toHaveBeenCalledTimes(1);
});

it("disables Try again while busy", async () => {
  const host = await render(<LoadError message="x" onRetry={() => {}} busy />);
  const button = host.querySelector("button")!;
  expect(button.disabled).toBe(true);
  expect(button.textContent).toBe("Checking…");
});

it("copies the reference and reports a failed copy", async () => {
  const write = vi.fn().mockResolvedValueOnce(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: write },
    configurable: true,
  });
  const host = await render(<LoadError message="Failed. Reference: R-9" />);
  expect(host.querySelector("code")?.textContent).toBe("R-9");
  expect(host.textContent).not.toContain("Try again");
  const copy = host.querySelector("button")!;
  await act(async () => copy.click());
  expect(write).toHaveBeenCalledWith("R-9");
  expect(copy.textContent).toBe("Copied");
  write.mockRejectedValueOnce(new Error("denied"));
  await act(async () => copy.click());
  expect(host.textContent).toContain("Could not copy");
});

it("announces the copy result outside the alert", async () => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
  const host = await render(<LoadError message="Failed. Reference: R-9" />);
  const alert = host.querySelector('[role="alert"]')!;
  await act(async () => alert.querySelector("button")!.click());
  const status = host.querySelector('[role="status"]')!;
  expect(status.textContent).toBe("Reference copied");
  expect(alert.contains(status)).toBe(false);
  expect(
    alert.querySelector(".load-error-reference")!.getAttribute("aria-live"),
  ).toBe("off");
});
