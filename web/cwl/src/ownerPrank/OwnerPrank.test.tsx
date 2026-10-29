// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import OwnerPrank from "./OwnerPrank";
import { ApiError } from "../api";
import type { PrankState } from "./model";

const api = vi.fn();
vi.mock("../api", () => ({
  api: (...args: unknown[]) => api(...args),
  ApiError: class extends Error {
    constructor(
      message: string,
      public status: number,
    ) {
      super(message);
    }
  },
}));

let root: Root;
let host: HTMLDivElement;
let server: PrankState;
const settled = vi.fn();
const replayAvailable = vi.fn();
const onError = vi.fn();

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  server = {
    card: 1,
    branch: null,
    completed_at: null,
    run: 1,
    signup_count: 42,
    can_replay: false,
  };
  api.mockImplementation(
    async (
      path: string,
      method?: string,
      body?: {
        event: string;
        card: number;
        branch?: "yes" | "no";
        run: number;
      },
    ) => {
      if (path === "/prank/state") return { ...server };
      expect(path).toBe("/prank/event");
      expect(method).toBe("POST");
      expect(body?.run).toBe(server.run);
      if (body?.event === "prank_bait_yes" || body?.event === "prank_bait_no")
        server.branch = body.branch!;
      if (body?.event === "prank_card_seen") server.card = body.card;
      if (body?.event === "prank_completed")
        server.completed_at = "2026-10-29T00:00:00Z";
      if (body?.event === "prank_replay")
        server = {
          ...server,
          card: 1,
          branch: null,
          completed_at: null,
          run: 2,
        };
      return { ...server };
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.removeAttribute("open");
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  api.mockClear();
  settled.mockClear();
  replayAvailable.mockClear();
  onError.mockClear();
});

async function render(replaySignal = 0) {
  await act(async () => {
    root.render(
      <OwnerPrank
        view="home"
        replaySignal={replaySignal}
        onSettled={settled}
        onReplayAvailable={replayAvailable}
        onError={onError}
      />,
    );
  });
}

async function press(label: string) {
  const button = [
    ...document.querySelectorAll<HTMLButtonElement>(".owner-prank-card button"),
  ].find((item) => item.textContent === label);
  expect(button).toBeDefined();
  await act(async () => {
    button!.click();
  });
}

it("takes both bait branches through the fake deletion and reassurance without signup writes", async () => {
  await render();
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
  expect(document.querySelector(".owner-prank-step")).toBeNull();
  expect(settled).not.toHaveBeenCalled();
  await press("No");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Deleted 42/42 signups",
  );
  expect(document.querySelector(".owner-prank-step")).toBeNull();
  expect(server.branch).toBe("no");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2100));
  });
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "No real signups were deleted.",
  );
  expect(document.querySelector(".owner-prank-step")?.textContent).toBe(
    "3 of 15",
  );
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "You pressed No",
  );
  expect(
    api.mock.calls.every(([path]) => String(path).startsWith("/prank/")),
  ).toBe(true);
});

it("closes immediately, saves the current card, and stays closed for the visit", async () => {
  await render();
  await press("Yes");
  await act(async () => {
    document.querySelector<HTMLButtonElement>(".owner-prank-close")!.click();
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(
    api.mock.calls.some(
      ([, , body]) => body?.event === "prank_closed_early" && body.card === 2,
    ),
  ).toBe(true);
  expect(settled).toHaveBeenCalledTimes(1);
  await render();
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
});

it("advances through the Rickroll and four encores before final completion", async () => {
  await render();
  await press("Yes");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2100));
  });
  for (const label of [
    "Uh oh",
    "I can explain",
    "Fair point",
    "Seriously?",
    "Go on",
    "That's touching",
    "Wait a second",
  ])
    await press(label);
  expect(
    document.querySelector<HTMLImageElement>(".owner-prank-rickroll")?.src,
  ).toContain("media.tenor.com");
  for (const label of [
    "Dismiss",
    "Let me out",
    "That's enough",
    "PLEASE STOP",
    "I'm begging",
  ])
    await press(label);
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Well, Look Who Survived.",
  );
  await press("Finally Free");
  expect(server.completed_at).toBeTruthy();
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(
    api.mock.calls.filter(([, , body]) => body?.event === "prank_completed"),
  ).toHaveLength(1);
});

it("ignores a state read that finishes after sign-out unmounts the controller", async () => {
  let resolveState!: (value: PrankState) => void;
  api.mockImplementationOnce(
    () =>
      new Promise<PrankState>((resolve) => {
        resolveState = resolve;
      }),
  );
  await render();
  await act(async () => {
    root.unmount();
  });
  root = createRoot(host);
  await act(async () => {
    resolveState({ ...server });
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(settled).not.toHaveBeenCalled();
});

it("reads newer progress after another browser advanced two cards", async () => {
  server = { ...server, card: 4, branch: "yes" };
  await render();
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Buttons Fear You",
  );
  api.mockImplementationOnce(async () => {
    server = { ...server, card: 6 };
    throw new ApiError("Card sequence changed", 400);
  });
  await press("I can explain");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Relax, Nothing Broke",
  );
  expect(document.querySelector(".owner-prank-error")?.textContent).toContain(
    "another session",
  );
  const seen5 = api.mock.calls.filter(
    ([, , body]) => body?.event === "prank_card_seen" && body.card === 5,
  );
  expect(seen5).toHaveLength(1);
  expect(api.mock.calls.at(-1)?.[0]).toBe("/prank/state");
  await press("Seriously?");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "We've Got Your Back",
  );
});

it("closes when another browser completed the run", async () => {
  server = { ...server, card: 15, branch: "no" };
  await render();
  api.mockImplementationOnce(async () => {
    server = { ...server, completed_at: "2026-10-29T00:00:00Z", run: 2 };
    throw new ApiError("Prank run changed", 409);
  });
  await press("Finally Free");
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(settled).toHaveBeenCalledTimes(1);
  expect(replayAvailable).not.toHaveBeenCalledWith(true);
  expect(api.mock.calls.at(-1)?.[0]).toBe("/prank/state");
});

it("silently releases the tour when prank state is unavailable with 404", async () => {
  api.mockImplementationOnce(async () => {
    throw new ApiError("Not found", 404);
  });
  await render();
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(settled).toHaveBeenCalledTimes(1);
  expect(onError).not.toHaveBeenCalled();
});
