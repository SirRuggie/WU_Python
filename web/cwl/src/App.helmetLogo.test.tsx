// @vitest-environment happy-dom
import { existsSync, readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./DashboardHome", () => ({ default: () => <p>Fixture Home</p> }));
vi.mock("./ownerPrank/OwnerPrank", () => ({ default: () => null }));

afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

it("uses the large self-hosted helmet throughout loading and signed-out branding without changing its words", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/home");
  let rejectAuth!: (cause: Error) => void;
  const pending = new Promise((_, reject) => {
    rejectAuth = reject;
  });
  state.api.mockImplementation((path: string) => {
    if (path === "/auth/me") return pending;
    if (path === "/config") return Promise.resolve({ dev_fixture: false });
    return Promise.resolve({});
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<App />));
    const loading = host.querySelector<HTMLImageElement>(
      'img[alt="Warriors United logo"]',
    )!;
    expect(loading.getAttribute("src")).toBe("/brand/wu-helmet-120.png");
    expect(loading.getAttribute("srcset")).toBe(
      "/brand/wu-helmet-120.png 1x, /brand/wu-helmet-240.png 2x, /brand/wu-helmet-360.png 3x",
    );
    expect(loading.closest(".brand--large")).not.toBeNull();
    expect(loading.parentElement?.tagName).toBe("PICTURE");
    const source = loading.parentElement?.querySelector("source");
    expect(source?.getAttribute("type")).toBe("image/webp");
    expect(source?.getAttribute("media")).toBe("(min-width: 900px)");
    expect(source?.getAttribute("srcset")).toBe(
      "/brand/wu-helmet-160.webp 1x, /brand/wu-helmet-320.webp 2x, /brand/wu-helmet-480.webp 3x",
    );
    expect(
      loading.parentElement
        ?.querySelector("source:not([media])")
        ?.getAttribute("srcset"),
    ).toBe(
      "/brand/wu-helmet-120.webp 1x, /brand/wu-helmet-240.webp 2x, /brand/wu-helmet-360.webp 3x",
    );
    expect(
      loading.parentElement
        ?.querySelector('source[type="image/png"]')
        ?.getAttribute("srcset"),
    ).toBe(
      "/brand/wu-helmet-160.png 1x, /brand/wu-helmet-320.png 2x, /brand/wu-helmet-480.png 3x",
    );
    expect([loading.width, loading.height]).toEqual([99, 120]);
    expect(host.textContent).toContain("Checking Discord sign-in…");
    const { ApiError } = await import("./api");
    await act(async () => {
      rejectAuth(new ApiError("Signed out", 401));
    });
    const welcome = host.querySelector<HTMLImageElement>(
      '.welcome-screen img[alt="Warriors United logo"]',
    )!;
    expect(welcome.getAttribute("src")).toBe("/brand/wu-helmet-120.png");
    expect(welcome.parentElement?.tagName).toBe("PICTURE");
    expect(host.querySelector(".brand strong")?.textContent).toBe(
      "WARRIORS UNITED",
    );
    expect(host.querySelector(".brand small")?.textContent).toBe(
      "SERVER DASHBOARD",
    );
    expect(host.querySelector(".welcome-screen .primary")?.textContent).toBe(
      "Continue with Discord",
    );
    expect(
      host.querySelectorAll('img[alt="Warriors United logo"]'),
    ).toHaveLength(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("keeps transparent any-icons and removes the maskable tile from the manifest and assets", () => {
  const manifest = JSON.parse(
    readFileSync("public/manifest.webmanifest", "utf8"),
  );
  expect(manifest.icons).toEqual([
    {
      src: "/icons/wu-192.png",
      sizes: "192x192",
      type: "image/png",
      purpose: "any",
    },
    {
      src: "/icons/wu-512.png",
      sizes: "512x512",
      type: "image/png",
      purpose: "any",
    },
  ]);
  expect(existsSync("public/icons/wu-maskable-512.png")).toBe(false);
});

it("keeps the signed-in sidebar helmet at its portrait height with its compact density sources", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/home");
  state.api.mockImplementation(async (path: string) => {
    if (path === "/auth/me")
      return {
        authenticated: true,
        user: { id: "1", username: "Fixture" },
        is_owner: true,
        can_edit: true,
        csrf_token: "fixture",
      };
    if (path === "/seasons")
      return { seasons: [], member_season: { season_id: null, revision: 0 } };
    if (path === "/config") return { dev_fixture: false };
    return {};
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<App />));
    const logo = host.querySelector<HTMLImageElement>(
      '.sidebar img[alt="Warriors United logo"]',
    )!;
    expect(logo).not.toBeNull();
    expect(logo.getAttribute("src")).toBe("/brand/wu-helmet-39.png");
    expect(logo.getAttribute("srcset")).toBe(
      "/brand/wu-helmet-39.png 1x, /brand/wu-helmet-78.png 2x, /brand/wu-helmet-117.png 3x",
    );
    expect([logo.width, logo.height]).toEqual([32, 39]);
    expect(logo.closest(".brand--large")).toBeNull();
    expect(logo.closest("picture")).toBeNull();
    expect(host.querySelector(".sidebar .brand strong")?.textContent).toBe(
      "WARRIORS UNITED",
    );
    expect(host.querySelector(".sidebar .brand small")?.textContent).toBe(
      "SERVER DASHBOARD",
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
