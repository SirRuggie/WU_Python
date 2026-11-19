// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
vi.mock("./StrikeTrackingStatus", () => ({ default: () => null }));
vi.mock("./ArrivalCheck", () => ({ default: () => null }));
import App from "./App";
import {
  slotCandidates241,
  slotClans241,
  slotFixtureReply241,
} from "../tests/fixtures/slotFixture241";
let host: HTMLDivElement, root: Root;
let previousURL: string, previousState: unknown;
let previousShowModal: PropertyDescriptor | undefined,
  previousClose: PropertyDescriptor | undefined;
let previousActEnvironment: PropertyDescriptor | undefined;
const settle = async () => {
  for (let index = 0; index < 5; index++)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
};
beforeAll(async () => {
  await import("./StrikesWorkspace");
});
beforeEach(() => {
  previousURL = location.href;
  previousState = structuredClone(history.state);
  previousShowModal = Object.getOwnPropertyDescriptor(
    HTMLDialogElement.prototype,
    "showModal",
  );
  previousClose = Object.getOwnPropertyDescriptor(
    HTMLDialogElement.prototype,
    "close",
  );
  previousActEnvironment = Object.getOwnPropertyDescriptor(
    globalThis,
    "IS_REACT_ACT_ENVIRONMENT",
  );
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  sessionStorage.clear();
  localStorage.clear();
  history.replaceState(
    { wuDashboardIndex: 0 },
    "",
    "/strikes?activity_view=replacements&slot_weight=179000&slot_weight=179000&slot_clan=%23PQQ",
  );
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  } as unknown as MediaQueryList);
  const accounts = slotCandidates241().map((row) => ({
    ...row,
    status: "risk",
    quiet_days: null,
  }));
  transport.mockReset().mockImplementation(async (path: string) => {
    if (path === "/auth/me")
      return {
        authenticated: true,
        user: { id: "123456789012345678", username: "Fixture" },
        is_owner: false,
        can_edit: false,
        csrf_token: "fixture",
        dashboard_permissions: ["strikes_remove"],
      };
    if (path === "/config") return { dev_fixture: true };
    if (path === "/seasons")
      return { seasons: [], member_season: { season_id: null, revision: 0 } };
    if (path.startsWith("/strikes/replacements"))
      return slotFixtureReply241(new URL(path, "http://fixture").searchParams);
    if (path.startsWith("/strikes/accounts"))
      return { accounts, clans: slotClans241 };
    return { entries: [], total: 0, clans: [], members: [], options: [] };
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  if (previousShowModal)
    Object.defineProperty(
      HTMLDialogElement.prototype,
      "showModal",
      previousShowModal,
    );
  else
    delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>)
      .showModal;
  if (previousClose)
    Object.defineProperty(HTMLDialogElement.prototype, "close", previousClose);
  else delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close;
  history.replaceState(previousState, "", previousURL);
  if (previousActEnvironment)
    Object.defineProperty(
      globalThis,
      "IS_REACT_ACT_ENVIRONMENT",
      previousActEnvironment,
    );
  else
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT;
  sessionStorage.clear();
  localStorage.clear();
});
// Test-only History boundary. happy-dom21.0.4 HistoryItemList.replace()
// incorrectly truncates forward entries; the browser replace algorithm does not.
// Keep App/Workspace/route writers real and model only the standard stack API.
function installSpecHistory() {
  const originalReplace = history.replaceState.bind(history);
  type Visit = { state: unknown; url: string };
  const visits: Visit[] = [
    {
      state: structuredClone(history.state),
      url: location.pathname + location.search,
    },
  ];
  let index = 0;
  const visit = (state: unknown, url?: string | URL | null): Visit => {
    const target = new URL(
      url == null ? location.href : String(url),
      location.href,
    );
    return {
      state: structuredClone(state),
      url: target.pathname + target.search + target.hash,
    };
  };
  vi.spyOn(history, "replaceState").mockImplementation((state, unused, url) => {
    visits[index] = visit(state, url);
    originalReplace(visits[index].state, unused, visits[index].url);
  });
  vi.spyOn(history, "pushState").mockImplementation((state, unused, url) => {
    visits.splice(index + 1);
    visits.push(visit(state, url));
    index++;
    originalReplace(visits[index].state, unused, visits[index].url);
  });
  vi.spyOn(history, "go").mockImplementation((delta = 0) => {
    const target = index + delta;
    if (!delta || target < 0 || target >= visits.length) return;
    index = target;
    originalReplace(visits[index].state, "", visits[index].url);
    const state = structuredClone(visits[index].state);
    queueMicrotask(() =>
      window.dispatchEvent(new PopStateEvent("popstate", { state })),
    );
  });
  vi.spyOn(history, "back").mockImplementation(() => history.go(-1));
  vi.spyOn(history, "forward").mockImplementation(() => history.go(1));
  return () => visits.map((row) => ({ ...row }));
}

