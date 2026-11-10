// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeMemberSelect, {
  strikeMemberOptions,
  type StrikeMemberOption,
} from "./StrikeMemberSelect";
import type { ActivityAccount } from "./strikeActivityView";
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const options: StrikeMemberOption[] = [
  {
    id: "100000000000000001",
    name: "𝔇𝔯𝔞𝔤𝔬𝔫𝔖𝔩𝔞𝔶𝔢𝔯",
    username: "ds_77",
    accounts: 2,
  },
  { id: "100000000000000002", name: "Ace", username: "ace", accounts: 1 },
  { id: "100000000000000003", name: "Dragonfly", accounts: 1 },
  {
    id: "100000000000000004",
    name: "Zed",
    username: "dragon_zed",
    accounts: 3,
  },
];
let host: HTMLDivElement, root: Root;
const onChange = vi.fn();
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onChange.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const mount = async () =>
  act(async () =>
    root.render(
      <StrikeMemberSelect options={options} value="" onChange={onChange} />,
    ),
  );
const type = async (text: string) => {
  const input = host.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const rows = () =>
  [...host.querySelectorAll("li button")].map((node) => node.textContent);
it("is labelled as a Discord member search", async () => {
  await mount();
  expect(host.querySelector("label")!.textContent).toContain("Discord member");
  expect(host.querySelector("input")!.placeholder).toBe(
    "Name, username or ID…",
  );
});
it("matches fancy letters, usernames and ranks name-prefix first", async () => {
  await mount();
  await type("dragon");
  expect(rows()).toEqual([
    "@𝔇𝔯𝔞𝔤𝔬𝔫𝔖𝔩𝔞𝔶𝔢𝔯ds_772 accounts",
    "@Dragonfly1 account",
    "@Zeddragon_zed3 accounts",
  ]);
});
it("matches an exact Discord ID first and never shows it", async () => {
  await mount();
  await type("100000000000000004");
  expect(rows()).toEqual(["@Zeddragon_zed3 accounts"]);
  expect(host.textContent).not.toContain("100000000000000004");
  await type("10000000000000000");
  expect(host.textContent).toContain("No Discord member found.");
});
it("hides a username that repeats the name and caps results at eight", async () => {
  await mount();
  await type("ace");
  expect(rows()).toEqual(["@Ace1 account"]);
  const many = Array.from({ length: 12 }, (_, i) => ({
    id: `2000000000000000${String(i).padStart(2, "0")}`,
    name: `Member ${i}`,
    accounts: 1,
  }));
  await act(async () =>
    root.render(
      <StrikeMemberSelect options={many} value="" onChange={onChange} />,
    ),
  );
  await type("member");
  expect(rows()).toHaveLength(8);
});
it("lists a member that has only a username", () => {
  const account = (extra: Partial<ActivityAccount>) =>
    ({ player_tag: "#P", player_name: "P", ...extra }) as ActivityAccount;
  expect(
    strikeMemberOptions([
      account({ discord_id: "100000000000000009", discord_username: "solo_u" }),
      account({ discord_id: "100000000000000008" }),
    ]),
  ).toEqual([
    {
      id: "100000000000000009",
      name: "solo_u",
      username: "solo_u",
      accounts: 1,
    },
  ]);
});
