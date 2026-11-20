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

function expectNoRetiredLogoMarkup(host: HTMLElement) {
  for (const element of host.querySelectorAll("img, source")) {
    expect(element.getAttribute("src") ?? "").not.toMatch(/wu-helmet/);
    expect(element.getAttribute("srcset") ?? "").not.toMatch(/wu-helmet/);
  }
}

afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

it("uses the large self-hosted WU crest throughout loading and signed-out branding without changing its words", async () => {
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
    expectNoRetiredLogoMarkup(host);
    const loading = host.querySelector<HTMLImageElement>(
      'img[alt="Warriors United logo"]',
    )!;
    expect(loading.getAttribute("src")).toBe("/brand/wu-crest-120.png");
    expect(loading.getAttribute("srcset")).toBe(
      "/brand/wu-crest-120.png 1x, /brand/wu-crest-240.png 2x, /brand/wu-crest-360.png 3x",
    );
    expect(loading.closest(".brand--large")).not.toBeNull();
    expect(loading.parentElement?.tagName).toBe("PICTURE");
    const source = loading.parentElement?.querySelector("source");
    expect(source?.getAttribute("type")).toBe("image/webp");
    expect(source?.getAttribute("media")).toBe("(min-width: 900px)");
    expect(source?.getAttribute("srcset")).toBe(
      "/brand/wu-crest-160.webp 1x, /brand/wu-crest-320.webp 2x, /brand/wu-crest-480.webp 3x",
    );
    expect(
      loading.parentElement
        ?.querySelector("source:not([media])")
        ?.getAttribute("srcset"),
    ).toBe(
      "/brand/wu-crest-120.webp 1x, /brand/wu-crest-240.webp 2x, /brand/wu-crest-360.webp 3x",
    );
    expect(
      loading.parentElement
        ?.querySelector('source[type="image/png"]')
        ?.getAttribute("srcset"),
    ).toBe(
      "/brand/wu-crest-160.png 1x, /brand/wu-crest-320.png 2x, /brand/wu-crest-480.png 3x",
    );
    expect([loading.width, loading.height]).toEqual([99, 120]);
    expect(host.textContent).toContain("Checking Discord sign-in…");
    const { ApiError } = await import("./api");
    await act(async () => {
      rejectAuth(new ApiError("Signed out", 401));
    });
    expectNoRetiredLogoMarkup(host);
    const welcome = host.querySelector<HTMLImageElement>(
      '.welcome-screen img[alt="Warriors United logo"]',
    )!;
    expect(welcome.getAttribute("src")).toBe("/brand/wu-crest-120.png");
    expect(welcome.parentElement?.tagName).toBe("PICTURE");
    expect(host.querySelector(".brand strong")?.textContent).toBe(
      "WARRIORS UNITED",
    );
    expect(host.querySelector(".brand small")?.textContent).toBe(
      "Server dashboard",
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
      src: "/icons/wu-crest-192.png",
      sizes: "192x192",
      type: "image/png",
      purpose: "any",
    },
    {
      src: "/icons/wu-crest-512.png",
      sizes: "512x512",
      type: "image/png",
      purpose: "any",
    },
  ]);
  for (const icon of manifest.icons) {
    expect(
      existsSync(
        `public${new URL(icon.src, "https://fixture.invalid").pathname}`,
      ),
    ).toBe(true);
  }
  expect(existsSync("public/icons/wu-maskable-512.png")).toBe(false);
});

it("keeps the signed-in sidebar WU crest at its portrait height with its compact density sources", async () => {
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
    expectNoRetiredLogoMarkup(host);
    const logo = host.querySelector<HTMLImageElement>(
      '.sidebar img[alt="Warriors United logo"]',
    )!;
    expect(logo).not.toBeNull();
    expect(logo.getAttribute("src")).toBe("/brand/wu-crest-39.png");
    expect(logo.getAttribute("srcset")).toBe(
      "/brand/wu-crest-39.png 1x, /brand/wu-crest-78.png 2x, /brand/wu-crest-117.png 3x",
    );
    expect([logo.width, logo.height]).toEqual([32, 39]);
    expect(logo.closest(".brand--large")).toBeNull();
    expect(logo.closest("picture")).toBeNull();
    expect(host.querySelector(".sidebar .brand strong")?.textContent).toBe(
      "WARRIORS UNITED",
    );
    expect(host.querySelector(".sidebar .brand small")?.textContent).toBe(
      "Server dashboard",
    );
    const phoneLogo = host.querySelector<HTMLImageElement>(
      ".topbar .topbar-logo",
    )!;
    expect(phoneLogo.getAttribute("src")).toBe("/brand/wu-crest-39.png");
    expect(phoneLogo.getAttribute("srcset")).toBe(
      "/brand/wu-crest-39.png 1x, /brand/wu-crest-78.png 2x, /brand/wu-crest-117.png 3x",
    );
    expect(phoneLogo.getAttribute("alt")).toBe("");
    expect(phoneLogo.getAttribute("aria-hidden")).toBe("true");
    expect([phoneLogo.width, phoneLogo.height]).toEqual([26, 32]);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("resolves every icon and OG image URL to the approved local public art", () => {
  const markup = new DOMParser().parseFromString(
    readFileSync("index.html", "utf8"),
    "text/html",
  );
  const paths = [
    ...markup.querySelectorAll(
      'link[rel="icon"], link[rel="apple-touch-icon"], meta[property="og:image"]',
    ),
  ].map((node) => node.getAttribute("href") ?? node.getAttribute("content")!);
  expect(paths).toEqual([
    "/icons/wu-crest-favicon-32.png",
    "/icons/wu-crest-favicon-48.png",
    "/favicon.ico?v=crest1",
    "/icons/wu-crest-apple-touch-180.png",
    "https://dash.warriorsunited.cc/brand/wu-crest-og.png",
  ]);
  for (const value of paths) {
    const url = new URL(value, "https://fixture.invalid");
    expect(existsSync(`public${url.pathname}`)).toBe(true);
  }
  expect(
    markup
      .querySelector('meta[property="og:image:width"]')
      ?.getAttribute("content"),
  ).toBe("1200");
  expect(
    markup
      .querySelector('meta[property="og:image:height"]')
      ?.getAttribute("content"),
  ).toBe("630");
  expect(
    markup
      .querySelector('meta[property="og:image:alt"]')
      ?.getAttribute("content"),
  ).toBe("Warriors United logo");
});
