import { expect, it } from "vitest";
import { rosterImageDimensions } from "./rosterImageDimensions";
it("reserves the existing renderer's full and last-page geometry", () => {
  expect(rosterImageDimensions(1, 0)).toEqual({ width: 1000, height: 460 });
  expect(rosterImageDimensions(15, 0)).toEqual({ width: 1000, height: 1440 });
  expect(rosterImageDimensions(16, 1)).toEqual({ width: 1000, height: 460 });
  expect(rosterImageDimensions(30, 1)).toEqual({ width: 1000, height: 1440 });
});
it("does not invent dimensions for malformed or absent pages", () => {
  for (const [count, page] of [
    [0, 0],
    [-1, 0],
    [16, 2],
    [NaN, 0],
    [16, -1],
    [16, 0.5],
  ])
    expect(rosterImageDimensions(count, page)).toEqual({});
});
