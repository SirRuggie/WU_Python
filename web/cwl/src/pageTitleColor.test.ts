import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

// Settings pages (Ticket settings, Integrations, FWA tools, Return reminders)
// share .manage-heading. Their titles must keep the gold ink and red mark.
it("does not override the gold title colour on settings pages", () => {
  const css = readFileSync("src/ServerManagement.css", "utf8");
  expect(css).not.toMatch(/\.manage-heading h1\s*\{[^}]*color:\s*inherit/);
});

it("gives settings page titles the red title mark", () => {
  const css = readFileSync("src/style.css", "utf8");
  const markRule = css.slice(
    css.indexOf("/* Page titles share the helmet bar"),
  );
  expect(markRule).toContain(".manage-heading > div > h1");
});
