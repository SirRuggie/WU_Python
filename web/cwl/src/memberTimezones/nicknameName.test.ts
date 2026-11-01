import { expect, it } from "vitest";
import { nicknameName } from "./nicknameName";
it.each([
  ["Sir | Ruggie | EST 🇺🇸", "Sir | Ruggie", false],
  ["Bob | Co-Leader", "Bob | Co-Leader", true],
  ["Alice", "Alice", true],
])("preserves the entire nickname name: %s", (value, name, needsReview) => {
  expect(nicknameName(value as string, "Fallback")).toEqual({
    name,
    needsReview,
  });
});
