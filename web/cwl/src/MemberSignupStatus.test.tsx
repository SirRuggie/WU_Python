// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MemberSignupStatus, {
  memberDateLines,
  relativeMinutes,
} from "./MemberSignupStatus";
import SidebarNavigation from "./SidebarNavigation";
import { MemberStepStrip } from "./CwlStepStrip";
import { memberTarget, loginPath } from "./memberLinks";
import type { Season } from "./api";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-29T12:00:00Z"));
});
afterEach(() => vi.useRealTimers());

const accounts = ["Aurora", "Ace", "Birch", "Cedar", "Dawn"].map((name, i) => ({
  name,
  tag: `#P2Y2Y2Y${i}`,
}));
it("rounds relative days without pluralizing one day", () => {
  expect(relativeMinutes(1440 * 60000, 0)).toBe("in 1 day");
  expect(relativeMinutes(1441 * 60000, 0)).toBe("in 1 day");
  expect(relativeMinutes(2880 * 60000, 0)).toBe("in 2 days");
  expect(relativeMinutes(40 * 60000, 0)).toBe("in 40 min");
});
it("keeps signup navigation when empty and account links are unavailable", async () => {
  await render({ signups: [], accounts: null });
  expect(host.textContent).toContain("Sign up for CWL ›");
  await render({
    signups: [],
    accounts: null,
    season: { ...season, signup_open: false },
  });
  expect(host.textContent).toContain("Signups are closed.");
  expect(host.textContent).not.toContain("Sign up for CWL ›");
});
const signups = accounts.slice(0, 2).map((a, i) => ({
  tag: a.tag,
  player_name: a.name,
  pool: i ? "lazy" : "main",
  assigned_clan_tag: null as string | null,
}));
const season = {
  id: 1,
  label: "November CWL",
  status: "draft",
  signup_open: true,
  signup_deadline: "2026-10-30T21:00:00Z",
  placements_by: "2026-10-31T21:00:00Z",
} as Season;
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
const render = async (props = {}) => {
  const onChange = vi.fn(),
    onRemaining = vi.fn();
  await act(async () =>
    root.render(
      <MemberSignupStatus
        signups={signups}
        accounts={accounts}
        season={season}
        onChange={onChange}
        onRemaining={onRemaining}
        {...props}
      />,
    ),
  );
  return { onChange, onRemaining };
};
const click = async (text: string) => {
  const button = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === text,
  )!;
  expect(button).toBeTruthy();
  await act(async () => button.click());
};

it("shows a red action card without remaining account names only while signups are open", async () => {
  const many = Array.from({ length: 44 }, (_, i) => ({
    tag: `remaining-${i}`,
    name: `Reserve ${i + 1}`,
  }));
  const callbacks = await render({ accounts: many });
  const card = host.querySelector(".member-signup-remaining")!;
  expect(card.tagName).toBe("SECTION");
  expect(card.previousElementSibling?.className).toBe("member-signup-success");
  expect(card.textContent).toContain("44 accounts not signed up yet");
  expect(card.textContent).toContain("Sign up 44 more accounts ›");
  expect(card.textContent).not.toContain("Reserve");
  expect(card.querySelector("svg[aria-hidden=true]")).not.toBeNull();
  expect(card.querySelector(".member-signup-date")?.textContent).toBe(
    host.querySelector(".member-signup-success .member-signup-date")
      ?.textContent,
  );
  await click("Sign up 44 more accounts ›");
  expect(callbacks.onRemaining).toHaveBeenCalledOnce();

  await render({ accounts: many, season: { ...season, signup_open: false } });
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  expect(host.textContent).not.toContain("weren't signed up");
});

