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

it("keeps the actual signed-out welcome CTA's winning brand colors", async () => {
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
    expect(opaqueRgba(computed.backgroundColor)).toEqual([32, 85, 170, 1]);
    expect(opaqueRgba(computed.borderTopColor)).toEqual([128, 181, 255, 1]);
    expect(opaqueRgba(computed.color)).toEqual([255, 255, 255, 1]);
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
  const hover = css.match(/(?:^|\n)\.primary:hover\s*\{([^}]+)\}/)?.[1];
  expect(base).toBeTruthy();
  expect(base).toMatch(/background:\s*#d9a628\s*;/i);
  expect(base).toMatch(/border-color:\s*#d9a628\s*;/i);
  expect(base).toMatch(/color:\s*#211b10\s*;/i);
  expect(hover).toMatch(/background:\s*#e7b73f\s*;/i);
});
