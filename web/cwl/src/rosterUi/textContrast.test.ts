import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
const css = readFileSync("src/rosterUi/tokens.css", "utf8");
const token = (name: string) => {
  const value = css.match(
    new RegExp(`--roster-${name}:\\s*(#[0-9a-f]{6})\\s*;`, "i"),
  )?.[1];
  if (!value) throw Error("Missing text color token " + name);
  return value;
};
function luminance(hex: string) {
  const channels = [1, 3, 5]
    .map((start) => parseInt(hex.slice(start, start + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
const contrast = (a: string, b: string) => {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
};
it.each([
  ["danger", "selection-surface"],
  ["danger", "card-danger"],
  ["text", "surface"],
  ["text-muted", "surface-soft"],
  ["warning", "attention-surface"],
  ["success", "card-success"],
  ["gold", "selection-surface"],
])(
  "%s text on %s meets normal-text contrast4.5:1",
  (foreground, background) => {
    expect(
      contrast(token(foreground), token(background)),
    ).toBeGreaterThanOrEqual(4.5);
  },
);
