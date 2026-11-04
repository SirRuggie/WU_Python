import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
const css = ["src/tokens.css", "src/rosterUi/tokens.css"]
  .map((path) => readFileSync(path, "utf8"))
  .join("\n");
const values = new Map(
  [...css.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((match) => [
    match[1],
    match[2].trim(),
  ]),
);
function resolveToken(name: string, ancestors: string[] = []): string {
  if (ancestors.includes(name)) throw Error("Cyclic color token " + name);
  const value = values.get(name);
  if (!value) throw Error("Missing text color token " + name);
  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  const alias = value.match(/^var\(--([\w-]+)\)$/);
  if (!alias) throw Error("Unsupported text color token " + name);
  return resolveToken(alias[1], [...ancestors, name]);
}
const token = (name: string) => resolveToken("roster-" + name);
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

it.each([
  ["text", "bg"],
  ["text", "surface"],
  ["text", "card"],
  ["text-muted", "surface"],
  ["text-muted", "surface-soft"],
  ["text-muted", "card"],
  ["accent", "surface"],
  ["accent", "accent-soft"],
  ["accent-ink", "accent"],
  ["success", "success-surface"],
  ["warning", "warning-surface"],
  ["danger", "danger-surface"],
  ["info", "info-surface"],
])(
  "global %s text on %s meets normal-text contrast4.5:1",
  (foreground, background) => {
    expect(
      contrast(
        resolveToken("wu-" + foreground),
        resolveToken("wu-" + background),
      ),
    ).toBeGreaterThanOrEqual(4.5);
  },
);

it("keeps roster action gold aligned with the approved global accent", () => {
  expect(resolveToken("roster-gold")).toBe("#f4cd64");
  expect(values.get("roster-gold")).toBe("var(--wu-accent)");
});

it("retains the winning primary fill and readable ink after the contrast fold", () => {
  const style = readFileSync("src/style.css", "utf8");
  const primary = style.match(/\.shell\s+\.primary\s*\{([^}]+)\}/)?.[1];
  expect(
    primary,
    "The shell's winning primary rule must survive the fold",
  ).toBeTruthy();
  const declarations = new Map(
    primary!
      .split(";")
      .map((declaration) => declaration.trim())
      .filter(Boolean)
      .map((declaration) => {
        const [property, value] = declaration.split(":");
        return [property.trim(), value.trim()];
      }),
  );
  const color = (property: string) => {
    const value = declarations.get(property);
    const alias = value?.match(/^var\(--([\w-]+)\)$/);
    return alias ? resolveToken(alias[1]) : value;
  };
  expect(color("background")).toBe("#f4cd64");
  expect(color("color")).toBe("#241b08");
  expect(color("-webkit-text-fill-color")).toBe("#241b08");
  expect(
    contrast(color("color")!, color("background")!),
  ).toBeGreaterThanOrEqual(4.5);
});
