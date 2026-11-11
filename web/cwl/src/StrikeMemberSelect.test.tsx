// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeMemberSelect, {
  strikeMemberOptions,
  type StrikeMemberOption,
} from "./StrikeMemberSelect";
import type { ActivityAccount } from "./strikeActivityView";
import {
  clearPicker,
  openPicker,
  optionTexts,
  pickerValue,
  typeInPicker,
} from "./searchPickerTestUtils";
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
const render = async (list: StrikeMemberOption[], value = "") =>
  act(async () =>
    root.render(
      <StrikeMemberSelect options={list} value={value} onChange={onChange} />,
    ),
  );
const mount = async () => render(options);
const picker = () => host.querySelector<HTMLElement>(".search-picker")!;
const type = async (text: string) => {
  if (!picker().querySelector("input")) await openPicker(picker());
  await typeInPicker(picker(), text);
};
const rows = () => optionTexts(picker());
it("is labelled as a Discord member search", async () => {
  await mount();
  expect(host.querySelector(".search-picker-label")!.textContent).toBe(
    "Discord member",
  );
  await openPicker(picker());
  expect(host.querySelector("input")!.placeholder).toBe("Name or username");
});
it("matches fancy letters, usernames and ranks name-prefix first", async () => {
  await mount();
  await type("dragon");
  expect(rows()).toEqual([
    "𝔇𝔯𝔞𝔤𝔬𝔫𝔖𝔩𝔞𝔶𝔢𝔯ds_77 · 2 accounts",
    "Dragonfly1 account",
    "Zeddragon_zed · 3 accounts",
  ]);
});
it("matches an exact Discord ID first and never shows it", async () => {
  await mount();
  await type("100000000000000004");
  expect(rows()).toEqual(["Zeddragon_zed · 3 accounts"]);
  expect(host.textContent).not.toContain("100000000000000004");
  await type("10000000000000000");
  expect(host.textContent).toContain("No Discord member found.");
});
it("selects a member, shows its name as the field, and clears it", async () => {
  await mount();
  await type("ace");
  expect(rows()).toEqual(["Ace1 account"]);
  await act(async () =>
    host.querySelector<HTMLElement>('[role="option"]')!.click(),
  );
  expect(onChange).toHaveBeenCalledWith("100000000000000002");
  await render(options, "100000000000000002");
  expect(pickerValue(picker())).toBe("Ace1 account");
  expect(host.textContent).not.toContain("100000000000000002");
  await clearPicker(picker());
  expect(onChange).toHaveBeenLastCalledWith("");
  await render(options, "100000000000000099");
  expect(pickerValue(picker())).toBe("Selected member unavailable");
});
it("lists up to thirty matches and says when more remain", async () => {
  const many = Array.from({ length: 40 }, (_, i) => ({
    id: `2000000000000000${String(i).padStart(2, "0")}`,
    name: `Member ${i}`,
    accounts: 1,
  }));
  await render(many);
  await type("member");
  expect(rows()).toHaveLength(30);
  expect(host.textContent).toContain("Showing 30 of 40");
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
it("folds accents and fullwidth letters, and ranks an exact ID above a name match", async () => {
  const list: StrikeMemberOption[] = [
    { id: "100000000000000011", name: "Ünïcode", accounts: 1 },
    { id: "100000000000000012", name: "Ｗｉｄｅ", accounts: 1 },
    { id: "100000000000000013", name: "100000000000000014 fan", accounts: 1 },
    { id: "100000000000000014", name: "Zed", accounts: 1 },
  ];
  await render(list);
  await type("unicode");
  expect(rows()).toEqual(["Ünïcode1 account"]);
  await type("ｗide");
  expect(rows()).toEqual(["Ｗｉｄｅ1 account"]);
  await type("100000000000000014");
  expect(rows()).toEqual(["Zed1 account", "100000000000000014 fan1 account"]);
});
