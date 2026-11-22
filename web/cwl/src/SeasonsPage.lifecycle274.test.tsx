// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import SeasonsPage from "./SeasonsPage";
import type { Season } from "./api";
const { api, readiness } = vi.hoisted(() => ({
  api: vi.fn(),
  readiness: vi.fn(),
}));
vi.mock("./api", async (load) => ({ ...(await load<object>()), api }));
vi.mock("./seasonLifecycle", async (load) => ({
  ...(await load<object>()),
  loadLifecycleReadiness: readiness,
}));
vi.mock("./CwlPoolRoles", () => ({ default: () => null }));
const nov: Season = {
  id: 1,
  label: "2026-11",
  status: "draft",
  signup_open: false,
};
const dec: Season = {
  id: 2,
  label: "December 2026",
  status: "draft",
  signup_open: false,
};
async function mount({
  id = 2,
  open = false,
  published = false,
  blockers = [] as string[],
  allowed = true,
} = {}) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  readiness.mockResolvedValue({ published, blockers });
  const seasons = [nov, { ...dec, signup_open: open }];
  api.mockImplementation(async (path: string) =>
    path === "/seasons"
      ? { seasons, member_season: { season_id: id, revision: 4 } }
      : {
          signup_gate: {
            status: "held",
            season_id: 2,
            run_at: "2026-11-30T06:00:00Z",
          },
        },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: allowed, permissions: [] }}
      >
        <SeasonsPage
          seasonId="1"
          seasons={seasons}
          memberSeason={{ season_id: id, revision: 4 }}
          onRefresh={async () => {}}
          onSeasonChange={() => {}}
          onClans={() => {}}
          onBusy={() => {}}
        />
      </DashboardPermissions.Provider>,
    ),
  );
  return {
    host,
    cleanup: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}
const button = (text: string, scope: ParentNode = document) =>
  Array.from(scope.querySelectorAll("button")).find(
    (b) => b.textContent === text,
  )!;
it.each([false, true])(
  "member card ignores manually selected November; next signup action (%s)",
  async (open) => {
    const { host, cleanup } = await mount({ open });
    try {
      expect(host.querySelector(".card h2")?.textContent).toBe("December 2026");
      expect(host.textContent).not.toContain("Season selector");
      expect(
        button(open ? "Close signups" : "Open signups", host),
      ).toBeTruthy();
      expect(button("Lock November 2026", host)).toBeUndefined();
      expect(host.textContent).toContain("November 2026 · Not locked");
      if (!open)
        expect(host.textContent).toContain("will wait. Signups are closed.");
    } finally {
      await cleanup();
    }
  },
);
it("NULL fallback shows and opens newest season through existing confirmation", async () => {
  const { host, cleanup } = await mount({ id: null as unknown as number });
  try {
    expect(host.textContent).toContain("Not shown to members");
    await act(async () => button("Show and open signups", host).click());
    expect(document.querySelector("dialog")?.textContent).toContain(
      "Show it to members and open signups?",
    );
    expect(api.mock.calls.every((c) => !c[1])).toBe(true);
  } finally {
    await cleanup();
  }
});
it("missing member ID fails closed instead of guessing selected/newest", async () => {
  const { host, cleanup } = await mount({ id: 99 });
  try {
    expect(host.textContent).toContain("Member season unavailable");
    expect(button("Open signups", host)).toBeUndefined();
  } finally {
    await cleanup();
  }
});
it.each([false, true])(
  "Start label explains rollover and gold requires publication (%s)",
  async (published) => {
    const { host, cleanup } = await mount({ published });
    try {
      const start = button("Start January 2027", host);
      expect(start).toBeTruthy();
      expect(start.className.includes("primary")).toBe(published);
      expect(host.textContent).toContain(
        "Members see January 2027. December 2026 stays saved.",
      );
    } finally {
      await cleanup();
    }
  },
);
it("Start dialog blocks unfinished bonuses with Finish these first", async () => {
  const { host, cleanup } = await mount({
    published: true,
    blockers: ["Fixture clan: bonuses"],
  });
  try {
    await act(async () => button("Start January 2027", host).click());
    const dialog = document.querySelector("dialog")!;
    expect(dialog.textContent).toContain("Finish these first");
    expect(button("Start January 2027", dialog).disabled).toBe(true);
  } finally {
    await cleanup();
  }
});
it("restricted staff cannot mutate lifecycle", async () => {
  const { host, cleanup } = await mount({ allowed: false });
  try {
    expect(button("Open signups", host)).toBeUndefined();
    expect(button("Start January 2027", host)).toBeUndefined();
  } finally {
    await cleanup();
  }
});

