import { expect, it } from "vitest";
import { placeCard } from "./placement";
it("flips left, below, then above without clamping into the target", () => {
  const card = { width: 460, height: 250 },
    viewport = { width: 1024, height: 768 };
  expect(
    placeCard({ left: 700, top: 100, width: 150, height: 44 }, card, viewport)
      .left,
  ).toBe(216);
  expect(
    placeCard({ left: 270, top: 180, width: 430, height: 44 }, card, viewport)
      .top,
  ).toBe(288);
  expect(
    placeCard({ left: 270, top: 650, width: 430, height: 44 }, card, viewport)
      .top,
  ).toBe(376);
});
