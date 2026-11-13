// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import type { Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", async (original) => ({
  ...(await original<object>()),
  useDashboardPermission: () => true,
}));
// Real caller options/value are exercised; native menu mechanics are separately tested.
vi.mock("./rosterUi/Menu", () => ({
  default: ({
    label,
    value,
    options,
    onValueChange,
    disabled,
    "aria-label": ariaLabel,
  }: {
    label: string;
    value: string;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
    disabled?: boolean;
    "aria-label"?: string;
  }) => (
    <select
      data-picker={label}
      aria-label={ariaLabel || label}
      value={value}
      disabled={disabled}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {options.map((row) => (
        <option key={row.value} value={row.value}>
          {row.label}
        </option>
      ))}
    </select>
  ),
}));
import BonusWorkspace from "./BonusWorkspace";
import ParticipationWorkspace from "./ParticipationWorkspace";
import RosterHeader from "./RosterHeader";
import PublicationWorkspace from "./PublicationWorkspace";
import SeasonsPage from "./SeasonsPage";
import ExportWorkspace from "./ExportWorkspace";
import MemberSeasonLine from "./MemberSeasonLine";
import StaffOverview from "./StaffOverview";
const seasons: Season[] = [
  { id: 4, label: "2026-10", status: "archived", signup_open: false },
  { id: 3, label: "2026-09", status: "archived", signup_open: false },
  { id: 2, label: "2026-08", status: "archived", signup_open: false },
  {
    id: 1,
    label: "November 2026",
    cwl_month: "2026-11",
    status: "draft",
    signup_open: true,
  },
];
const expected = [
  "November 2026",
  "October 2026",
  "September 2026",
  "August 2026",
];
let host: HTMLDivElement, root: Root;
const change = vi.fn(),
  noop = () => {};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset().mockImplementation(() => new Promise(() => {}));
  change.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  history.replaceState({}, "", "/cwl/results?season=1");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
const mount = async (node: ReactNode) => {
  await act(async () => root.render(node));
};
const common = { seasonId: "1", seasons, onSeasonChange: change };
const variants: { name: string; render: () => ReactNode }[] = [
  { name: "bonus steps", render: () => <BonusWorkspace {...common} /> },
  {
    name: "participation list",
    render: () => <ParticipationWorkspace {...common} />,
  },
  {
    name: "Build roster",
    render: () => (
      <RosterHeader
        {...common}
        roster={null}
        pool="all"
        canRoster
        canSignups
        canPublish
        uiLocked={false}
        archived={false}
        onFillSignupSpot={() => false}
        onSignupDetails={() => false}
        onRefresh={noop}
        onAutoPlace={noop}
        onStatusFilter={noop}
        onAccessError={noop}
      />
    ),
  },
  {
    name: "Finalize roster",
    render: () => (
      <PublicationWorkspace
        {...common}
        step="review"
        onStepChange={noop}
        onFix={noop}
      />
    ),
  },
  {
    name: "Seasons",
    render: () => (
      <SeasonsPage
        {...common}
        memberSeason={{ season_id: 1, revision: 1 }}
        onRefresh={async () => {}}
        onBusy={noop}
      />
    ),
  },
  { name: "Exports", render: () => <ExportWorkspace {...common} /> },
];
it.each(variants)(
  "$name formats/orders without changing selected id, URL or writing",
  async ({ render }) => {
    await mount(render());
    const picker = host.querySelector<HTMLSelectElement>(
      'select[name="season"],select[data-picker="Season"]',
    )!;
    expect(picker).not.toBeNull();
    expect(
      [...picker.options].filter((row) => row.value).map((row) => row.text),
    ).toEqual(expected);
    expect(picker.value).toBe("1");
    expect(picker.selectedOptions[0].text).toBe("November 2026");
    expect(picker.textContent).not.toMatch(/2026-|Archived/);
    expect(location.pathname + location.search).toBe("/cwl/results?season=1");
    expect(change).not.toHaveBeenCalled();
    expect(
      api.mock.calls.every(
        (call) => call[1] === undefined || call[1] === "GET",
      ),
    ).toBe(true);
  },
);
it("formats the roster's accessible selected label", async () => {
  await mount(
    <RosterHeader
      {...common}
      seasonId="4"
      roster={null}
      pool="all"
      canRoster
      canSignups
      canPublish
      uiLocked={false}
      archived
      onFillSignupSpot={() => false}
      onSignupDetails={() => false}
      onRefresh={noop}
      onAutoPlace={noop}
      onStatusFilter={noop}
      onAccessError={noop}
    />,
  );
  expect(
    host.querySelector('[data-picker="Season"]')?.getAttribute("aria-label"),
  ).toBe("Season: October 2026");
});
it("formats member text without changing its open state", async () => {
  await mount(
    <MemberSeasonLine
      season={{ ...seasons[0], signup_open: true, status: "draft" }}
    />,
  );
  expect(host.textContent).toContain("October 2026 · Signups open");
  expect(host.textContent).not.toContain("2026-");
});
it("formats staff text and preserves its destination id", async () => {
  api.mockResolvedValue({
    checked_at: 1,
    seasons: [{ id: 4, label: "2026-10", signed_up: 0, unplaced: 0 }],
    tickets: null,
    failures_count: 0,
    failures: [],
    warnings: [],
    areas: ["roster"],
  });
  await mount(<StaffOverview onNavigate={change} />);
  expect(host.textContent).toContain("October 2026");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((row) => row.textContent === "Open roster ")!
      .click(),
  );
  expect(change).toHaveBeenCalledWith("roster", "4");
});
