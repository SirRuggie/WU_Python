// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikesWorkspace, { type Entry } from "./StrikesWorkspace";
import StrikeSettingsEditor, {
  type StrikeSettings,
} from "./StrikeSettingsEditor";
import StrikeHistoryRow from "./StrikeHistoryRow";
import { ApiError } from "./api";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
vi.mock("./StrikeTrackingStatus", () => ({ default: () => null }));
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  history.replaceState({}, "", "/strikes");
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  sessionStorage.clear();
  transport.mockReset();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.stubGlobal(
    "confirm",
    vi.fn(() => {
      throw Error("Native confirm forbidden");
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const render = async (node: React.ReactNode) => {
  await act(async () => root.render(node));
};
const settle = async () => {
  await act(async () => vi.advanceTimersByTimeAsync(300));
};
const button = (text: string, scope: ParentNode = document) => {
  const b = [...scope.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === text,
  );
  expect(b, text).toBeTruthy();
  return b!;
};
const click = async (text: string, scope?: ParentNode) => {
  await act(async () => button(text, scope).click());
};
const input = async (selector: string, value: string) => {
  const node = host.querySelector<HTMLInputElement>(selector)!;
  expect(node).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const countText = (element: Element | null) => {
  const walker = document.createTreeWalker(element!, NodeFilter.SHOW_TEXT);
  const parts: string[] = [];
  while (walker.nextNode()) parts.push(walker.currentNode.textContent || "");
  return parts.join(" ").replace(/\s+/g, " ").trim();
};
const settings: StrikeSettings = {
  revision: 8,
  strike_limit: 7,
  leaves: [],
  excluded_roles: [{ id: "9", name: "Old integration", managed: true }],
  roles: [
    { id: "3", name: "Captain", position: 30, color: 0xffaa00 },
    { id: "2", name: "Helper bot", managed: true },
    { id: "1", name: "External-looking name", managed: false, position: 1 },
  ],
};
function SettingsFixture() {
  const [value, setValue] = useState(settings);
  return (
    <StrikeSettingsEditor
      settings={value}
      onSaved={setValue}
      onDirty={() => {}}
      onBusy={() => {}}
    />
  );
}
it("preserves server role order, hides only managed additions, and retains a conflicting limit/role draft until confirmed reload", async () => {
  transport.mockRejectedValueOnce(new ApiError("Conflict", 409));
  await render(<SettingsFixture />);
  const options = host.querySelector('[aria-label="Available exempt roles"]')!;
  expect(options.textContent).toContain("External-looking name");
  expect(options.textContent).not.toContain("Helper bot");
  expect([...options.querySelectorAll("button")].map((b) => b.title)).toEqual([
    "3",
    "1",
  ]);
  expect(host.textContent).toContain("Old integration");
  await input('[placeholder="Search role names"]', "Captain");
  expect(options.textContent).not.toContain("External-looking");
  await act(async () =>
    options.querySelector<HTMLButtonElement>("button")!.click(),
  );
  await input('input[type="number"]', "11");
  await click("Save settings");
  expect(transport).toHaveBeenCalledWith("/strikes/settings/roles", "PUT", {
    revision: 8,
    role_ids: ["9", "3"],
    strike_limit: 11,
  });
  expect(host.textContent).toContain("Changed by someone else · Reload");
  expect(
    host.querySelector<HTMLInputElement>('input[type="number"]')!.value,
  ).toBe("11");
  expect(button("Save settings").disabled).toBe(true);
  await click("Reload");
  await click("Keep editing");
  expect(host.textContent).toContain("Captain");
  transport.mockResolvedValueOnce({
    ...settings,
    revision: 10,
    strike_limit: 12,
  });
  await click("Reload");
  await click("Reload", document.querySelector("dialog")!);
  expect(
    host.querySelector<HTMLInputElement>('input[type="number"]')!.value,
  ).toBe("12");
  expect(host.textContent).not.toContain("Changed by someone else");
});
it("uses its successful revision receipt for the next save without a racing settings read", async () => {
  transport
    .mockResolvedValueOnce({
      revision: 9,
      strike_limit: 10,
    })
    .mockResolvedValueOnce({
      revision: 10,
      strike_limit: 11,
    });
  await render(<SettingsFixture />);
  await input('input[type="number"]', "10");
  await click("Save settings");
  expect(button("Save settings").disabled).toBe(true);
  await input('input[type="number"]', "11");
  await click("Save settings");
  expect(transport.mock.calls[1][2].revision).toBe(9);
  expect(transport.mock.calls).toHaveLength(2);
});
it("loads the family once, filters locally and clears protected data on authorization loss", async () => {
  transport.mockResolvedValue({
    clans: [],
    accounts: [
      {
        player_tag: "#P2Y",
        player_name: "Aspen",
        active_strikes: 7,
        total_strikes: 28,
        status: "risk",
        quiet_days: null,
        marked_for_replacement: true,
      },
    ],
  });
  await render(
    <StrikesWorkspace
      permissions={["strikes_remove"]}
      isOwner={false}
      userId="1"
    />,
  );
  await settle();
  expect(host.textContent).toContain("1 at risk · 0 watch · 0 active");
  expect(host.textContent).toContain("Aspen");
  await input('input[type="search"]', "No match");
  await settle();
  expect(host.textContent).not.toContain("Aspen");
  expect(
    transport.mock.calls.filter((call) =>
      String(call[0]).startsWith("/strikes/accounts"),
    ),
  ).toHaveLength(1);
  await act(async () =>
    window.dispatchEvent(new Event("dashboard-access-changed")),
  );
  expect(host.textContent).not.toContain("Aspen");
});
it.each([
  ["active", "strike", "Active"],
  ["expired", "strike", "Expired"],
  ["removed", "strike", "Removed"],
  ["recorded", "miss", "One attack missed (no strike)"],
  ["mismatch", "mismatch", "Mismatch war (no strike)"],
  ["recorded", "no_attack", "No-attack war (no strike)"],
  ["recorded", "cwl", "CWL miss (no strike)"],
  ["exempt", "strike", "Exempt (no strike)"],
] as const)(
  "shows %s / %s status with an icon and no repeated account identity",
  async (status, kind, text) => {
    const item: Entry = {
      id: "row1",
      player_tag: "#P2Y",
      player_name: "Aspen",
      kind,
      status,
      source: "war",
      war_end: "2026-10-01T00:00:00Z",
      expires_at: new Date(Date.now() + 9 * 86400000).toISOString(),
      reason: "<script>external text</script>",
      opponent_name: "Opponent",
    };
    await render(
      <StrikeHistoryRow
        item={item}
        showIdentity={false}
        canRemove={status === "active"}
        removing={false}
        onRemove={() => {}}
      />,
    );
    expect(host.textContent).toContain(text);
    expect(
      host.querySelector(".strike-row-more")?.getAttribute("aria-label"),
    ).toBe(
      `Details and actions for ${new Date(item.war_end!).toLocaleDateString(undefined, { month: "numeric", day: "numeric" })} vs Opponent`,
    );
    expect(host.querySelector("svg")).not.toBeNull();
    expect(host.textContent).not.toContain("Aspen");
    expect(host.textContent).not.toContain("#P2Y");
    expect(host.querySelector("script")).toBeNull();
    if (status === "active") {
      expect(host.textContent).toContain("expires in 9 days");
      expect(host.textContent).not.toContain("Remove strike");
      await act(async () =>
        host.querySelector<HTMLButtonElement>(".strike-row-more")!.click(),
      );
      expect(
        host.querySelector(`time[datetime="${item.expires_at}"]`),
      ).not.toBeNull();
    }
  },
);
it.each([1, 2])(
  "shows selected import counts for %s strikes and reports actual duplicate/history outcomes",
  async (count) => {
    const entries = [
      ...Array(count).fill(true),
      ...Array(count).fill(false),
    ].map((will_strike, i) => ({
      key: `entry${i}`,
      player_tag: `#P${i}Y`,
      player_name: "Aspen",
      clan_name: "Oak",
      war_end: "2026-10-01T00:00:00Z",
      missed_attacks: will_strike ? 2 : 1,
      will_strike,
    }));
    sessionStorage.setItem(
      "wu:strikes:import:1",
      JSON.stringify({
        preview: {
          preview_id: "preview",
          wars_scanned: 3,
          complete_wars: count,
          incomplete_wars: count,
          deferred_count: count,
          entries,
          coverage: [
            {
              clan_name: "Oak",
              wars: count,
              skipped: count,
              deferred_accounts: count,
            },
          ],
        },
        excluded: [],
      }),
    );
    transport.mockImplementation(async (path: string) => {
      if (path === "/strikes/settings") return settings;
      if (path === "/strikes/import/apply")
        return {
          added_strikes: 1,
          deferred_count: count,
          duplicates: 1,
          history_only: 1,
          applied: 2,
          strikes: 1,
          skipped: 1,
        };
      return { entries: [], total: 0, clans: [] };
    });
    await render(<StrikesWorkspace permissions={[]} isOwner userId="1" />);
    await settle();
    expect(countText(host)).toMatch(
      new RegExp(
        "\\b" +
          `Adds ${count} ${count === 1 ? "strike" : "strikes"} to ${count} ${count === 1 ? "account" : "accounts"} · ${count} history-only ${count === 1 ? "record" : "records"}` +
          "\\b",
      ),
    );
    expect(countText(host)).toMatch(
      new RegExp(`\\b${count} ${count === 1 ? "needs" : "need"} review\\b`),
    );
    const disclosure = [...host.querySelectorAll("details")].find((node) =>
      node
        .querySelector("summary")
        ?.textContent?.includes("Review selected records"),
    )!;
    expect(disclosure.open).toBe(false);
    expect(countText(host)).toMatch(
      new RegExp(
        "\\b" + `${count} complete ${count === 1 ? "war" : "wars"}` + "\\b",
      ),
    );
    expect(countText(host)).toMatch(
      new RegExp(
        "\\b" + `${count} skipped ${count === 1 ? "war" : "wars"}` + "\\b",
      ),
    );
    expect(countText(host.querySelector(".strikes-coverage"))).toMatch(
      new RegExp("\\b" + `${count} ${count === 1 ? "war" : "wars"}` + "\\b"),
    );
    const boxes = [
      ...host.querySelectorAll<HTMLInputElement>(
        ".strikes-import-review input[type=checkbox]",
      ),
    ];
    await act(async () => boxes.slice(count).forEach((box) => box.click()));
    expect(countText(host)).toMatch(
      new RegExp(
        "\\b" +
          `${count} ${count === 1 ? "record" : "records"} selected` +
          "\\b",
      ),
    );

    expect(host.textContent).toContain("ClashKing (import)");
    await click(`Add ${count} ${count === 1 ? "strike" : "strikes"}`);
    expect(transport).toHaveBeenCalledWith("/strikes/import/apply", "POST", {
      preview_id: "preview",
      excluded_keys: entries.slice(count).map((entry) => entry.key),
    });
    expect(host.textContent).toContain(
      "1 strike added · 1 skipped as duplicate · 1 history-only",
    );
  },
);
it("paginates 28 detail records independently of the account page, retains filters across pages, and keeps removal behind row actions", async () => {
  transport.mockImplementation(async (path: string) => {
    if (path.startsWith("/strikes/accounts"))
      return {
        total: 300,
        strike_limit: 4,
        summary: { over_limit: 1, new_this_week: 1 },
        clans: [],
        accounts: [
          {
            player_tag: "#P2Y",
            player_name: "Unique Aspen",
            discord_id: "12345",
            current_clan_name: "Oak",
            active_strikes: 28,
            total_strikes: 28,
          },
        ],
      };
    if (path.startsWith("/strikes/overview")) {
      const offset = Number(
        new URL(path, "https://test").searchParams.get("offset"),
      );
      return {
        total: 28,
        clans: [],
        entries: Array.from({ length: offset ? 3 : 25 }, (_, i) => ({
          id: `row${offset + i}`,
          player_tag: "#P2Y",
          player_name: "Unique Aspen",
          kind: "strike",
          status: "active",
          source: "war",
          war_end: "2026-10-01T00:00:00Z",
          expires_at: "2026-12-01T00:00:00Z",
          reason: "Missed both attacks",
        })),
      };
    }
    if (path.endsWith("/remove")) return {};
    throw Error(path);
  });
  await render(
    <StrikesWorkspace
      permissions={["strikes_remove"]}
      isOwner={false}
      userId="1"
    />,
  );
  await settle();
  await act(async () =>
    host.querySelector<HTMLButtonElement>("[data-strike-player]")!.click(),
  );
  await settle();
  expect(host.querySelectorAll(".strike-compact-row")).toHaveLength(25);
  expect(host.textContent!.split("Unique Aspen")).toHaveLength(2);
  expect(host.textContent!.split("#P2Y")).toHaveLength(2);
  expect(host.textContent).toContain("12345");
  expect(host.textContent).not.toContain("Confirm removal");
  expect(
    [...host.querySelectorAll("select option")].map(
      (option) => option.textContent,
    ),
  ).toEqual(
    expect.arrayContaining([
      "Active strikes",
      "Expired strikes",
      "Removed strikes",
      "One attack missed (no strike)",
      "CWL miss (no strike)",
      "Exempt (no strike)",
      "Everything",
    ]),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".strike-row-more")!.click(),
  );
  await click("Remove strike");
  expect(
    host.querySelector<HTMLInputElement>(".strike-row-details form input")
      ?.maxLength,
  ).toBe(500);
  await click("Cancel");
  await click("Next");
  await settle();
  expect(host.querySelectorAll(".strike-compact-row")).toHaveLength(3);
  expect(transport.mock.calls.at(-1)![0]).toContain("offset=25");
  await click("← Players");
  await settle();
  expect(transport.mock.calls.at(-1)![0]).toBe(
    "/strikes/accounts?activity=true",
  );
});
it("finds wars beyond the first page and discloses incomplete upstream name search", async () => {
  transport.mockImplementation(async (path: string) =>
    path.startsWith("/strikes/wars")
      ? { wars: [], total: 70, name_search_incomplete: true }
      : { accounts: [], total: 0, clans: [] },
  );
  await render(
    <StrikesWorkspace
      permissions={["strikes_remove"]}
      isOwner={false}
      userId="1"
    />,
  );
  await settle();
  await click("Find war");
  await settle();
  expect(host.textContent).toContain("Some opponent names are unavailable");
  await click("Next wars");
  await settle();
  expect(transport.mock.calls.at(-1)![0]).toContain("offset=25");
  await input('[placeholder="Opponent, clan, or date"]', "Remote opponent");
  await settle();
  expect(transport.mock.calls.at(-1)![0]).toContain("query=Remote+opponent");
  expect(transport.mock.calls.at(-1)![0]).toContain("offset=0");
});
it("sends the selected leave revision and retains the date and accounts after a conflict", async () => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/strikes/settings") return settings;
    if (path.startsWith("/strikes/members?"))
      return { members: [{ id: "42", name: "Member", accounts: [] }] };
    if (path === "/strikes/members/42/accounts")
      return {
        member: {
          id: "42",
          name: "Member",
          accounts: [{ tag: "#P2Y", name: "Aspen" }],
        },
      };
    if (path === "/strikes/settings/leaves/42") return { revision: 6 };
    if (method === "POST") throw new ApiError("Conflict", 409);
    return { accounts: [], total: 0, clans: [] };
  });
  await render(<StrikesWorkspace permissions={[]} isOwner userId="1" />);
  await settle();
  await click("Leave");
  await settle();
  await input('[placeholder="Name or Discord ID"]', "Member");
  await settle();
  const select = host.querySelector<HTMLSelectElement>("select")!;
  await act(async () => {
    select.value = "42";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await input('input[type="date"]', "2027-01-01");
  await click("Save leave");
  expect(transport).toHaveBeenCalledWith("/strikes/settings/leaves", "POST", {
    discord_id: "42",
    player_tags: ["#P2Y"],
    resume_date: "2027-01-01",
    revision: 6,
  });
  expect(host.textContent).toContain("Changed by someone else · Reload");
  expect(
    host.querySelector<HTMLInputElement>('input[type="date"]')!.value,
  ).toBe("2027-01-01");
  expect(
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked,
  ).toBe(true);
  await click("Reload");
  await click("Keep editing");
  expect(
    host.querySelector<HTMLInputElement>('input[type="date"]')!.value,
  ).toBe("2027-01-01");
});

it("does not expose retired opponent exclusions", async () => {
  await render(<SettingsFixture />);
  expect(host.textContent).not.toContain("No-attack opponents");
  expect(host.querySelector("textarea")).toBeNull();
});
it.each([1, 6, 7, 8])(
  "shows the active strike count correctly at %s",
  async (count) => {
    transport.mockImplementation(async (path: string) =>
      path.startsWith("/strikes/accounts")
        ? {
            total: 1,
            strike_limit: 7,
            summary: { over_limit: count >= 7 ? 1 : 0, new_this_week: 0 },
            clans: [],
            accounts: [
              {
                player_tag: "#P2Y",
                player_name: "Aspen",
                active_strikes: count,
                total_strikes: count,
                over_limit: count >= 7,
              },
            ],
          }
        : { members: [] },
    );
    await render(
      <StrikesWorkspace
        permissions={["strikes_remove"]}
        isOwner={false}
        userId="1"
      />,
    );
    await settle();
    expect(host.querySelector(".strike-activity-count")?.textContent).toContain(
      `${count} ${count === 1 ? "strike" : "strikes"}`,
    );
  },
);

it.each([1, 3])(
  "renders %s account, record, and total strike labels",
  async (count) => {
    transport.mockImplementation(async (path: string) => {
      if (path.startsWith("/strikes/accounts"))
        return {
          total: count,
          strike_limit: 7,
          summary: { over_limit: 0, new_this_week: 0 },
          clans: [],
          accounts: [
            {
              player_tag: "#P2Y",
              player_name: "Count player",
              active_strikes: count,
              total_strikes: count,
            },
          ],
        };
      if (path.startsWith("/strikes/overview"))
        return { total: count, entries: [], clans: [] };
      return { members: [] };
    });
    await render(
      <StrikesWorkspace
        permissions={["strikes_remove"]}
        isOwner={false}
        userId="1"
      />,
    );
    await settle();
    expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(1);
    await act(async () =>
      host.querySelector<HTMLButtonElement>("[data-strike-player]")!.click(),
    );
    await settle();
    expect(countText(host.querySelector(".strikes-list-head"))).toMatch(
      new RegExp(
        "\\b" + `${count} ${count === 1 ? "record" : "records"}` + "\\b",
      ),
    );
    expect(countText(host)).toMatch(
      new RegExp(
        "\\b" +
          `${count} ${count === 1 ? "strike" : "strikes"} in the last 90 days` +
          "\\b",
      ),
    );
  },
);

it("returns from a routed account to the filtered roster when browser history clears the tag", async () => {
  const account = {
    player_tag: "#P2Y",
    player_name: "Routed Aspen",
    active_strikes: 0,
    total_strikes: 0,
    status: "active",
    quiet_days: null,
    marked_for_replacement: false,
  };
  transport.mockImplementation(async (path: string) =>
    path.startsWith("/strikes/accounts")
      ? { accounts: [account], clans: [] }
      : { entries: [], total: 0, clans: [] },
  );
  const memory = new Map<string, unknown>();
  const props = {
    permissions: ["strikes_remove"],
    isOwner: false,
    userId: "1",
    memory,
    activityState: "q=Routed",
    onAccountRoute: vi.fn(),
  };
  await render(<StrikesWorkspace {...props} targetTag="#P2Y" />);
  await settle();
  expect(host.querySelector(".strikes-detail-context")?.textContent).toContain(
    "Routed Aspen",
  );
  await render(<StrikesWorkspace {...props} targetTag="" />);
  await settle();
  expect(host.querySelector(".strikes-detail-context")).toBeNull();
  expect(
    host.querySelector<HTMLInputElement>('input[type="search"]')?.value,
  ).toBe("Routed");
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(1);
});