it("mockHistory preserves forward entries on replace after Back and truncates them on push after Back", async () => {
  const visits = installSpecHistory();
  history.pushState({ wuDashboardIndex: 1 }, "", "/strikes?visit=forward");
  await act(async () => history.back());
  history.replaceState({ wuDashboardIndex: 0 }, "", "/strikes?visit=replaced");
  expect(visits()).toHaveLength(2);
  await act(async () => history.forward());
  expect(location.search).toBe("?visit=forward");
  await act(async () => history.back());
  history.pushState({ wuDashboardIndex: 1 }, "", "/strikes?visit=new");
  expect(visits()).toHaveLength(2);
  await act(async () => history.forward());
  expect(location.search).toBe("?visit=new");
});

it("keeps the exact slot account route/search/results after editing filters, Back/Forward and closing real App detail", async () => {
  const visits = installSpecHistory();
  await act(async () => root.render(<App />));
  await settle();
  const section = host.querySelector(".strike-find-slots");
  expect(section).not.toBeNull();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(".strike-slot-group li button")!
      .click(),
  );
  await settle();
  const tag = new URLSearchParams(location.search).get("tag");
  expect(tag).toBeTruthy();
  expect(host.querySelector(".strikes-detail-context")).not.toBeNull();
  const field = host.querySelector<HTMLInputElement>(
    'input[name="recruit-weights"]',
  )!;
  const typeWeight = async (value: string) => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(field, value);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 350));
    });
  };
  await typeWeight("150");
  await settle();
  expect(new URLSearchParams(location.search).get("tag")).toBe(tag);
  expect(new URLSearchParams(location.search).getAll("slot_weight")).toEqual([
    "150000",
  ]);
  expect(host.querySelector(".strike-find-slots")).toBe(section);
  expect(host.querySelectorAll(".strike-slot-group")).toHaveLength(1);
  expect(host.querySelector(".strikes-detail-context")).not.toBeNull();
  await act(async () => history.back());
  await settle();
  expect(new URLSearchParams(location.search).get("tag")).toBeNull();
  expect(field.value).toBe("179, 179");
  expect(host.querySelector(".strikes-detail-context")).toBeNull();
  expect(visits()).toHaveLength(2);
  expect(
    new URL(visits()[1].url, location.origin).searchParams.get("tag"),
  ).toBe(tag);
  await act(async () => history.forward());
  await settle();
  expect(new URLSearchParams(location.search).get("tag")).toBe(tag);
  expect(field.value).toBe("150");
  expect(host.querySelector(".strike-find-slots")).toBe(section);
  expect(host.querySelector(".strikes-detail-context")).not.toBeNull();
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((node) => node.textContent === "← Players")!
      .click(),
  );
  await settle();
  await typeWeight("173");
  await settle();
  expect(new URLSearchParams(location.search).get("tag")).toBeNull();
  expect(host.querySelector(".strikes-detail-context")).toBeNull();
  expect(host.querySelector(".strike-find-slots")).toBe(section);
  expect(
    transport.mock.calls.every((call) => !call[1] || call[1] === "GET"),
  ).toBe(true);
});
