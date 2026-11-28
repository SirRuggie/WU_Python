import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";

vi.mock("./api", () => ({ api: vi.fn() }));
beforeEach(() => {
  vi.resetModules();
  vi.mocked(api).mockReset();
});

it("shares the icon read and picks the highest valid maximum and its owner", async () => {
  const url =
    "https://cdn.discordapp.com/emojis/1571025137896005783.gif?size=64";
  vi.mocked(api).mockResolvedValue([
    { level: 12, emoji_url: null, weight_max: 120000 },
    { level: 19, emoji_url: url, weight_max: 200000 },
    { level: 20, emoji_url: null, weight_max: 190000 },
    ...[300000.5, 0, -1, 500001, "500000", true, null, NaN, Infinity].map(
      (weight_max) => ({ level: 21, weight_max }),
    ),
    { level: 100, weight_max: 500000 },
    { level: 0, weight_max: 500000 },
    { level: "22", weight_max: 500000 },
    null,
  ]);
  const registry = await import("./townHallRegistry");
  const [icons, maximum] = await Promise.all([
    registry.loadTownHallIcons(),
    registry.loadTownHallWeightMax(),
  ]);
  expect(maximum).toEqual({ level: 19, max: 200000 });
  expect(icons.get(19)).toBe(url);
  expect(registry.knownTownHallIcon(19)).toBe(url);
  expect(await registry.loadTownHallWeightMax()).toEqual(maximum);
  expect(api).toHaveBeenCalledExactlyOnceWith("/town-halls");
});

for (const weight_max of [1, 500000]) {
  it(`accepts the inclusive maximum bound ${weight_max}`, async () => {
    vi.mocked(api).mockResolvedValue([{ level: 19, weight_max }]);
    const { loadTownHallWeightMax } = await import("./townHallRegistry");
    expect(await loadTownHallWeightMax()).toEqual({
      level: 19,
      max: weight_max,
    });
  });
}

for (const response of [
  [],
  [{ level: 19 }],
  {},
  null,
  [{ level: 19, weight_max: 0 }],
  [300000.5, -1, 500001, "200000", true].map((weight_max) => ({
    level: 19,
    weight_max,
  })),
]) {
  it("returns null when the read has no valid maximum", async () => {
    vi.mocked(api).mockResolvedValue(response);
    const { loadTownHallWeightMax } = await import("./townHallRegistry");
    expect(await loadTownHallWeightMax()).toBeNull();
  });
}

it("returns null on read failure without retrying or losing icon fallback", async () => {
  vi.mocked(api).mockRejectedValue(new Error("503 unavailable"));
  const registry = await import("./townHallRegistry");
  expect(await registry.loadTownHallWeightMax()).toBeNull();
  expect(await registry.loadTownHallWeightMax()).toBeNull();
  expect(await registry.loadTownHallIcons()).toEqual(new Map());
  expect(registry.knownTownHallIcon(19)).toBeNull();
  expect(api).toHaveBeenCalledTimes(1);
});
