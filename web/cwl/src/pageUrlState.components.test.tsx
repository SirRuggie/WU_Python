// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ModerationWorkspace from "./ModerationWorkspace";
import StrikesWorkspace from "./StrikesWorkspace";
import { DashboardHistory } from "./dashboardHistory";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
vi.mock("./StrikeTrackingStatus", () => ({ default: () => null }));
vi.mock("./MemberActivityHistory", () => ({
  default: () => <p>History content</p>,
}));
vi.mock("./ModerationSettings", () => ({
  default: ({ view }: { view: string }) => <p>Settings content {view}</p>,
}));
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  transport.mockReset();
  transport.mockResolvedValue({ entries: [], total: 0, clans: [] });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const render = async (node: React.ReactNode) =>
  act(async () => root.render(node));
const visibleText = () =>
  [...host.querySelectorAll("p")]
    .filter((node) => !node.closest("[hidden]"))
    .map((node) => node.textContent);

it.each(["invites", "channels"])(
  "opens Moderation ?tab=%s with that tab's content",
  async (tab) => {
    history.replaceState({}, "", `/server/moderation?tab=${tab}`);
    await render(<ModerationWorkspace />);
    expect(visibleText()).toContain(`Settings content ${tab}`);
    expect(visibleText()).not.toContain("History content");
  },
);

it("falls back to the first visible Strikes tab and corrects the address", async () => {
  history.replaceState({}, "", "/strikes?tab=settings&activity_view=all");
  await render(
    <StrikesWorkspace
      permissions={["strikes_remove"]}
      isOwner={false}
      userId="1"
    />,
  );
  const tabs = [
    ...host.querySelectorAll('[aria-label="Strike sections"] button'),
  ];
  expect(tabs.map((node) => node.textContent)).not.toContain("Settings");
  expect(
    tabs.find((node) => node.getAttribute("aria-pressed") === "true")
      ?.textContent,
  ).toBe("Accounts");
  expect(window.location.search).not.toContain("tab=settings");
  expect(window.location.search).toContain("activity_view=all");
});

it.each([
  ["/tickets?status=closed", "tickets", "42", "?status=closed"],
  ["/strikes?tab=leave", "strikes", "42", "?tab=leave"],
])(
  "keeps page params of %s when App writes a season",
  (start, view, season, expected) => {
    history.replaceState({}, "", start);
    new DashboardHistory(window.history).write(
      { view: view as "tickets" | "strikes", season },
      false,
    );
    expect(window.location.search).toBe(expected);
  },
);