it.each([false, true])(
  "retains old Start context through lock failure, refresh and remount; explicit retry only locks old month (%s)",
  async (openNow) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    sessionStorage.clear();
    readiness.mockResolvedValue({ published: true, blockers: [] });
    let snapshot = {
      seasons: [nov, dec],
      member_season: { season_id: 1, revision: 4 },
    };
    let failLock = true;
    api
      .mockReset()
      .mockImplementation(
        async (
          path: string,
          method?: string,
          _body?: Record<string, unknown>,
        ) => {
          if (!method)
            return path === "/seasons" ? structuredClone(snapshot) : {};
          if (path === "/member-season")
            snapshot.member_season = { season_id: 2, revision: 5 };
          if (path === "/seasons/2")
            snapshot.seasons = snapshot.seasons.map((row) =>
              row.id === 2 ? { ...row, signup_open: true } : row,
            );
          if (path === "/seasons/1") {
            if (failLock) throw new Error("Lock failed");
            snapshot.seasons = snapshot.seasons.map((row) =>
              row.id === 1 ? { ...row, status: "archived" } : row,
            );
          }
          return {};
        },
      );
    function Fixture() {
      const [value, setValue] = useState(structuredClone(snapshot));
      return (
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <SeasonsPage
            actorId="staff-fixture"
            seasonId="1"
            seasons={value.seasons}
            memberSeason={value.member_season}
            onSeasonChange={() => {}}
            onRefresh={async () => setValue(structuredClone(snapshot))}
            onBusy={() => {}}
          />
        </DashboardPermissions.Provider>
      );
    }
    const host = document.createElement("div");
    document.body.append(host);
    let root = createRoot(host);
    const writes = () =>
      api.mock.calls
        .filter((call) => call[1])
        .map((call) => `${call[1]} ${call[0]}`);
    try {
      await act(async () => root.render(<Fixture />));
      await act(async () => button("Start December 2026", host).click());
      if (openNow)
        await act(async () =>
          document
            .querySelector<HTMLInputElement>("dialog input[type=checkbox]")!
            .click(),
        );
      const confirm = button(
        "Start December 2026",
        document.querySelector("dialog")!,
      );
      await act(async () => {
        confirm.click();
        confirm.click();
      });
      expect(host.textContent).toContain("Done:");
      expect(host.textContent).toContain("Not done: lock the previous month.");
      expect(button("Start January 2027", host).disabled).toBe(true);
      expect(button("Retry Start December 2026", host)).toBeTruthy();
      const before = writes();
      await act(async () => root.unmount());
      root = createRoot(host);
      await act(async () => root.render(<Fixture />));
      expect(writes()).toEqual(before);
      failLock = false;
      await act(async () => button("Retry Start December 2026", host).click());
      expect(
        document.querySelector<HTMLInputElement>("dialog input[type=checkbox]")
          ?.checked,
      ).toBe(openNow);
      await act(async () =>
        button(
          "Retry Start December 2026",
          document.querySelector("dialog")!,
        ).click(),
      );
      expect(writes()).toEqual([
        "PUT /member-season",
        ...(openNow ? ["PATCH /seasons/2"] : []),
        "PATCH /seasons/1",
        "PATCH /seasons/1",
      ]);
      expect(host.querySelector('[aria-label="Unfinished Start"]')).toBeNull();
      expect(button("Start January 2027", host).disabled).toBe(false);
    } finally {
      await act(async () => root.unmount());
      host.remove();
      sessionStorage.clear();
    }
  },
);

it("NULL hidden already-open month offers Show and open via show-only fix", async () => {
  const { host, cleanup } = await mount({
    id: null as unknown as number,
    open: true,
  });
  try {
    await act(async () => button("Show and open signups", host).click());
    expect(button("Close signups", host)).toBeUndefined();
    expect(document.querySelector("dialog")?.textContent).toContain(
      "Show it to members?",
    );
    expect(
      button("Show to members", document.querySelector("dialog")!),
    ).toBeTruthy();
  } finally {
    await cleanup();
  }
});
