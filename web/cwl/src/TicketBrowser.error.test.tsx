// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TicketBrowser from "./TicketBrowser";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  api.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows a failed ticket load once, with Try again", async () => {
  api.mockRejectedValueOnce(new Error("Tickets unavailable"));
  api.mockResolvedValue({ tickets: [], has_more: false });
  await act(async () => root.render(<TicketBrowser />));
  const text = host.textContent || "";
  expect(text.split("Tickets unavailable")).toHaveLength(2);
  const retry = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Try again",
  )!;
  expect(retry).toBeTruthy();
  await act(async () => retry.click());
  expect(host.querySelector(".load-error")).toBeNull();
  expect(api).toHaveBeenCalledTimes(2);
});
