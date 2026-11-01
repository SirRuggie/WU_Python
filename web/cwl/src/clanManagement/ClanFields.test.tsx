// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import ClanFields from "./ClanFields";
const leaderId = "123456789012345678";
const clan = {
  tag: "#AAA",
  revision: "one",
  name: "Test clan",
  type: "CWL",
  logo: "",
  leader_id: leaderId,
  leader_role_id: "",
  role_id: "",
};
it("shows leader name and avatar, with IDs only on hover, and shares ordered role search", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host),
    change = vi.fn();
  const props = {
    section: "Roles",
    draft: clan,
    saved: clan,
    disabled: false,
    dirty: false,
    data: { types: [], town_halls: [] },
    channels: [],
    roles: [
      { id: "9", name: "Bot integration", managed: true },
      { id: "3", name: "Captain", color: 0xff0000 },
      { id: "1", name: "Admiral" },
    ],
    memberQuery: "",
    setMemberQuery: vi.fn(),
    members: [
      {
        id: leaderId,
        name: "Captain Jane",
        avatar_url: "https://cdn.discordapp.com/embed/avatars/1.png",
      },
    ],
    memberError: "",
    change,
    action: vi.fn(),
    upload: vi.fn(),
  };
  try {
    await act(async () => root.render(<ClanFields {...props} />));
    expect(host.textContent).toContain("Captain Jane");
    expect(host.textContent).not.toContain(leaderId);
    expect(
      host.querySelector(".roster-discord-identity")!.getAttribute("aria-label"),
    ).toBe("Linked Discord member");
    expect(host.querySelector(".roster-discord-identity img")).not.toBeNull();
    const choices = host.querySelector(
      '[aria-label="Available leader roles"]',
    )!;
    expect(
      [...choices.querySelectorAll("button")].map((button) => button.title),
    ).toEqual(["3", "1"]);
    expect(choices.textContent).not.toContain("Bot integration");
    act(() => choices.querySelector<HTMLButtonElement>("button")!.click());
    expect(change).toHaveBeenCalledWith("leader_role_id", "3");
    await act(async () => root.render(<ClanFields {...props} members={[]} />));
    expect(host.textContent).toContain("Current leader unavailable");
    expect(host.textContent).not.toContain(leaderId);
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});
