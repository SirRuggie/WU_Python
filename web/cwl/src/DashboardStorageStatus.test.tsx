// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import DashboardStorageStatus from "./DashboardStorageStatus";
import { api, ApiError } from "./api";
import { STORAGE_RECOVERED, STORAGE_UNAVAILABLE } from "./storageStatus";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

it("shows one staff line until a successful authenticated read confirms recovery", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        error: "Dashboard storage is recovering; check the saved result.",
      }),
      {
        status: 503,
        headers: {
          "Content-Type": "application/json",
          "X-Dashboard-Storage-Degraded": "1",
        },
      },
    ),
  );
  try {
    await act(async () => root.render(<DashboardStorageStatus />));
    expect(host.textContent).toBe("");
    await act(async () => {
      await expect(api("/fixture-save", "POST", {})).rejects.toBeInstanceOf(
        ApiError,
      );
    });
    expect(fetch).toHaveBeenCalledTimes(1); // Never retry a possibly accepted write.
    expect(host.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(host.textContent).toContain("Saves are temporarily unavailable");
    fetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await act(async () => {
      await api("/config");
    });
    expect(host.querySelector('[role="alert"]')).not.toBeNull(); // Public health is not recovery.
    fetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ authenticated: true }), { status: 200 }),
    );
    await act(async () => {
      await api("/auth/me");
    });
    expect(host.querySelector('[role="alert"]')).toBeNull();
  } finally {
    await act(async () => root.unmount());
  }
});

it("does not treat a generic provider outage as dashboard storage poisoning", async () => {
  const unavailable = vi.fn();
  window.addEventListener(STORAGE_UNAVAILABLE, unavailable);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: "Provider unavailable" }), {
      status: 503,
    }),
  );
  try {
    await expect(api("/fixture-save", "POST", {})).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(unavailable).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener(STORAGE_UNAVAILABLE, unavailable);
  }
});

it("removes storage listeners when the staff notice unmounts", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  const root = createRoot(host);
  const remove = vi.spyOn(window, "removeEventListener");
  await act(async () => root.render(<DashboardStorageStatus />));
  await act(async () => root.unmount());
  expect(remove).toHaveBeenCalledWith(
    STORAGE_UNAVAILABLE,
    expect.any(Function),
  );
  expect(remove).toHaveBeenCalledWith(STORAGE_RECOVERED, expect.any(Function));
});

it("keeps permanent attention visible when a later transient error arrives", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  const root = createRoot(host);
  try {
    await act(async () => root.render(<DashboardStorageStatus />));
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent(STORAGE_UNAVAILABLE, { detail: { attention: true } }),
      );
    });
    expect(host.textContent).toContain("needs attention");
    await act(async () => window.dispatchEvent(new Event(STORAGE_UNAVAILABLE)));
    expect(host.textContent).toContain("needs attention");
    expect(host.textContent).not.toContain("recovering");
    await act(async () => window.dispatchEvent(new Event(STORAGE_RECOVERED)));
    expect(host.textContent).toBe("");
  } finally {
    await act(async () => root.unmount());
  }
});