it("reassures two of five and offers the remaining accounts in a separate card", async () => {
  const callbacks = await render();
  expect(host.textContent).toContain("✓ You're signed up · 2 of 5 accounts");
  expect(host.textContent).toContain("Aurora · Main CWL");
  expect(host.textContent).toContain("Ace · Lazy CWL");
  expect(host.querySelector(".member-signup-remaining")?.textContent).toContain(
    "3 accounts not signed up yet",
  );
  expect(
    host.querySelector(".member-signup-remaining")?.textContent,
  ).not.toContain("Birch");
  expect(host.querySelector("[role=alert]")).toBeNull();
  expect(callbacks.onChange).not.toHaveBeenCalled();
  await click("Change signups ›");
  expect(callbacks.onChange).toHaveBeenCalledOnce();
  await click("Sign up 3 more accounts ›");
  expect(callbacks.onRemaining).toHaveBeenCalledOnce();
});
it("uses singular copy and omits the deadline when unavailable", async () => {
  await render({
    signups: signups.slice(0, 1),
    accounts: accounts.slice(0, 2),
    season: { ...season, signup_deadline: null },
  });
  const card = host.querySelector(".member-signup-remaining")!;
  expect(card.textContent).toContain("1 account not signed up yet");
  expect(card.textContent).toContain("Sign up 1 more account ›");
  expect(card.querySelector(".member-signup-date")).toBeNull();
});
it("closed and hidden remain reassuring, all signed counts correctly, empty never claims success", async () => {
  await render({ season: { ...season, signup_open: false }, published: false });
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  expect(host.textContent).not.toContain("weren't signed up");
  expect(host.textContent).not.toContain("hidden");
  expect(host.querySelector("button")).toBeNull();
  await render({ accounts: accounts.slice(0, 2) });
  expect(host.textContent).toContain("all 2 accounts");
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  await render({
    signups: signups.slice(0, 1),
    accounts: accounts.slice(0, 1),
  });
  expect(host.textContent).toContain("all 1 account");
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  await render({ signups: [], accounts: accounts.slice(0, 3) });
  expect(host.textContent).toContain("You haven't signed up any accounts yet.");
  expect(host.querySelector(".member-signup-success")).toBeNull();
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  expect(host.querySelector(".member-signup-empty")?.textContent).toContain(
    "Sign up for CWL ›",
  );
});
it("partly placed lists only waiting names and does not invent totals when links are unavailable", async () => {
  await render({
    published: true,
    signups: [{ ...signups[0], assigned_clan_tag: "#P2222222" }, signups[1]],
  });
  expect(host.textContent).toContain("waiting for your clan");
  expect(host.querySelector("ul")?.textContent).toBe("Ace · Lazy CWL");
  await render({ accounts: null });
  expect(host.textContent).toContain("You're signed up · 2 accounts");
  expect(host.textContent).not.toContain("not signed up");
});
it("local dates, minute-only countdown, late and null guidance", async () => {
  const now = Date.parse("2026-10-28T21:00:00Z");
  expect(memberDateLines(season, false, now)[0]).toContain("in 2 days");
  expect(memberDateLines(season, false, now)[0]).toContain(
    new Date(season.signup_deadline!).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }),
  );
  const closed = { ...season, signup_open: false };
  expect(
    memberDateLines(closed, false, Date.parse("2026-10-31T03:00:00Z"))[0],
  ).toContain("in 18 h");
  expect(
    memberDateLines(closed, false, Date.parse("2026-11-01T00:00:00Z")),
  ).toEqual(["Taking a little longer than usual · check back soon"]);
  expect(
    memberDateLines({ ...season, placements_by: null }, false, now),
  ).toEqual([]);
  expect(memberDateLines(season, true, now)).toEqual([]);
  vi.useFakeTimers();
  vi.setSystemTime(Date.parse(season.placements_by!) - 40 * 60000);
  await render({ season: closed });
  expect(host.textContent).toContain("in 40 min");
  await act(async () => vi.advanceTimersByTime(60000));
  expect(host.textContent).toContain("in 39 min");
});
it("sidebar is ordered, expanded initially and remembers collapse even on a member page", async () => {
  localStorage.setItem(
    "wu-navigation-v2:member",
    JSON.stringify({ "my-dashboard": true, "my-cwl": false, clans: true }),
  );
  const onSignup = vi.fn();
  const props = {
    userId: "member",
    view: "home" as const,
    canEdit: false,
    isOwner: false,
    onNavigate: vi.fn(),
    onSignup,
    signupPanel: "saved" as const,
  };
  await act(async () => root.render(<SidebarNavigation {...props} />));
  const nav = host.querySelector("#navigation-my-cwl")!;
  expect(nav.hasAttribute("hidden")).toBe(false);
  const stored = JSON.parse(localStorage.getItem("wu-navigation-v3:member")!);
  expect(stored.clans).toBe(true);
  expect(stored["my-cwl"]).toBeUndefined();
  expect([...nav.querySelectorAll("button")].map((b) => b.textContent)).toEqual(
    ["Sign up", "My signups", "My clan assignments"],
  );
  await click("My signups");
  expect(onSignup).toHaveBeenCalledWith("saved");
  const toggle = host.querySelector<HTMLButtonElement>(
    '[aria-controls="navigation-my-cwl"]',
  )!;
  await act(async () => toggle.click());
  expect(nav.hasAttribute("hidden")).toBe(true);
  await act(async () => root.render(<div />));
  await act(async () => root.render(<SidebarNavigation {...props} />));
  expect(host.querySelector("#navigation-my-cwl")?.hasAttribute("hidden")).toBe(
    true,
  );
});
it("step strip and canonical plus legacy saved URLs keep the same destination", async () => {
  const onNavigate = vi.fn();
  await act(async () =>
    root.render(<MemberStepStrip step="saved" onNavigate={onNavigate} />),
  );
  expect(host.querySelector("[aria-current=step]")?.textContent).toBe(
    "My signups",
  );
  await click("My clan");
  expect(onNavigate).toHaveBeenCalledWith("assignments");
  for (const [path, query] of [
    ["/my-signups", ""],
    ["/signup", "?signupPanel=saved"],
    ["/", "?view=signup&signupPanel=saved"],
  ]) {
    expect(memberTarget(query, path).signupPanel).toBe("saved");
    expect(loginPath(query, false, path)).toContain("view=my-signups");
  }
});

it("remaining card keeps the deadline without a placement estimate or on a published roster", async () => {
  await render({ season: { ...season, placements_by: null }, published: true });
  expect(
    host.querySelector(".member-signup-remaining .member-signup-date")
      ?.textContent,
  ).toContain("Signups close");
  expect(
    host.querySelector(".member-signup-success .member-signup-date"),
  ).toBeNull();
});

it("zero signups uses only the grey signup action, and hides it when closed", async () => {
  const callbacks = await render({ signups: [] });
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  expect(host.querySelector(".member-signup-empty button")?.textContent).toBe(
    "Sign up for CWL ›",
  );
  await click("Sign up for CWL ›");
  expect(callbacks.onRemaining).toHaveBeenCalledOnce();
  expect(callbacks.onChange).not.toHaveBeenCalled();
  await render({ signups: [], season: { ...season, signup_open: false } });
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
  expect(host.querySelector("button")).toBeNull();
  expect(host.textContent).toContain("Signups are closed.");
});
