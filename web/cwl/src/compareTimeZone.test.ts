import { expect, it } from "vitest";
import { ownerTimeZone, sortTimeZoneAccounts } from "./compareTimeZone";
import { compareClanAccounts } from "./compare";
import type { RosterAccount } from "./roster";
const offsets = {
  GMT: 0,
  UTC: 0,
  BST: 60,
  WET: 0,
  CET: 60,
  CEST: 120,
  EET: 120,
  EEST: 180,
  MSK: 180,
  IST: 330,
  PKT: 300,
  SGT: 480,
  AWST: 480,
  JST: 540,
  AEST: 600,
  AEDT: 660,
  NZST: 720,
  EST: -300,
  EDT: -240,
  CST: -360,
  CDT: -300,
  MST: -420,
  MDT: -360,
  PST: -480,
  PDT: -420,
  AST: -240,
  HST: -600,
  AKST: -540,
  EASTERN: -300,
  CENTRAL: -360,
  PACIFIC: -480,
  MOUNTAIN: -420,
};
for (const [label, minutes] of Object.entries(offsets))
  it(`parses ${label}`, () =>
    expect(ownerTimeZone(`Name | ${label} 🇺🇸`)).toEqual({
      label,
      offsetMinutes: minutes,
    }));
it.each([
  ["UTC+5", 300],
  ["UTC-3", -180],
  ["GMT+1", 60],
  ["UTC+5:30", 330],
])("parses %s", (label, minutes) => {
  expect(ownerTimeZone(`Name | ${label}`)?.offsetMinutes).toBe(minutes);
});
it("uses the last pipe and retains unknown labels", () => {
  expect(ownerTimeZone("Pipe | Name | EST 🇺🇸")).toEqual({
    label: "EST",
    offsetMinutes: -300,
  });
  expect(ownerTimeZone("Name | MOON")).toEqual({
    label: "MOON",
    offsetMinutes: null,
  });
  expect(ownerTimeZone("Name | UTC+24")?.offsetMinutes).toBeNull();
  expect(ownerTimeZone("Name | UTC+5:90")?.offsetMinutes).toBeNull();
});
it.each([null, undefined, "Name", "Name | ", "Name | 🇺🇸"])(
  "missing zone %s",
  (value) => expect(ownerTimeZone(value)).toBeNull(),
);
const row = (
  tag: string,
  user_id: string,
  weight: number | null,
): RosterAccount =>
  ({
    tag,
    user_id,
    effective_weight: weight,
    player_name: tag,
    assigned_clan_tag: "#CLAN",
  }) as RosterAccount;
it("orders west to east, unknown labels A–Z, then no zone; owners stay together before weight", () => {
  const accounts = [
    row("blank", "0", 999),
    row("z", "z", 200),
    row("moon", "m", 190),
    row("a-low", "a", 100),
    row("east", "e", 200),
    row("alpha", "n", 180),
    row("a-high", "a", 300),
    row("a-null", "a", null),
    row("west", "w", 100),
  ];
  const owners = {
    w: "West | PST",
    a: "Able | EST",
    z: "Zed | EST",
    e: "East | IST",
    m: "M | MOON",
    n: "N | ALPHA",
    0: "No zone",
  };
  expect(sortTimeZoneAccounts(accounts, owners).map((a) => a.tag)).toEqual([
    "west",
    "a-high",
    "a-low",
    "a-null",
    "z",
    "east",
    "alpha",
    "moon",
    "blank",
  ]);
  expect(accounts[0].tag).toBe("blank");
  expect(
    compareClanAccounts(
      [
        ...accounts,
        { ...accounts[0], tag: "elsewhere", assigned_clan_tag: "#OTHER" },
      ],
      "#CLAN",
      "time_zone",
      owners,
    ),
  ).toHaveLength(9);
});
it("ties owner nicknames by user ID before account weight", () => {
  expect(
    sortTimeZoneAccounts([row("two", "2", 300), row("one", "1", 100)], {
      1: "Same | UTC",
      2: "Same | UTC",
    }).map((a) => a.tag),
  ).toEqual(["one", "two"]);
});

it.each([
  "\u{1F3F4}\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}",
  "\u{1F3F4}\u{E0067}\u{E0062}\u{E0073}\u{E0063}\u{E0074}\u{E007F}",
])("ignores subdivision flag tag characters %s", (flag) => {
  expect(ownerTimeZone(`Name | GMT ${flag}`)).toEqual({
    label: "GMT",
    offsetMinutes: 0,
  });
});
it("recognizes UK as standard GMT", () =>
  expect(ownerTimeZone("Name | UK 🇬🇧")).toEqual({
    label: "UK",
    offsetMinutes: 0,
  }));

it("recognizes NZT as New Zealand standard time", () =>
  expect(ownerTimeZone("Name | NZT 🇳🇿")).toEqual({
    label: "NZT",
    offsetMinutes: 720,
  }));

it.each([
  ["MT", -420],
  ["MTN", -420],
  ["AET", 600],
])("maps live standard-time alias %s", (label, offset) =>
  expect(ownerTimeZone(`Name | ${label}`)?.offsetMinutes).toBe(offset),
);

it("normalizes decorated Unicode zone letters while retaining ambiguous annotations",()=>{
 expect(ownerTimeZone("Name | 𝔼𝕊𝕋")).toEqual({label:"EST",offsetMinutes:-300});
 expect(ownerTimeZone("Name | GMT+8 (NEW)")).toEqual({label:"GMT+8 (NEW)",offsetMinutes:null});
});
