// @vitest-environment happy-dom
import { act, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ParticipationAccount } from "./participation";

const fixture = vi.hoisted(() => ({
  api: vi.fn(),
  nextInstance: 0,
  unmounted: [] as string[],
}));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: fixture.api,
}));
vi.mock("./ParticipationRecord", () => ({
  default: ({
    account,
    onDirty,
    open,
    onOpen,
  }: {
    account: ParticipationAccount;
    onDirty: (tag: string, dirty: boolean) => void;
    open: boolean;
    onOpen: () => void;
  }) => {
    const [draft, setDraft] = useState("");
    const [busy, setBusy] = useState(false);
    const instance = useRef(++fixture.nextInstance);
    // Match the real record's cleanup contract: unmounting clears parent dirty state.
    useEffect(() => {
      onDirty(account.tag, !!draft || busy);
      return () => onDirty(account.tag, false);
    }, [account.tag, draft, busy, onDirty]);
    useEffect(
      () => () => {
        fixture.unmounted.push(account.tag);
      },
      [account.tag],
    );
    return (
      <section
        data-record={account.tag}
        data-instance={instance.current}
        data-open={open}
      >
        <span>{account.player_name}</span>
        <input
          aria-label={`Draft for ${account.player_name}`}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button onClick={() => setBusy(!busy)}>
          {busy ? "Finish pending" : "Start pending"} {account.player_name}
        </button>
        <button onClick={onOpen}>Open {account.player_name}</button>
      </section>
    );
  },
}));
import ParticipationWorkspace from "./ParticipationWorkspace";

const accounts: ParticipationAccount[] = Array.from(
  { length: 500 },
  (_, i) => ({
    tag: `#P${i}`,
    player_name: `Participant ${String(i).padStart(3, "0")}`,
    pool: "main",
    town_hall: 19,
    assigned_clan_tag: "#PQQ",
    assigned_clan_name: "Fixture clan",
    attacks: i % 8,
    stars: i % 21,
    notes: "",
    revision: 1,
    updated_by: null,
    updated_at: null,
    in_latest_publication: true,
    source_complete: true,
  }),
);
const data = { accounts, publication_version: 1 };
const original = JSON.stringify(data);
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const mounted = () => host.querySelectorAll(".participation-list > li");
const visible = () =>
  host.querySelectorAll(".participation-list > li:not([hidden])");
const record = (tag: string) =>
  host.querySelector<HTMLElement>(`[data-record="${tag}"]`)!;
const named = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
const render = (props: { urlState?: string; seasonId?: string } = {}) =>
  act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
          { id: 2, label: "December", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
        {...props}
      />,
    ),
  );
const change = (input: HTMLInputElement | HTMLSelectElement, value: string) =>
  act(async () => {
    const proto =
      input.tagName === "SELECT"
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(input, value);
    input.dispatchEvent(
      new Event(input.tagName === "SELECT" ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
const search = (value: string) =>
  change(
    host.querySelector<HTMLInputElement>(
      '.participation-toolbar input[type="search"]',
    )!,
    value,
  );
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  localStorage.clear();
  sessionStorage.clear();
  fixture.unmounted.length = 0;
  fixture.api.mockReset().mockResolvedValue(data);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await render();
});
afterEach(async () => {
  expect(JSON.stringify(data)).toBe(original);
  expect(
    fixture.api.mock.calls.every((call) => !call[1] || call[1] === "GET"),
  ).toBe(true);
  await act(async () => root.unmount());
  host.remove();
});

it("mounts50, adds50, and searches and summarizes all500 without writes or revision changes", async () => {
  expect(mounted()).toHaveLength(50);
  expect(visible()).toHaveLength(50);
  expect(
    host.querySelector(".participation-list-heading")?.textContent,
  ).toContain("500 players");
  await act(async () => named("Load more").click());
  expect(mounted()).toHaveLength(100);
  expect(visible()).toHaveLength(100);
  await search("Participant 499");
  expect(mounted()).toHaveLength(1);
  expect(visible()).toHaveLength(1);
  expect(record("#P499").textContent).toContain("Participant 499");
  expect(
    host.querySelector(".participation-list-heading")?.textContent,
  ).toContain("1 of 500 players");
  await search("");
  expect(mounted()).toHaveLength(50);
  expect(accounts.every((a) => a.revision === 1)).toBe(true);
});

it("keeps a hidden dirty component and its draft through filters without onDirty unmount cleanup", async () => {
  const before = record("#P0"),
    instance = before.dataset.instance;
  await change(before.querySelector("input")!, "Unsaved draft");
  await search("Participant 499");
  expect(mounted()).toHaveLength(2);
  expect(visible()).toHaveLength(1);
  expect(record("#P0")).toBe(before);
  expect(record("#P0").dataset.instance).toBe(instance);
  expect(record("#P0").closest("li")!.hidden).toBe(true);
  expect(record("#P0").querySelector("input")!.value).toBe("Unsaved draft");
  expect(fixture.unmounted).not.toContain("#P0");
  await search("");
  expect(record("#P0")).toBe(before);
  expect(record("#P0").querySelector("input")!.value).toBe("Unsaved draft");
});

it("keeps a busy off-filter component until its pending state finishes", async () => {
  const before = record("#P0");
  await act(async () => named("Start pending Participant 000").click());
  await search("Participant 499");
  expect(record("#P0")).toBe(before);
  expect(mounted()).toHaveLength(2);
  expect(fixture.unmounted).not.toContain("#P0");
  await act(async () => named("Finish pending Participant 000").click());
  expect(mounted()).toHaveLength(1);
  expect(fixture.unmounted).toContain("#P0");
});

it("pins the active editor during external URL filter changes, including the incumbent hidden state", async () => {
  const before = record("#P0");
  await act(async () => named("Open Participant 000").click());
  await render({ urlState: "pool=lazy" });
  expect(record("#P0")).toBe(before);
  expect(record("#P0").dataset.open).toBe("true");
  expect(record("#P0").closest("li")!.hidden).toBe(true);
  expect(fixture.unmounted).not.toContain("#P0");
});

it("resets50 for sort, clan, outcome, pool and season and never restores an old large limit", async () => {
  await act(async () => named("Load more").click());
  expect(visible()).toHaveLength(100);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Sort: Name A–Z"]')!
      .click(),
  );
  await act(async () =>
    [
      ...document.querySelectorAll<HTMLButtonElement>(
        ".participation-sort-options button",
      ),
    ]
      .find((button) => button.textContent === "Stars high to low")!
      .click(),
  );
  expect(visible()).toHaveLength(50);
  await act(async () => named("Load more").click());
  await render({ urlState: "clan=%23PQQ" });
  expect(visible()).toHaveLength(50);
  await act(async () => named("Load more").click());
  await render({ urlState: "outcome=partial" });
  expect(visible()).toHaveLength(50);
  await act(async () => named("Load more").click());
  await render({ urlState: "pool=lazy" });
  expect(visible()).toHaveLength(0);
  await render({ urlState: "pool=main" });
  expect(visible()).toHaveLength(50);
  await act(async () => named("Load more").click());
  await render({ seasonId: "2" });
  expect(visible()).toHaveLength(50);
});
