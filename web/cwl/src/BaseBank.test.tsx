// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({ api: vi.fn(), accounts: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mock.api,
}));
vi.mock("./accountDisplay", () => ({ loadAccountDisplay: mock.accounts }));
import { ApiError } from "./api";
import BaseBank from "./BaseBank";
import { defaultTownHall, baseLink, type BankBase } from "./baseBank";
const link = "https://link.clashofclans.com/en?action=OpenLayout&id=fixture";
const bases: BankBase[] = [
  {
    key: "th18_new",
    town_hall: 18,
    variant: "non-merged",
    link,
    war_base_image: null,
    has_details: true,
  },
  {
    key: "th18",
    town_hall: 18,
    variant: "merged",
    link: null,
    war_base_image: null,
    has_details: false,
  },
  {
    key: "th17",
    town_hall: 17,
    variant: "merged",
    link,
    war_base_image: null,
    has_details: false,
  },
];
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const flush = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mock.api.mockReset().mockResolvedValue({ bases });
  mock.accounts
    .mockReset()
    .mockResolvedValue({ accounts: [{ town_hall: 17 }] });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
async function mount(linked: (number | null)[] | null = [18]) {
  await act(async () => root.render(<BaseBank townHalls={linked} />));
  await flush();
}
it("selects highest available linked TH, otherwise highest available", () => {
  expect(defaultTownHall(bases, [17, 16])).toBe(17);
  expect(defaultTownHall(bases, [19, 17])).toBe(17);
  expect(defaultTownHall(bases, [16])).toBe(18);
  expect(defaultTownHall(bases, null)).toBe(18);
  expect(defaultTownHall([], [])).toBeNull();
  expect(baseLink("https://evil.example/")).toBeNull();
  expect(baseLink("javascript:alert(1)")).toBeNull();
  expect(baseLink(link)).toBe(link);
});
it("sorts merged first, shows no copy button for missing link, uses uncropped images", async () => {
  await mount();
  const cards = [...host.querySelectorAll("article")];
  expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual([
    "TH18 Merged defenses",
    "TH18 Non-merged defenses",
  ]);
  expect(cards[0].querySelector("a")).toBeNull();
  expect(cards[0].textContent).toContain("Base link coming soon");
  expect(cards[1].querySelector("a")?.getAttribute("href")).toBe(link);
  expect(cards[1].querySelector("a")?.textContent).toBe("Copy base");
  expect(host.textContent).toContain("Base image coming soon");
  expect(mock.api).toHaveBeenCalledTimes(1);
});
it("does not fetch details until open; renders external text as plain text", async () => {
  await mount();
  expect(mock.api).toHaveBeenCalledTimes(1);
  mock.api.mockResolvedValue({
    key: "th18_new",
    base_information: "<img src=x onerror=alert(1)>",
    base_upgrade_notes: "Notes",
  });
  const details = host.querySelector("details")!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await flush();
  expect(mock.api).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("<img src=x onerror=alert(1)>");
  expect(host.querySelector("img")).toBeNull();
});
it("late linked accounts choose their TH but cannot override an explicit selection", async () => {
  await mount(null);
  await act(async () => root.render(<BaseBank townHalls={[17]} />));
  expect(host.querySelector('button[aria-pressed="true"]')?.textContent).toBe(
    "17",
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label="Town Hall 18"]')!
      .click(),
  );
  await act(async () => root.render(<BaseBank townHalls={[17, 16]} />));
  expect(host.querySelector('button[aria-pressed="true"]')?.textContent).toBe(
    "18",
  );
});
it("distinguishes empty, unavailable and signed-out states", async () => {
  mock.api.mockResolvedValue({ bases: [] });
  await mount();
  expect(host.textContent).toContain("No bases are available");
  await act(async () => root.unmount());
  root = createRoot(host);
  mock.api.mockRejectedValue(new Error("fixture"));
  await mount();
  expect(host.textContent).toContain("Couldn't load Base bank");
  mock.api.mockRejectedValue(new ApiError("Permission lost", 403));
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  await flush();
  expect(host.textContent).toContain("Sign in again");
  expect(host.querySelector("article")).toBeNull();
});

it("direct member route loads linked accounts independently of a CWL signup visit", async () => {
  await act(async () => root.render(<BaseBank />));
  await flush();
  expect(mock.accounts).toHaveBeenCalledTimes(1);
  expect(host.querySelector('button[aria-pressed="true"]')?.textContent).toBe(
    "17",
  );
});
