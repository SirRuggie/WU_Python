import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

it("keeps Signup message rows stretched when the destination content narrows", () => {
  const css = readFileSync(
    new URL("../ReminderWorkspace.css", import.meta.url),
    "utf8",
  );
  const row = css.match(
    /\.reminders-workspace \.reminder-message-row\s*\{([^}]+)\}/,
  )?.[1];
  expect(row).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  expect(row).toMatch(/justify-content:\s*stretch/);
  expect(row).toMatch(/width:\s*100%/);
});
