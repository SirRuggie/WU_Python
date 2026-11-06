// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikeActivityRows, {
  compactActivitySummary,
} from "./StrikeActivityRows";
import AccountCard from "./AccountCard";
import { parseActivityFilters } from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";

const account = (patch: Partial<ActivityAccount> = {}): ActivityAccount => ({
  player_tag: "#PYY",
  player_name: "Echo",
  current_clan_tag: "#PQQ",
  current_clan_name: "Local Alpha",
  town_hall: 16,
  weight: 149000,
  active_strikes: 2,
  total_strikes: 2,
  marked_for_replacement: false,
  status: "watch",
  quiet_days: 8,
  missed_attacks: 2,
  observed_attacks: 6,
  no_attack_wars: 2,
  observed_wars: 3,
  attacked_wars: 1,
  skipped_raid_weekends: 0,
  ...patch,
});
let host: HTMLDivElement, root: Root;
let narrow: boolean, media: MediaQueryList;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  narrow = true;
  const events = new EventTarget();
  media = {
    get matches() {
      return narrow;
    },
    media: "(max-width: 899px)",
    addEventListener: events.addEventListener.bind(events),
    removeEventListener: events.removeEventListener.bind(events),
    dispatchEvent: events.dispatchEvent.bind(events),
  } as MediaQueryList;
  vi.spyOn(window, "matchMedia").mockReturnValue(media);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const choose = vi.fn(),
  select = vi.fn(),
  sort = vi.fn();
async function render(
  patch: Partial<Parameters<typeof StrikeActivityRows>[0]> = {},
) {
  choose.mockClear();
  select.mockClear();
  sort.mockClear();
  await act(async () =>
    root.render(
      <StrikeActivityRows
        rows={[account()]}
        selecting={false}
        selected={[]}
        busy={false}
        filters={parseActivityFilters("?view=all")}
        onSort={sort}
        onSelected={select}
        onChoose={choose}
        {...patch}
      />,
    ),
  );
}

it("switches one rendered list at the 899/900 media boundary and removes its listener", async () => {
  const remove = vi.spyOn(media, "removeEventListener");
  await render();
  expect(window.matchMedia).toHaveBeenCalledWith("(max-width: 899px)");
  expect(host.querySelectorAll("article")).toHaveLength(1);
  expect(host.querySelector("table")).toBeNull();
  narrow = false;
  await act(async () => {
    media.dispatchEvent(new Event("change"));
  });
  expect(host.querySelectorAll("table")).toHaveLength(1);
  expect(host.querySelector("article")).toBeNull();
  narrow = true;
  await act(async () => {
    media.dispatchEvent(new Event("change"));
  });
  expect(host.querySelectorAll("article")).toHaveLength(1);
  expect(host.querySelector("table")).toBeNull();
  await act(async () => root.render(null));
  expect(remove).toHaveBeenCalledWith("change", expect.any(Function));
});
it("keeps the table and its sort/navigation behavior when matchMedia is absent", async () => {
  vi.stubGlobal("matchMedia", undefined);
  expect(window.matchMedia).toBeUndefined();
  await render();
  expect(host.querySelector("table")).not.toBeNull();
  expect(host.querySelector("article")).toBeNull();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Sort by Quiet"]')!
      .click(),
  );
  expect(sort).toHaveBeenCalledWith("quiet");
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click(),
  );
  expect(choose).toHaveBeenCalledExactlyOnceWith(account());
});
it("orders name, reason and TH/clan/Left/weight meta, retaining the seeded title and right-hand strikes", async () => {
  const row = account({
    town_hall: null,
    weight: null,
    current_clan_name: null,
    last_clan_name: "Previous clan",
    left_clan: true,
    last_seen_source: "ClashKing",
  });
  await render({ rows: [row] });
  const content = host.querySelector(".account-card-content")!;
  expect([...content.children].map((node) => node.className)).toEqual([
    "player-card-top",
    "account-card-detail",
    "player-card-meta account-card-meta",
    "account-card-action",
  ]);
  expect(
    content.querySelector(".strike-activity-row")?.getAttribute("title"),
  ).toBe("Echo #PYY");
  expect(
    content
      .querySelector(".strike-activity-row")
      ?.getAttribute("data-strike-player"),
  ).toBe("#PYY");
  const reason = content.querySelector(".strike-activity-card-reason")!;
  expect(reason.textContent).toBe(compactActivitySummary(row));
  expect(reason.getAttribute("title")).toBe(
    "~ Last seen: first value taken from ClashKing",
  );
  expect(content.querySelector(".account-card-meta")?.textContent).toBe(
    "TH— · Previous clan · Left · —",
  );
  expect(content.querySelector(".account-card-action")?.textContent).toBe(
    "2 strikes",
  );
  expect(content.querySelector(".account-card-status-row")).toBeNull();
});
it.each([true, false])(
  "preserves the exact checkbox restrictions in cards=%s",
  async (cards) => {
    narrow = cards;
    const rows = [
      account(),
      account({ player_tag: "#LEFT", left_clan: true }),
      account({ player_tag: "#NONE", current_clan_tag: null }),
    ];
    await render({ rows, selecting: true });
    const checks = [
      ...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    ];
    expect(checks.map((node) => node.disabled)).toEqual([false, true, true]);
    await act(async () => checks[0].click());
    expect(select).toHaveBeenCalledExactlyOnceWith(["#PYY"]);
    expect(choose).not.toHaveBeenCalled();
    const fifty = Array.from({ length: 50 }, (_, i) => `#TAG${i}`);
    await render({ rows, selecting: true, selected: fifty });
    expect(
      host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled,
    ).toBe(true);
    await render({
      rows,
      selecting: true,
      selected: ["#PYY", ...fifty.slice(1)],
    });
    const selected = host.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    expect(selected.disabled).toBe(false);
    expect(selected.checked).toBe(true);
    await act(async () => selected.click());
    expect(select).toHaveBeenCalledExactlyOnceWith(fifty.slice(1));
    await render({ rows, selecting: true, busy: true });
    expect(
      [
        ...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
      ].every((node) => node.disabled),
    ).toBe(true);
    await act(async () =>
      host.querySelector<HTMLButtonElement>(".strike-activity-row")!.click(),
    );
    expect(choose).not.toHaveBeenCalled();
  },
);
it.each([true, false])(
  "uses the same priority labels/classes in cards=%s and opens Details once",
  async (cards) => {
    narrow = cards;
    await render({
      rows: [
        account({ priority: "replace_first" }),
        account({ player_tag: "#HIGH", priority: "high" }),
      ],
    });
    expect(host.querySelector(".strike-priority-chopping")?.textContent).toBe(
      "Chopping Block",
    );
    expect(host.querySelector(".strike-priority-high")?.textContent).toBe(
      "High",
    );
    const rows = [
      ...host.querySelectorAll<HTMLButtonElement>(".strike-activity-row"),
    ];
    await act(async () => rows[0].click());
    expect(choose).toHaveBeenCalledExactlyOnceWith(
      account({ priority: "replace_first" }),
    );
  },
);
it("omits absent optional detail/status while preserving the existing supplied status branch", async () => {
  await act(async () =>
    root.render(<AccountCard thLevel={16} name="Echo" meta={["TH16"]} />),
  );
  expect(host.querySelector(".account-card-detail")).toBeNull();
  expect(host.querySelector(".account-card-status-row")).toBeNull();
  await act(async () =>
    root.render(
      <AccountCard
        thLevel={16}
        name="Echo"
        meta={["TH16"]}
        values="3 Attacks"
      />,
    ),
  );
  expect(host.querySelector(".account-card-values")?.textContent).toBe(
    "3 Attacks",
  );
  expect(host.querySelector(".account-card-value-separator")).toBeNull();
  await act(async () =>
    root.render(
      <AccountCard
        thLevel={16}
        name="Echo"
        meta={["TH16"]}
        detail="Reason"
        values="3 Attacks"
        status={{ tone: "bad", content: "Staff correction" }}
      />,
    ),
  );
  expect(host.querySelector(".account-card-detail")?.textContent).toBe(
    "Reason",
  );
  expect(
    host.querySelector(".player-current-clan.is-elsewhere")?.textContent,
  ).toBe("Staff correction");
  expect(host.querySelector(".account-card-value-separator")?.textContent).toBe(
    " · ",
  );
});

