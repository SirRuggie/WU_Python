// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { StrictMode, act } from "react";
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
          can_replay: false,
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

async function render(
  replaySignal = 0,
  view = "home",
  strict = false,
  blockedByTour = false,
  startBlocked = false,
) {
  const panel = (
    <OwnerPrank
      view={view}
      blockedByTour={blockedByTour}
      startBlocked={startBlocked}
      replaySignal={replaySignal}
      onSettled={settled}
      onReplayAvailable={replayAvailable}
      onError={onError}
    />
  );
  await act(async () => {
    root.render(strict ? <StrictMode>{panel}</StrictMode> : panel);
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

it.each(Array.from({ length: 15 }, (_, index) => index + 1))(
  "renders card %i without a step number or progress indicator",
  async (card) => {
    server = { ...server, card, branch: "yes" };
    await render();
    const dialog = document.querySelector(".owner-prank-card");
    expect(dialog).not.toBeNull();
    expect(
      dialog?.querySelector(
        '.owner-prank-step, .tour-step, [role="progressbar"], progress, .progress-pill',
      ),
    ).toBeNull();
    expect(dialog?.textContent).not.toMatch(/\b\d+\s+of\s+(?:\?|\d+)/i);
  },
);

it("takes both bait branches through the fake deletion and reassurance without signup writes", async () => {
  await render();
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
  expect(settled).not.toHaveBeenCalled();
  await press("No");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Deleted 42/42 signups",
  );
  expect(
    document.querySelector(".owner-prank-card .owner-prank-step"),
  ).toBeNull();
  expect(document.querySelector(".owner-prank-card")?.textContent).not.toMatch(
    /\b\d+\s+of\s+(?:\?|\d+)/i,
  );
  expect(server.branch).toBe("no");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2100));
  });
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "No real signups were deleted.",
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

it("silently releases the tour when the prank state read fails", async () => {
  api.mockImplementationOnce(async () => {
    throw new Error("network unavailable");
  });
  await render();
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(settled).toHaveBeenCalledTimes(1);
  expect(onError).not.toHaveBeenCalled();
});

it("resumes saved card 2 directly at the Wizard", async () => {
  server = { ...server, card: 2, branch: "yes" };
  await render();
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "HEY!! WHAT ARE YOU DOING?!",
  );
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "No real signups were deleted.",
  );
  expect(
    api.mock.calls.some(
      ([, , body]) => body?.event === "prank_card_seen" && body.card === 3,
    ),
  ).toBe(true);
  expect(
    api.mock.calls.some(
      ([, , body]) => body?.event === "prank_jumpscare_seen" && body.card === 3,
    ),
  ).toBe(true);
});

it("opens once after StrictMode effect replay with a pending read", async () => {
  let resolveRead!: (state: PrankState) => void;
  const pendingRead = new Promise<PrankState>((resolve) => {
    resolveRead = resolve;
  });
  const delegate = api.getMockImplementation()!;
  api.mockImplementation((...args) =>
    args[0] === "/prank/state" ? pendingRead : delegate(...args),
  );
  await render(0, "home", true);
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  await act(async () => {
    resolveRead({ ...server });
  });
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
  expect(
    api.mock.calls.filter(([, , body]) => body?.event === "prank_opened"),
  ).toHaveLength(1);
  await act(async () => {
    document.querySelector<HTMLButtonElement>(".owner-prank-close")!.click();
  });
  expect(settled).toHaveBeenCalledTimes(1);
});

it("keeps the pending read when navigating from Home to Tasks", async () => {
  let resolveRead!: (state: PrankState) => void;
  api.mockImplementationOnce(
    () =>
      new Promise<PrankState>((resolve) => {
        resolveRead = resolve;
      }),
  );
  await render();
  await render(0, "todo");
  await act(async () => {
    resolveRead({ ...server });
  });
  expect(document.querySelector(".owner-prank-dialog")).not.toBeNull();
  expect(settled).not.toHaveBeenCalled();
});

