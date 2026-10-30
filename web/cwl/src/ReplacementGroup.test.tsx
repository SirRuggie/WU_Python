// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api } from "./api";
import ReplacementGroup from "./ReplacementGroup";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const group = {
  clan_tag: "#R2Y",
  clan_name: "Family",
  listed: 30,
  at_three: 29,
  chopping_block: 2,
};
const candidate = (name: string) => ({
  player_tag: "#P2Y",
  player_name: name,
  active_strikes: 4,
  revision: 1,
});
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function render(
  open: boolean,
  query = "include_low=false&town_hall=17&sort=strikes",
  targetTag = "",
) {
  await act(async () =>
    root.render(
      <ReplacementGroup
        group={group}
        query={query}
        refresh={0}
        open={open}
        disabled={false}
        targetTag={targetTag}
        onToggle={() => {}}
        renderCandidate={(row) => <p>{row.player_name}</p>}
      />,
    ),
  );
}
it("leaves collapsed clans unfetched and pages with all filters", async () => {
  vi.mocked(api).mockResolvedValue({
    candidates: [candidate("First page")],
    total: 30,
  });
  await render(false);
  expect(api).not.toHaveBeenCalled();
  expect(host.textContent).toContain(
    "30 listed · 29 at 3+ strikes · 2 Chopping Block",
  );
  await render(true);
  expect(api).toHaveBeenCalledWith(
    "/strikes/replacements?include_low=false&town_hall=17&sort=strikes&clan=%23R2Y&offset=0&limit=25",
  );
  vi.mocked(api).mockResolvedValue({
    candidates: [candidate("Next page")],
    total: 30,
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "Next page")!
      .click(),
  );
  expect(api).toHaveBeenLastCalledWith(
    "/strikes/replacements?include_low=false&town_hall=17&sort=strikes&clan=%23R2Y&offset=25&limit=25",
  );
  expect(host.textContent).toContain("26–30 of 30");
  expect(host.textContent).not.toContain("First page");
});
it("ignores responses from a closed clan", async () => {
  let resolve!: (v: unknown) => void;
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }) as never,
  );
  await render(true);
  await render(false);
  await act(async () =>
    resolve({ candidates: [candidate("Stale result")], total: 30 }),
  );
  expect(host.textContent).not.toContain("Stale result");
});
it("fetches a deep-linked player outside the first page", async () => {
  vi.mocked(api).mockImplementation(
    async (path) =>
      ({
        candidates: path.includes("query=") ? [candidate("Target")] : [],
        total: 30,
      }) as never,
  );
  await render(true, "sort=weight", "#P2Y");
  expect(api).toHaveBeenCalledWith(
    "/strikes/replacements?sort=weight&clan=%23R2Y&offset=0&limit=25&query=%23P2Y",
  );
  expect(host.textContent).toContain("Target");
});
