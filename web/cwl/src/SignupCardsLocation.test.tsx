// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import MemberAssignments from "./MemberAssignments";
import SavedSignupStatus from "./SavedSignupStatus";
import type { Season, Signup, Account } from "./api";
const season = {
  id: 1,
  label: "November",
  signup_open: true,
  status: "draft",
  signup_deadline: "2099-10-30T00:00:00Z",
  placements_by: "2099-11-01T00:00:00Z",
} as Season;
const signups = [
  { tag: "#A", player_name: "Alpha", pool: "main" },
  { tag: "#B", player_name: "Beta", pool: "lazy" },
] as Signup[];
const accounts = [
  { tag: "#A", name: "Alpha" },
  { tag: "#B", name: "Beta" },
  { tag: "#C", name: "Reserve" },
] as Account[];
let root: Root, host: HTMLDivElement;
let published = false,
  partial = false,
  empty = false,
  unplaced = false;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  published = false;
  partial = false;
  empty = false;
  unplaced = false;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            published: published
              ? {
                  version: 1,
                  published_at: "2026-10-31T12:00:00Z",
                  joining_instructions: "",
                }
              : null,
            accounts: empty
              ? []
              : signups.map((s, i) => ({
                  ...s,
                  assigned_clan_tag:
                    published && !unplaced && (!partial || i === 0)
                      ? "#CLAN"
                      : null,
                  assigned_clan_name: "Fixture clan",
                })),
          }),
          { status: 200 },
        ),
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
it.each([false, true])(
  "assignments omits both signup cards, published=%s",
  async (value) => {
    published = value;
    await act(async () =>
      root.render(<MemberAssignments seasonId="1" seasons={[season]} />),
    );
    expect(host.querySelector(".member-signup-success")).toBeNull();
    expect(host.querySelector(".member-signup-remaining")).toBeNull();
    expect(host.textContent).toContain(
      value ? "Published clan assignments" : "Not published yet",
    );
    if (!value) {
      expect(host.textContent).toContain("You'll see your clan by");
      expect(host.textContent).toContain("2 accounts signed up");
      expect(host.querySelector('a[href="/my-signups"]')?.textContent).toBe(
        "My signups ›",
      );
    } else expect(host.querySelector(".member-open-clan")).not.toBeNull();
  },
);
it("preserves the empty assignment card", async () => {
  empty = true;
  await act(async () =>
    root.render(<MemberAssignments seasonId="1" seasons={[season]} />),
  );
  expect(host.textContent).toContain("You haven't signed up any accounts yet.");
  expect(host.textContent).not.toContain("Not published yet");
  expect(host.querySelector(".member-signup-refresh")?.textContent).toBe(
    "Refresh",
  );
});
it.each([true, false])(
  "saved summary lists every signup and gates remaining action, open=%s",
  async (open) => {
    published = true;
    partial = true;
    const remaining = vi.fn();
    await act(async () =>
      root.render(
        <SavedSignupStatus
          signups={signups}
          accounts={accounts}
          season={{ ...season, signup_open: open }}
          onRemaining={remaining}
          onAssignments={vi.fn()}
        />,
      ),
    );
    expect(host.querySelector(".member-signup-success ul")?.textContent).toBe(
      "Alpha · Main CWLBeta · Lazy CWL",
    );
    expect(host.textContent).toContain("✓ You're signed up · 2 of 3 accounts");
    expect(host.textContent).not.toContain("Change signups");
    expect(!!host.querySelector(".member-signup-remaining")).toBe(open);
    if (open) {
      expect(host.textContent).toContain("Signups close");
      await act(async () => host.querySelector("button")!.click());
      expect(remaining).toHaveBeenCalledOnce();
    } else expect(host.querySelector("button")).toBeNull();
  },
);
it("published ready line navigates to My clan without a write", async () => {
  published = true;
  const navigate = vi.fn();
  await act(async () =>
    root.render(
      <SavedSignupStatus
        signups={signups}
        accounts={accounts}
        season={season}
        onRemaining={vi.fn()}
        onAssignments={navigate}
      />,
    ),
  );
  const link = host.querySelector<HTMLAnchorElement>('a[href="/assignments"]')!;
  expect(link.textContent).toBe(
    "Your published clan assignments are ready to view.",
  );
  await act(async () => link.click());
  expect(navigate).toHaveBeenCalledOnce();
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(([, opts]) => !opts?.method || opts.method === "GET"),
  ).toBe(true);
});

it("does not advertise remaining totals while linked accounts are unavailable", async () => {
  await act(async () =>
    root.render(
      <SavedSignupStatus
        signups={signups}
        accounts={null}
        season={season}
        onRemaining={vi.fn()}
        onAssignments={vi.fn()}
      />,
    ),
  );
  expect(host.textContent).toContain("You're signed up · 2 accounts");
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
});
it("ignores a publication response after switching seasons", async () => {
  let resolveOld!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      String(url).includes("/seasons/1/")
        ? new Promise<Response>((resolve) => {
            resolveOld = resolve;
          })
        : Promise.resolve(
            new Response(
              JSON.stringify({ published: null, accounts: signups }),
            ),
          ),
    ),
  );
  const props = {
    signups,
    accounts,
    onRemaining: vi.fn(),
    onAssignments: vi.fn(),
  };
  await act(async () =>
    root.render(<SavedSignupStatus {...props} season={season} />),
  );
  await act(async () =>
    root.render(<SavedSignupStatus {...props} season={{ ...season, id: 2 }} />),
  );
  await act(async () =>
    resolveOld(
      new Response(
        JSON.stringify({
          published: { version: 1 },
          accounts: signups.map((row) => ({
            ...row,
            assigned_clan_tag: "#CLAN",
          })),
        }),
      ),
    ),
  );
  expect(host.querySelector('a[href="/assignments"]')).toBeNull();
  expect(host.textContent).toContain("Alpha · Main CWL");
});

it("keeps saved accounts and exposes a publication read failure without claiming published readiness", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ error: "Unavailable" }), {
          status: 503,
          headers: { "X-Read-Retries-Exhausted": "1" },
        }),
    ),
  );
  await act(async () =>
    root.render(
      <SavedSignupStatus
        signups={signups}
        accounts={null}
        season={season}
        onRemaining={vi.fn()}
        onAssignments={vi.fn()}
      />,
    ),
  );
  expect(host.textContent).toContain("Clan assignments could not be checked.");
  expect(host.textContent).toContain("Alpha · Main CWL");
  expect(host.textContent).not.toContain(
    "Your published clan assignments are ready",
  );
});

it("distinguishes a publication with no placements for this member", async () => {
  published = true;
  unplaced = true;
  await act(async () =>
    root.render(<MemberAssignments seasonId="1" seasons={[season]} />),
  );
  expect(host.textContent).toContain(
    "Published · your accounts are waiting for a clan",
  );
  expect(host.textContent).not.toContain("Not published yet");
  expect(host.textContent).toContain("2 accounts signed up");
  expect(host.querySelector('a[href="/my-signups"]')).not.toBeNull();
  expect(
    host.querySelector(".member-unpublished-status button")?.textContent,
  ).toBe("Refresh");
});
