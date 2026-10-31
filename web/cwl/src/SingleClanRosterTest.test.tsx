// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
vi.mock("./ChannelCombobox", () => ({
  default: ({ onChange }: { onChange: (value: string) => void }) => (
    <button onClick={() => onChange("123456789012345678")}>
      Pick test channel
    </button>
  ),
}));
vi.mock("./ConfirmDialog", () => ({
  default: ({
    text,
    onConfirm,
    onCancel,
  }: {
    text: string;
    onConfirm: () => void;
    onCancel: () => void;
  }) => (
    <div role="dialog">
      {text}
      <button onClick={onConfirm}>Confirm test</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  ),
}));
import SingleClanRosterTest from "./SingleClanRosterTest";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const clans = ["#AAA", "#BBB", "#CCC", "#DDD"].map((tag, index) => ({
  tag,
  name: `Clan ${index + 1}`,
  pool: "lazy",
  count: 15,
  pages: index === 1 ? 2 : 1,
}));
const acquire = vi.fn(() => vi.fn());
async function click(label: string) {
  const button = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === label,
  )!;
  expect(button).toBeDefined();
  await act(async () => button.click());
}
async function loaded() {
  await act(async () =>
    host
      .querySelectorAll("img")
      .forEach((img) => img.dispatchEvent(new Event("load"))),
  );
}
beforeEach(async () => {
  api.mockReset();
  acquire.mockClear();
  api.mockImplementation(async (path: string, method?: string) =>
    method === "POST"
      ? { url: "https://discord.com/channels/1/2/3" }
      : path === "/announcement-channels"
        ? { channels: [] }
        : { version: 3, season: "Test", clans },
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <SingleClanRosterTest seasonId="1" version={3} acquire={acquire} />,
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("loads current and adjacent clans only, stacks pages and sends the shown clan", async () => {
  expect([...host.querySelectorAll("img")].map((img) => img.alt)).toEqual([
    "Clan 1 finalized roster, page 1",
    "Clan 2 finalized roster, page 1",
    "Clan 2 finalized roster, page 2",
  ]);
  await click("Next clan");
  await loaded();
  await click("Pick test channel");
  expect(host.textContent).toContain("Clan 2 of 4");
  await click("Send Clan 2 test");
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(0);
  await click("Confirm test");
  const writes = api.mock.calls.filter((call) => call[1] === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/seasons/1/roster-images/%23BBB/test");
  expect(writes[0][2]).toMatchObject({
    version: 3,
    channel_id: "123456789012345678",
  });
});
it("jump list and keyboard select clans without loading every image", async () => {
  await click("Clan 1");
  await click("Clan 4 · 15 players");
  expect(host.textContent).toContain("Clan 4 of 4");
  expect(host.querySelectorAll("img")).toHaveLength(2);
  const rail = host.querySelector(".image-carousel-rail")!;
  await act(async () =>
    rail.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
    ),
  );
  expect(host.textContent).toContain("Clan 3 of 4");
  expect(
    [...host.querySelectorAll("img")].some((img) =>
      img.alt.startsWith("Clan 1"),
    ),
  ).toBe(false);
});
it("a settled swipe selects the visible clan", async () => {
  const rail = host.querySelector(".image-carousel-rail") as HTMLDivElement;
  rail.getBoundingClientRect = () => ({ left: 0, width: 360 }) as DOMRect;
  [...rail.children].forEach((card, index) => {
    card.getBoundingClientRect = () =>
      ({ left: (index - 2) * 360, width: 360 }) as DOMRect;
  });
  rail.scrollTo = vi.fn();
  await act(async () => {
    rail.dispatchEvent(new Event("pointerdown"));
    rail.dispatchEvent(new Event("scrollend"));
  });
  expect(host.textContent).toContain("Clan 3 of 4");
  await loaded();
  await click("Pick test channel");
  await click("Send Clan 3 test");
  await click("Confirm test");
  expect(api.mock.calls.find((call) => call[1] === "POST")?.[0]).toBe(
    "/seasons/1/roster-images/%23CCC/test",
  );
});
it("all pages must load before sending and cancel performs no write", async () => {
  await click("Next clan");
  await click("Pick test channel");
  const images = host.querySelectorAll('article[aria-hidden="false"] img');
  await act(async () => images[0].dispatchEvent(new Event("load")));
  const send = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Send Clan 2 test",
  )!;
  expect(send.disabled).toBe(true);
  await act(async () => images[1].dispatchEvent(new Event("load")));
  expect(send.disabled).toBe(false);
  await click("Send Clan 2 test");
  await click("Cancel");
  expect(api.mock.calls.filter((call) => call[1] === "POST")).toHaveLength(0);
});
