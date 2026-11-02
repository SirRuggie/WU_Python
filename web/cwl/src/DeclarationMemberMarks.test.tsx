// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi, afterEach } from "vitest";
import DeclarationMemberMarks from "./DeclarationMemberMarks";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (orig) => ({
  ...(await orig<object>()),
  api: transport,
}));
let root: ReturnType<typeof createRoot> | undefined, host: HTMLDivElement;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  transport.mockReset();
});
it("reuses compact identity and DM for linked rows without per-row lookup, keeping unlinked rows quiet", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const uid = "123456789012345678";
  await act(async () =>
    root!.render(
      <DeclarationMemberMarks
        rows={[
          {
            tag: "#P",
            name: "Linked account",
            town_hall: 16,
            context: "Not signed up",
            assigned_clan_tag: null,
            discord_id: uid,
            discord_profile: {
              id: uid,
              display_name: "Long family name",
              username: "family",
            },
          },
          {
            tag: "#Q",
            name: "Unlinked account",
            town_hall: 9,
            context: "Not signed up",
            assigned_clan_tag: null,
          },
        ]}
      />,
    ),
  );
  expect(host.querySelectorAll(".discord-identity-compact")).toHaveLength(1);
  expect(host.querySelectorAll("a")).toHaveLength(1);
  expect(host.querySelector("a")?.href).toContain(uid);
  expect(host.textContent).toContain("Long family name");
  expect(host.textContent).not.toContain(uid);
  expect(host.textContent).not.toContain("No Discord account linked");
  expect(transport).not.toHaveBeenCalled();
});
it("groups one person across three accounts and saves only the checked account", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const uid = "123456789012345678";
  const onChanged = vi.fn();
  const rows = ["#P", "#Q", "#L"].map((tag, index) => ({
    tag,
    name: `Account ${index}`,
    town_hall: index === 0 ? 9 : 16,
    context: "Assigned to Fixture",
    assigned_clan_tag: "#HOST",
    discord_id: uid,
    discord_profile: { id: uid, display_name: "One person" },
    roster_filler: false,
    roster_filler_revision: index,
  }));
  transport.mockResolvedValue({
    revision: 12,
    mark_revision: 3,
    roster_filler: true,
    tag: "#L",
  });
  await act(async () =>
    root!.render(
      <DeclarationMemberMarks
        rows={rows}
        control={{ seasonId: "1", revision: 11, onChanged }}
      />,
    ),
  );
  expect(host.querySelectorAll(".discord-identity-compact")).toHaveLength(1);
  expect(host.querySelectorAll("a.discord-contact")).toHaveLength(1);
  expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(3);
  expect(host.querySelectorAll(".declaration-member-account")).toHaveLength(3);
  await act(async () =>
    host.querySelectorAll<HTMLInputElement>("input")[2].click(),
  );
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport).toHaveBeenCalledWith(
    "/seasons/1/roster-filler/%23L",
    "PATCH",
    { revision: 11, roster_filler: true, mark_revision: 2 },
  );
  expect(onChanged).toHaveBeenCalledWith(
    expect.objectContaining({ tag: "#L", revision: 12 }),
  );
});
it("keeps unlinked accounts separate and deduplicates shared low/filler tags", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const row = {
    tag: "#P",
    name: "Unlinked",
    town_hall: 9,
    context: "Not signed up",
    assigned_clan_tag: null,
  };
  await act(async () =>
    root!.render(
      <DeclarationMemberMarks
        rows={[row, row, { ...row, tag: "#Q", name: "Another" }]}
      />,
    ),
  );
  expect(host.querySelectorAll(".declaration-member-group")).toHaveLength(2);
  expect(host.querySelectorAll(".declaration-member-account")).toHaveLength(2);
  expect(host.querySelectorAll(".discord-identity-compact,a")).toHaveLength(0);
  expect(transport).not.toHaveBeenCalled();
});
