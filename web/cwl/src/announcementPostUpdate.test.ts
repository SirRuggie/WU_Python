import { expect, it } from "vitest";
import {
  validPostCopy,
  safePostUrl,
  checkedPostReview,
} from "./announcementPostUpdate";
const copy = {
  title: "Title",
  body: "Body",
  buttons: [{ label: "Tasks", url: "https://example.com/tasks" }],
};
it("validates literal text and five HTTPS links without credentials or whitespace", () => {
  expect(validPostCopy(copy)).toBe(true);
  expect(validPostCopy({ ...copy, body: "x".repeat(4000) })).toBe(false);
  for (const url of [
    "http://example.com",
    "javascript:alert(1)",
    "https://user:secret@example.com",
    "https://example.com/a b",
  ])
    expect(validPostCopy({ ...copy, buttons: [{ label: "Bad", url }] })).toBe(
      false,
    );
  expect(
    validPostCopy({
      ...copy,
      buttons: Array.from({ length: 6 }, () => copy.buttons[0]),
    }),
  ).toBe(false);
});
it("only links to a concrete Discord post, and rejects incomplete server review DTOs", () => {
  expect(safePostUrl("https://discord.com/channels/1/2/3")).toBe(true);
  expect(safePostUrl("https://discord.com.evil/channels/1/2/3")).toBe(false);
  expect(() => checkedPostReview({} as never)).toThrow("incomplete");
});
