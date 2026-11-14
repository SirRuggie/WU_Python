// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import SeasonsPage from "./SeasonsPage";
import type { Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./rosterUi/Menu", () => ({
  default: () => <span>Season selector</span>,
}));
const make = (id: number, label: string) =>
  ({ id, label, signup_open: false, status: "draft" }) as Season;
const buttonByText = (text: string, scope: ParentNode = document) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent === text,
  )!;
const writes = () =>
  api.mock.calls
    .filter((call) => call[1])
    .map((call) => `${call[1]} ${call[0]}`);

async function renderSeasons(seasons: Season[], memberId: number) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset();
  api.mockResolvedValue({
    seasons,
    member_season: { season_id: memberId, revision: 4 },
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onRefresh = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <SeasonsPage
          seasonId={String(seasons[0].id)}
          seasons={seasons}
          memberSeason={{ season_id: memberId, revision: 4 }}
          onSeasonChange={() => {}}
          onRefresh={onRefresh}
          onBusy={() => {}}
        />
      </DashboardPermissions.Provider>,
    ),
  );
  const cleanup = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  return { host, onRefresh, cleanup };
}

it("offers the next month by name and creates it only after confirm", async () => {
  const { host, cleanup } = await renderSeasons([make(1, "2026-11")], 1);
  try {
    expect(host.textContent).toContain("Other name");
    await act(async () => buttonByText("Create December 2026", host).click());
    expect(writes()).toEqual([]);
    api.mockResolvedValue({ id: 2, label: "2026-12", copied_clan_count: 1 });
    await act(async () =>
      buttonByText(
        "Create December 2026",
        document.querySelector("dialog")!,
      ).click(),
    );
    expect(api).toHaveBeenCalledWith("/seasons", "POST", {
      label: "2026-12",
      signup_open: false,
    });
  } finally {
    await cleanup();
  }
});

it("finishes with signups off and ignores a double select", async () => {
  const nov = make(1, "2026-11");
  const dec = make(2, "2026-12");
  const { host, onRefresh, cleanup } = await renderSeasons([nov, dec], 1);
  api.mockResolvedValue({
    seasons: [nov, dec],
    member_season: { season_id: 1, revision: 4 },
  });
  try {
    expect(host.textContent).not.toContain("Create December 2026");
    await act(async () => buttonByText("Finish November 2026", host).click());
    const box = document.querySelector<HTMLInputElement>(
      "dialog input[type=checkbox]",
    )!;
    expect(box.checked).toBe(false);
    const confirm = buttonByText("Finish");
    await act(async () => {
      confirm.click();
      confirm.click();
    });
    expect(writes()).toEqual(["PUT /member-season"]);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  } finally {
    await cleanup();
  }
});

it("names the completed steps when finishing fails", async () => {
  const nov = make(1, "2026-11");
  const dec = make(2, "2026-12");
  const { host, cleanup } = await renderSeasons([nov, dec], 1);
  api.mockImplementation(async (_path: string, method?: string) => {
    if (method === "PUT") throw new Error("Changed by someone else.");
    return {
      seasons: [nov, dec],
      member_season: { season_id: 1, revision: 4 },
    };
  });
  try {
    await act(async () => buttonByText("Finish November 2026", host).click());
    await act(async () => buttonByText("Finish").click());
    expect(host.querySelector(".load-error")?.textContent).toContain(
      "Done: nothing. Not done: show December 2026 to members.",
    );
  } finally {
    await cleanup();
  }
});

it("locks a season that members do not see, after confirm", async () => {
  const { host, onRefresh, cleanup } = await renderSeasons(
    [make(1, "2026-10"), make(2, "2026-11")],
    2,
  );
  api.mockResolvedValue({});
  try {
    await act(async () => buttonByText("Lock October 2026", host).click());
    expect(writes()).toEqual([]);
    expect(document.body.textContent).toContain("read-only");
    await act(async () => buttonByText("Lock season").click());
    expect(api).toHaveBeenCalledWith("/seasons/1", "PATCH", {
      status: "archived",
    });
    expect(onRefresh).toHaveBeenCalledTimes(1);
  } finally {
    await cleanup();
  }
});

it("does not offer Lock for the member season", async () => {
  const { host, cleanup } = await renderSeasons([make(2, "2026-11")], 2);
  try {
    expect(host.textContent).not.toContain("Lock November 2026");
  } finally {
    await cleanup();
  }
});