it("starts on Tasks as the first page", async () => {
  await render(0, "todo");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("waits for a dirty roster editor and starts when clean", async () => {
  await render(0, "roster", false, false, true);
  expect(api).not.toHaveBeenCalled();
  await render(0, "roster");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("waits for a dirty roster editor and starts after navigation", async () => {
  await render(0, "roster", false, false, true);
  await render(0, "todo");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("defers a pending state read when signup becomes dirty", async () => {
  let resolveRead!: (state: PrankState) => void;
  api.mockImplementationOnce(
    () =>
      new Promise<PrankState>((resolve) => {
        resolveRead = resolve;
      }),
  );
  await render(0, "signup");
  await render(0, "signup", false, false, true);
  await act(async () => {
    resolveRead({ ...server });
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(
    api.mock.calls.some(([, , body]) => body?.event === "prank_opened"),
  ).toBe(false);
  await render(0, "signup");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("receives the signup draft dirty flag from App", () => {
  const app = readFileSync("src/App.tsx", "utf8");
  const prank = app.slice(app.indexOf("<OwnerPrank view="));
  expect(prank).toMatch(/startBlocked=\{[^}]*signupDirty/);
});

it("waits for another dialog to close before starting", async () => {
  const other = document.createElement("dialog");
  other.setAttribute("open", "");
  document.body.append(other);
  await render(0, "todo");
  expect(api).not.toHaveBeenCalled();
  await act(async () => {
    other.remove();
  });
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("defers a pending state read when another dialog opens", async () => {
  let resolveRead!: (state: PrankState) => void;
  api.mockImplementationOnce(
    () =>
      new Promise<PrankState>((resolve) => {
        resolveRead = resolve;
      }),
  );
  await render(0, "todo");
  const other = document.createElement("dialog");
  await act(async () => {
    other.setAttribute("open", "");
    document.body.append(other);
  });
  await act(async () => {
    resolveRead({ ...server });
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(
    api.mock.calls.some(([, , body]) => body?.event === "prank_opened"),
  ).toBe(false);
  await act(async () => {
    other.remove();
  });
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
  expect(
    api.mock.calls.filter(([, , body]) => body?.event === "prank_opened"),
  ).toHaveLength(1);
});

it("defers opening when another dialog appears during the opening event", async () => {
  const delegate = api.getMockImplementation()!;
  let resolveOpen!: (state: PrankState) => void;
  let held = false;
  api.mockImplementation((...args) => {
    if (
      args[0] === "/prank/event" &&
      args[2]?.event === "prank_opened" &&
      !held
    ) {
      held = true;
      return new Promise<PrankState>((resolve) => {
        resolveOpen = resolve;
      });
    }
    return delegate(...args);
  });
  await render(0, "todo");
  const other = document.createElement("dialog");
  await act(async () => {
    other.setAttribute("open", "");
    document.body.append(other);
  });
  await act(async () => {
    resolveOpen({ ...server });
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  await act(async () => {
    other.remove();
  });
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("waits for an off-Home manual tour to close before starting", async () => {
  await render(0, "home", false, true);
  expect(
    api.mock.calls.filter(([path]) => path === "/prank/state"),
  ).toHaveLength(0);
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  await render(0, "todo", false, false);
  expect(
    api.mock.calls.filter(([path]) => path === "/prank/state"),
  ).toHaveLength(1);
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("discards a pending state read when the tour starts", async () => {
  let resolveRead!: (state: PrankState) => void;
  api.mockImplementationOnce(
    () =>
      new Promise<PrankState>((resolve) => {
        resolveRead = resolve;
      }),
  );
  await render();
  await render(0, "home", false, true);
  await act(async () => {
    resolveRead({ ...server });
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  await render(0, "home", false, false);
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
  expect(
    api.mock.calls.filter(([, , body]) => body?.event === "prank_opened"),
  ).toHaveLength(1);
});

it("resumes on a fresh mount after closing early", async () => {
  await render(0, "todo");
  await act(async () => {
    document.querySelector<HTMLButtonElement>(".owner-prank-close")!.click();
  });
  await render(0, "home");
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  await act(async () => {
    root.unmount();
  });
  root = createRoot(host);
  await render(0, "todo");
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
});

it("uses the saved replay entitlement to start a new run", async () => {
  server = {
    ...server,
    card: 15,
    branch: "yes",
    completed_at: "2026-10-29T00:00:00Z",
    can_replay: true,
  };
  await render();
  expect(replayAvailable).toHaveBeenCalledWith(true);
  await render(1);
  expect(document.querySelector(".owner-prank-card")?.textContent).toContain(
    "Remove all signups?",
  );
  expect(
    api.mock.calls.some(
      ([, , body]) =>
        body?.event === "prank_replay" && body.card === 15 && body.run === 1,
    ),
  ).toBe(true);
  expect(replayAvailable).toHaveBeenCalledWith(false);
});

it("Escape closes the prank early and saves its card", async () => {
  await render();
  await act(async () => {
    document
      .querySelector<HTMLDialogElement>(".owner-prank-dialog")!
      .dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  expect(document.querySelector(".owner-prank-dialog")).toBeNull();
  expect(
    api.mock.calls.some(
      ([, , body]) => body?.event === "prank_closed_early" && body.card === 1,
    ),
  ).toBe(true);
});
