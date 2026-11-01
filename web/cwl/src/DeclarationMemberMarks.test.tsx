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
