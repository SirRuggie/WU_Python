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
import { loginPath } from "./memberLinks";
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
  expect(cards[0].textContent).toContain("Base link not available yet");
  expect(cards[1].querySelector("a")?.getAttribute("href")).toBe(link);
  expect(cards[1].querySelector("a")?.textContent).toBe("Copy base");
  expect(host.textContent).toContain("Base image not available yet");
  expect(mock.api).toHaveBeenCalledTimes(1);
});
it("does not fetch details until open and never renders external HTML", async () => {
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
  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector("[onerror]")).toBeNull();
});

it("renders both Details blocks with safe Discord formatting and non-clickable links", async () => {
  await mount();
  mock.api.mockResolvedValue({
    key: "th18_new",
    base_information: [
      "# Title",
      "### Sub",
      "**bold** :white_check_mark:",
      "- item",
      "<:TH18:1447965910735519906>",
      "[Guide](https://example.com/guide)",
      "<script>alert('unsafe')</script>",
      '<img src="x" onerror="alert(1)">',
    ].join("\n\n"),
    base_upgrade_notes: "## Upgrade notes\n\n**Keep heroes available**",
  });
  const details = host.querySelector("details")!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await flush();
  const blocks = details.querySelectorAll(".base-bank-details");
  expect(blocks).toHaveLength(2);
  expect(blocks[0].querySelector("h1")?.textContent).toBe("Title");
  expect(blocks[0].querySelector("h3")?.textContent).toBe("Sub");
  expect(blocks[0].querySelector("strong")?.textContent).toBe("bold");
  expect(blocks[0].querySelector("li")?.textContent).toBe("item");
  expect(blocks[0].textContent).toContain("✅");
  expect(blocks[0].querySelector('img[alt="TH18"]')?.getAttribute("src")).toBe(
    "https://cdn.discordapp.com/emojis/1447965910735519906.png",
  );
  expect(blocks[0].textContent).not.toMatch(/\*\*|#|:white_check_mark:|<:/);
  expect(blocks[0].querySelector(".discord-preview-link")?.textContent).toBe(
    "Guide",
  );
  expect(blocks[1].querySelector("h2")?.textContent).toBe("Upgrade notes");
  expect(blocks[1].querySelector("strong")?.textContent).toBe(
    "Keep heroes available",
  );
  expect(details.querySelector("a, script, [onerror]")).toBeNull();
  expect(details.querySelectorAll("img")).toHaveLength(1);
  await act(async () =>
    details.querySelector("img")!.dispatchEvent(new Event("error")),
  );
  expect(details.querySelector("img")).toBeNull();
  expect(details.querySelector(".discord-image-placeholder")?.textContent).toBe(
    "TH18",
  );
  expect(mock.api.mock.calls.every((call) => call[1] === "GET")).toBe(true);
});

it("keeps mention context in either Details block without exposing Discord IDs", async () => {
  await mount();
  mock.api.mockResolvedValue({
    key: "th18_new",
    base_information: "Ask <@&123456789012345678> or <@!234567890123456789>.",
    base_upgrade_notes: "See <#345678901234567890> and <@456789012345678901>.",
  });
  const details = host.querySelector("details")!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await flush();
  expect(details.textContent).toContain("Ask @role or @member.");
  expect(details.textContent).toContain("See #channel and @member.");
  expect(details.textContent).not.toMatch(/\d{17,20}|<[@#]/);
  expect(details.querySelector("a")).toBeNull();
});

it("keeps Town Hall in accessible names while showing only the variant tag", async () => {
  mock.api.mockResolvedValue({
    bases: [{ ...bases[0], war_base_image: "https://example.com/base.png" }],
  });
  await mount();
  expect(host.querySelector("article")?.getAttribute("aria-label")).toBe(
    "TH18 Non-merged defenses",
  );
  expect(
    host.querySelector(".base-bank-copy")?.getAttribute("aria-label"),
  ).toBe("Copy TH18 non-merged defenses base");
  expect(
    [...host.querySelectorAll(".base-bank-tags span")].map(
      (tag) => tag.textContent,
    ),
  ).toEqual(["Non-merged defenses"]);
  const image = host.querySelector(".base-bank-image img")!;
  expect(image.getAttribute("width")).toBe("480");
  expect(image.getAttribute("height")).toBe("300");
  await act(async () => image.dispatchEvent(new Event("error")));
  expect(host.querySelector(".base-bank-image img")).toBeNull();
  expect(host.querySelector(".base-bank-image")?.textContent).toBe(
    "Base image not available yet",
  );
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
  expect(host.textContent).toContain("Could not load Base bank");
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

it("keeps the signed-out bases destination through login", () => {
  expect(loginPath("", false, "/bases")).toContain("bases");
});
it("never exposes an unvalidated upstream copy link", async () => {
  mock.api.mockResolvedValue({
    bases: [{ ...bases[0], link: "javascript:alert(1)" }],
  });
  await mount();
  expect(host.querySelector("a")).toBeNull();
  expect(host.textContent).toContain("Base link not available yet");
});
