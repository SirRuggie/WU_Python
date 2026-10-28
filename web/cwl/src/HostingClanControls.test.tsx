// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import HostingClanControls, {
  availableFamily,
  ArchiveHostingClan,
} from "./HostingClanControls";
import { DashboardPermissions } from "./DashboardPermissions";
import type { RosterClan } from "./roster";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
vi.mock("./ActionPanel", () => ({
  default: ({ children, footer }: any) => (
    <div role="dialog">
      {children}
      {footer}
    </div>
  ),
}));
vi.mock("./ConfirmDialog", () => ({
  default: ({ text, onConfirm, onCancel }: any) => (
    <div role="dialog">
      {text}
      <button onClick={onConfirm}>Archive clan</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  ),
}));
it("excludes active hosts while allowing archived and non-host family clans", () => {
  expect(
    availableFamily(
      [
        { tag: "#A", name: "A" },
        { tag: "#B", name: "B" },
        { tag: "#C", name: "C" },
      ],
      [
        { tag: "#A", archived: false },
        { tag: "#B", archived: true },
      ] as RosterClan[],
    ).map((c) => c.tag),
  ).toEqual(["#B", "#C"]);
});
it("family selection is read-only until explicit Confirm uses the existing add POST", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api
    .mockReset()
    .mockImplementation(async (_path, method) =>
      method ? {} : { clans: [{ tag: "#P2Y", name: "New family clan" }] },
    );
  const changed = vi.fn(async () => {});
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const click = async (name: string) =>
    act(async () =>
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent?.trim() === name)!
        .click(),
    );
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <HostingClanControls
            clans={[]}
            onChanged={changed}
            onBusy={() => {}}
            disabled={false}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    await click("Add hosting clan");
    await click("New family clan · #P2Y");
    expect(api.mock.calls.every((c) => !c[1])).toBe(true);
    await click("Confirm add hosting clan");
    expect(api).toHaveBeenCalledWith("/clans", "POST", {
      tag: "#P2Y",
      pool: null,
    });
    expect(changed).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("archive requires confirmation and keeps assignments via the existing archive endpoint", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset().mockResolvedValue({});
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const clan = { tag: "#P2Y", name: "Host" } as RosterClan;
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <ArchiveHostingClan
            clan={clan}
            disabled={false}
            onChanged={async () => {}}
            onBusy={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => host.querySelector("button")!.click());
    expect(host.textContent).toContain("This season's assignments stay.");
    expect(api).not.toHaveBeenCalled();
    await act(async () =>
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Archive clan")!
        .click(),
    );
    expect(api).toHaveBeenCalledWith("/clans/%23P2Y", "PATCH", {
      archived: true,
    });
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

for (const permissions of [
  ["cwl_settings"],
  ["cwl_roster"],
  ["cwl_signups"],
  ["cwl_settings", "cwl_roster"],
]) {
  it(`hosting controls require roster access and existing mutation permission: ${permissions.join(", ")}`, async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    api.mockReset();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider value={{ owner: false, permissions }}>
            <HostingClanControls
              clans={[]}
              onChanged={async () => {}}
              onBusy={() => {}}
              disabled={false}
            />
            <ArchiveHostingClan
              clan={{ tag: "#P2Y", name: "Host" } as RosterClan}
              disabled={false}
              onChanged={async () => {}}
              onBusy={() => {}}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      const visible =
        permissions.includes("cwl_settings") &&
        permissions.includes("cwl_roster");
      expect(host.textContent?.includes("Add hosting clan")).toBe(visible);
      expect(host.textContent?.includes("Archive hosting clan")).toBe(visible);
      expect(api).not.toHaveBeenCalled();
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });
}
it("by-tag lookup displays the name before Confirm and requires a resolved choice", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  let resolveLookup!: (v: unknown) => void;
  api.mockReset().mockImplementation(async (path, method) =>
    method
      ? {}
      : path.startsWith("/clans/lookup")
        ? new Promise((r) => {
            resolveLookup = r;
          })
        : { clans: [] },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const button = (name: string) =>
    [...host.querySelectorAll("button")].find(
      (b) => b.textContent?.trim() === name,
    )!;
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <HostingClanControls
            clans={[]}
            disabled={false}
            onChanged={async () => {}}
            onBusy={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => button("Add hosting clan").click());
    await act(async () => button("By clan tag").click());
    expect(button("Confirm add hosting clan").disabled).toBe(true);
    const input = host.querySelector("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "#P2Y");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => button("Look up clan").click());
    expect(button("Confirm add hosting clan").disabled).toBe(true);
    await act(async () =>
      resolveLookup({ tag: "#P2Y", name: "Resolved host" }),
    );
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain(
      "Resolved host",
    );
    expect(button("Confirm add hosting clan").disabled).toBe(false);
    expect(api.mock.calls.every((c) => !c[1])).toBe(true);
    await act(async () => button("Confirm add hosting clan").click());
    expect(api).toHaveBeenCalledWith("/clans", "POST", {
      tag: "#P2Y",
      pool: null,
    });
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