it("shows the chip fade only while local row content remains to the right", async () => {
  let contentWidth = 500;
  const { default: StrikeActivityRoster } = await import(
    "./StrikeActivityRoster"
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("strike-activity-tabs") ? 200 : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("strike-activity-tabs") ? contentWidth : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            accounts: [account()],
            clans: [{ tag: "#PQQ", name: "Local Alpha" }],
            activity_as_of: "Activity as of 03:21 UTC",
          }),
        ),
    ),
  );
  await act(async () =>
    root.render(<StrikeActivityRoster state="?view=all" onChoose={choose} />),
  );
  const row = host.querySelector<HTMLElement>(".strike-activity-tabs")!;
  const wrapper = host.querySelector(".strike-activity-chips")!;
  expect(wrapper.classList.contains("has-more")).toBe(true);
  row.scrollLeft = 300;
  await act(async () => {
    row.dispatchEvent(new Event("scroll"));
  });
  expect(wrapper.classList.contains("has-more")).toBe(false);
  row.scrollLeft = 20;
  await act(async () => {
    row.dispatchEvent(new Event("scroll"));
  });
  expect(wrapper.classList.contains("has-more")).toBe(true);
  const lines = host.querySelectorAll(
    ".strike-activity-rule-line, .strike-activity-freshness",
  );
  expect(lines).toHaveLength(2);
  expect(lines[0].querySelector(".strike-activity-summary")?.textContent).toBe(
    "Showing 1 of 1",
  );
  expect(lines[0].querySelector(".strike-activity-as-of")).toBeNull();
  expect(lines[1].querySelector(".strike-activity-as-of")?.textContent).toBe(
    "Activity as of 03:21 UTC",
  );
  expect(
    lines[1].querySelector(".strike-activity-tracking-slot"),
  ).not.toBeNull();
  contentWidth = 200;
  await act(async () =>
    root.render(
      <StrikeActivityRoster state="?view=all&q=unmatched" onChoose={choose} />,
    ),
  );
  expect(wrapper.classList.contains("has-more")).toBe(false);
  expect(fetch).toHaveBeenCalledTimes(1);
});
