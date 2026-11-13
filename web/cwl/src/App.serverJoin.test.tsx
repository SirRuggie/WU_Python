// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardHome", () => ({ default: () => null }));
vi.mock("./TodoWorkspace", () => ({ default: () => null }));
import App from "./App";
import { ApiError } from "./api";
import { JOIN_REQUIRED_TEXT, SERVER_INVITE_URL } from "./ServerJoinNotice";

afterEach(() => {
  vi.restoreAllMocks();
  api.mockReset();
});

function mockApi(
  serverMember: boolean | null | undefined,
  save?: () => unknown,
) {
  api.mockImplementation(async (path: string, method = "GET") => {
    if (path === "/auth/me")
      return {
        authenticated: true,
        user: { id: "1", username: "Local fixture" },
        can_edit: false,
        is_owner: false,
        csrf_token: "fixture",
        dashboard_permissions: [],
        server_member: serverMember,
      };
    if (path === "/seasons")
      return {
        seasons: [
          { id: 1, label: "November", status: "draft", signup_open: true },
        ],
        member_season: { season_id: 1, revision: 1 },
      };
    if (path === "/config") return { dev_fixture: true };
    if (path.startsWith("/linked-accounts"))
      return {
        accounts: [
          {
            tag: "#PYY",
            name: "Fixture",
            town_hall: 18,
            current_clan_type: "CWL",
          },
        ],
        updating: false,
      };
    if (path.endsWith("/signups") && method === "POST") return save?.();
    if (path.endsWith("/signups")) return { signups: [] };
    return {};
  });
}

async function renderSignup() {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/signup");
  localStorage.clear();
  sessionStorage.clear();
  vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(
    () => {},
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  const host = document.createElement("div"),
    root = createRoot(host);
  document.body.append(host);
  await act(async () => root.render(<App />));
  for (let i = 0; i < 4; i++)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  const main = [
    ...host.querySelectorAll<HTMLButtonElement>(".pool-choice-grid button"),
  ].find((b) => b.querySelector("strong")?.textContent === "Main CWL")!;
  await act(async () => main.click());
  await act(async () =>
    host.querySelector<HTMLInputElement>(".account-card input")!.click(),
  );
  const cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  return { host, cleanup };
}

const continueButton = (host: HTMLElement) =>
  [...host.querySelectorAll<HTMLButtonElement>(".submit-bar button")].find(
    (b) => b.textContent === "Continue →",
  )!;

it("non-member sees the join line with the invite and cannot continue", async () => {
  mockApi(false);
  const { host, cleanup } = await renderSignup();
  try {
    const notice = host.querySelector(".server-join-notice")!;
    expect(notice.textContent).toBe(`${JOIN_REQUIRED_TEXT} Join server`);
    const link = notice.querySelector("a")!;
    expect(link.getAttribute("href")).toBe(SERVER_INVITE_URL);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(continueButton(host).disabled).toBe(true);
    expect(api.mock.calls.some(([, method]) => method === "POST")).toBe(false);
  } finally {
    cleanup();
  }
});

it.each([true, null, undefined])(
  "server_member %s shows no join line and allows continue",
  async (value) => {
    mockApi(value);
    const { host, cleanup } = await renderSignup();
    try {
      expect(host.querySelector(".server-join-notice")).toBeNull();
      expect(continueButton(host).disabled).toBe(false);
    } finally {
      cleanup();
    }
  },
);

it("a 403 join refusal on save shows the join line and blocks a second save", async () => {
  mockApi(null, () => {
    throw new ApiError(JOIN_REQUIRED_TEXT, 403);
  });
  const { host, cleanup } = await renderSignup();
  try {
    await act(async () => continueButton(host).click());
    const confirm = host.querySelector<HTMLButtonElement>(
      '[data-tour-target="signup-confirm"]',
    )!;
    await act(async () => confirm.click());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(host.querySelector(".server-join-notice")?.textContent).toContain(
      JOIN_REQUIRED_TEXT,
    );
    expect(continueButton(host).disabled).toBe(true);
    expect(
      api.mock.calls.filter(([, method]) => method === "POST"),
    ).toHaveLength(1);
  } finally {
    cleanup();
  }
});
