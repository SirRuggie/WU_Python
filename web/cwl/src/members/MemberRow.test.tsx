// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import MemberRow from "./MemberRow";
const member = {
  discord_id: "111111111111111111",
  name: "Sample Person",
  nickname: "Sample",
  bot: false,
  status: "Missing",
  profile: null,
  parsed: null,
  skip_reason: null,
  role_ids: [],
};
it("row tap opens the person and never toggles selection; checkbox only selects", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const open = vi.fn(),
    select = vi.fn();
  try {
    await act(async () =>
      root.render(
        <MemberRow
          member={member}
          selected={false}
          onSelect={select}
          onOpen={open}
        />,
      ),
    );
    await act(async () => host.querySelector("button")!.click());
    expect(open).toHaveBeenCalledTimes(1);
    expect(select).not.toHaveBeenCalled();
    await act(async () => host.querySelector("input")!.click());
    expect(select).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledTimes(1);
    expect(host.querySelector("input")!.closest("button")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("bots have no selectable checkbox and errors remain on their own row", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <MemberRow
          member={{ ...member, bot: true }}
          selected={false}
          onSelect={() => {}}
          onOpen={() => {}}
          error="Permission changed"
        />,
      ),
    );
    expect(host.querySelector("input")!.disabled).toBe(true);
    expect(host.querySelector("[role=alert]")!.textContent).toBe(
      "Permission changed",
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
