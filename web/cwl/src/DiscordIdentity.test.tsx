// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: transport,
}));
import DiscordIdentity from "./DiscordIdentity";
import useDiscordIdentities from "./useDiscordIdentities";
const id = "123456789012345678";
const profile = {
  id,
  display_name: "Example member",
  username: "example",
  avatar_url: "https://cdn.discordapp.com/avatars/123/avatar.png",
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const flush = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  transport.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("full and compact share one identity, no primary raw ID, optional diagnostics only", async () => {
  for (const variant of ["full", "compact"] as const) {
    await act(async () =>
      root.render(
        <DiscordIdentity
          userId={id}
          resolvedMember={profile}
          variant={variant}
        />,
      ),
    );
    expect(host.querySelector("strong")?.textContent).toBe("Example member");
    expect(host.textContent).not.toContain(id);
    expect(host.querySelector("a")?.href).toBe(
      `https://discord.com/users/${id}`,
    );
    expect(host.querySelector(`.discord-identity-${variant}`)).not.toBeNull();
  }
  expect(transport).not.toHaveBeenCalled();
  await act(async () =>
    root.render(
      <DiscordIdentity userId={id} resolvedMember={profile} diagnostics />,
    ),
  );
  expect(host.querySelector("details code")?.textContent).toBe(id);
});
it("loading unavailable and no link never present an ID as the member name", async () => {
  await act(async () =>
    root.render(
      <DiscordIdentity userId={id} resolvedMember={null} resolving />,
    ),
  );
  expect(host.textContent).toContain("Loading Discord member");
  await act(async () =>
    root.render(<DiscordIdentity userId={id} resolvedMember={null} />),
  );
  expect(host.textContent).toContain("Discord member unavailable");
  expect(host.textContent).not.toContain(id);
  await act(async () =>
    root.render(<DiscordIdentity userId={null} resolvedMember={null} />),
  );
  expect(host.textContent).toBe("No Discord account linked");
  await act(async () =>
    root.render(
      <DiscordIdentity
        userId={id}
        resolvedMember={{ ...profile, display_name: id, username: id }}
      />,
    ),
  );
  expect(host.querySelector("strong")?.textContent).toBe(
    "Discord member unavailable",
  );
});
it("avatar failure falls back, untrusted URLs are rejected, archive avatars stay supported", async () => {
  await act(async () =>
    root.render(<DiscordIdentity userId={id} resolvedMember={profile} />),
  );
  await act(async () =>
    host.querySelector("img")!.dispatchEvent(new Event("error")),
  );
  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector(".roster-discord-avatar")?.textContent).toBe("E");
  await act(async () =>
    root.render(
      <DiscordIdentity
        userId={id}
        resolvedMember={{
          ...profile,
          avatar_url: "https://untrusted.example/avatar.png",
        }}
      />,
    ),
  );
  expect(host.querySelector("img")).toBeNull();
  await act(async () =>
    root.render(
      <DiscordIdentity
        userId={id}
        resolvedMember={{
          ...profile,
          avatar_url: "/api/cwl/manage/member-events/event-1/avatar",
        }}
      />,
    ),
  );
  expect(host.querySelector("img")?.getAttribute("src")).toContain(
    "/member-events/event-1/avatar",
  );
});
it("batch resolves once for many rows and row renderers do not fetch", async () => {
  const ids = Array.from({ length: 25 }, (_, i) =>
    String(BigInt(id) + BigInt(i)),
  );
  transport.mockResolvedValue({
    options: ids.map((uid, i) => ({
      ...profile,
      id: uid,
      display_name: "Member " + i,
    })),
  });
  function Page() {
    const batch = useDiscordIdentities(ids);
    return (
      <>
        {ids.map((uid) => (
          <DiscordIdentity
            key={uid}
            userId={uid}
            resolvedMember={batch.members[uid] || null}
            resolving={batch.loading}
            variant="compact"
          />
        ))}
      </>
    );
  }
  await act(async () => root.render(<Page />));
  await flush();
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport.mock.calls[0][0]).toContain("staff-signup-members?ids=");
  expect(host.querySelectorAll("strong")).toHaveLength(25);
  expect(host.textContent).not.toContain(id);
});
it("cached display names remain immediate while batch profiles resolve", async () => {
  await act(async () =>
    root.render(
      <DiscordIdentity
        userId={id}
        displayName="Cached owner"
        resolvedMember={null}
        resolving
      />,
    ),
  );
  expect(host.querySelector("strong")?.textContent).toBe("Cached owner");
  expect(transport).not.toHaveBeenCalled();
});

it("a supplied profile from another owner cannot label this account",async()=>{
 await act(async()=>root.render(<DiscordIdentity userId={id} resolvedMember={{...profile,id:"223456789012345678"}}/>));
 expect(host.textContent).not.toContain("Example member");expect(host.querySelector("img")).toBeNull();expect(host.textContent).toContain("Discord member unavailable");
});
