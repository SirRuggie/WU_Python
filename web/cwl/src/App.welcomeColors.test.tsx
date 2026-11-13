// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import App from "./App";

const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));

function opaqueRgba(value: string): [number, number, number, number] {
  const hex = value.match(/^#([a-f0-9]{3}|[a-f0-9]{6})$/i);
  if (hex) {
    const digits =
      hex[1].length === 3
        ? [...hex[1]].map((digit) => digit + digit).join("")
        : hex[1];
    return [0, 2, 4]
      .map((start) => parseInt(digits.slice(start, start + 2), 16))
      .concat(1) as [number, number, number, number];
  }
  const rgb = value.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/);
  if (!rgb || rgb.slice(1).some((channel) => Number(channel) > 255)) {
    throw Error("Unsupported opaque CSS color: " + value);
  }
  return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3]), 1];
}

it("keeps the actual signed-out welcome CTA gold", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/home");
  const { ApiError } = await import("./api");
  state.api.mockImplementation(async (path: string) => {
    if (path === "/auth/me") throw new ApiError("Signed out", 401);
    if (path === "/config") return { dev_fixture: false };
    throw Error("Unexpected signed-out request " + path);
  });
  // Welcome is an App dependency; main imports the global sheets after App.
  const style = document.createElement("style");
  style.textContent = [
    "src/tokens.css",
    "src/Welcome.css",
    "src/style.css",
    "src/workflowControls.css",
    "src/accessibility.css",
  ]
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  document.head.append(style);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<App />));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    const cta = host.querySelector<HTMLAnchorElement>(
      ".welcome-screen .primary",
    );
    expect(cta?.textContent).toBe("Continue with Discord");
    expect(cta?.getAttribute("href")).toContain("/api/cwl/auth/discord?");
    const computed = getComputedStyle(cta!);
    expect(opaqueRgba(computed.backgroundColor)).toEqual([242, 182, 42, 1]);
    expect(opaqueRgba(computed.borderTopColor)).toEqual([242, 182, 42, 1]);
    expect(opaqueRgba(computed.color)).toEqual([36, 27, 8, 1]);
    expect(computed.borderRadius).toBe("999px");
  } finally {
    await act(async () => root.unmount());
    host.remove();
    style.remove();
    state.api.mockReset();
    localStorage.clear();
    sessionStorage.clear();
  }
});

it("separately preserves the base primary gold declarations, not the welcome CTA", () => {
  const css = readFileSync("src/style.css", "utf8");
  const base = css.match(/(?:^|\n)\.primary\s*\{([^}]+)\}/)?.[1];
  const hover = css.match(/(?:^|\n)\s*\.primary:hover\s*\{([^}]+)\}/)?.[1];
  expect(base).toBeTruthy();
  expect(base).toMatch(/background:\s*var\(--wu-accent\)\s*;/i);
  expect(base).toMatch(/border-color:\s*var\(--wu-accent\)\s*;/i);
  expect(base).toMatch(/color:\s*var\(--wu-accent-ink\)\s*;/i);
  const tokens = readFileSync("src/tokens.css", "utf8");
  expect(tokens).toMatch(/--wu-accent-ink:\s*#241b08\s*;/i);
  expect(hover).toMatch(/background:\s*var\(--wu-accent-hover\)\s*;/i);
});
