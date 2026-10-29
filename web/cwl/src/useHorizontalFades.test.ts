import { expect, it } from "vitest";
import { horizontalFadeState } from "./useHorizontalFades";

it("shows only edges with hidden content", () => {
  expect(
    horizontalFadeState({ scrollLeft: 0, clientWidth: 360, scrollWidth: 360 }),
  ).toEqual({ left: false, right: false });
  expect(
    horizontalFadeState({ scrollLeft: 0, clientWidth: 360, scrollWidth: 600 }),
  ).toEqual({ left: false, right: true });
  expect(
    horizontalFadeState({
      scrollLeft: 120,
      clientWidth: 360,
      scrollWidth: 600,
    }),
  ).toEqual({ left: true, right: true });
  expect(
    horizontalFadeState({
      scrollLeft: 240,
      clientWidth: 360,
      scrollWidth: 600,
    }),
  ).toEqual({ left: true, right: false });
});
