// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import DashboardLink from "./DashboardLink";

async function mount(node: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  return {
    host,
    cleanup: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}

function press(link: Element, init: MouseEventInit) {
  const event = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
    ...init,
  });
  link.dispatchEvent(event);
  return event;
}

it("navigates in-app on a plain primary click and keeps the real href", async () => {
  const go = vi.fn();
  const { host, cleanup } = await mount(
    <DashboardLink href="/clans" onNavigate={go}>
      Clans
    </DashboardLink>,
  );
  try {
    const link = host.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("/clans");
    const event = await act(async () => press(link, {}));
    expect(event.defaultPrevented).toBe(true);
    expect(go).toHaveBeenCalledOnce();
  } finally {
    await cleanup();
  }
});

it("leaves modified and non-primary clicks to the browser", async () => {
  const go = vi.fn();
  const { host, cleanup } = await mount(
    <DashboardLink href="/clans" onNavigate={go}>
      Clans
    </DashboardLink>,
  );
  try {
    const link = host.querySelector("a")!;
    for (const init of [
      { ctrlKey: true },
      { metaKey: true },
      { shiftKey: true },
      { altKey: true },
      { button: 1 },
    ]) {
      const event = await act(async () => press(link, init));
      expect(event.defaultPrevented).toBe(false);
    }
    expect(go).not.toHaveBeenCalled();
  } finally {
    await cleanup();
  }
});

it("does nothing while disabled", async () => {
  const go = vi.fn();
  const { host, cleanup } = await mount(
    <DashboardLink href="/clans" onNavigate={go} disabled>
      Clans
    </DashboardLink>,
  );
  try {
    const link = host.querySelector("a")!;
    expect(link.getAttribute("aria-disabled")).toBe("true");
    expect(link.hasAttribute("href")).toBe(false);
    const aux = await act(async () => press(link, { button: 1 }));
    expect(aux.defaultPrevented).toBe(true);
    expect(go).not.toHaveBeenCalled();
    const event = await act(async () => press(link, {}));
    expect(event.defaultPrevented).toBe(true);
    expect(go).not.toHaveBeenCalled();
  } finally {
    await cleanup();
  }
});
