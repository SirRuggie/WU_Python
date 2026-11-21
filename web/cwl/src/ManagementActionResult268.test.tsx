import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import ManagementActionResult from "./ManagementActionResult";
it("keeps details, safe Discord link and accounts in a single announced success", () => {
  const html = renderToStaticMarkup(
    <ManagementActionResult
      actionResult={{
        message: "Saved.",
        details: "Updated channels.",
        url: "https://discord.com/channels/1/2/3",
        accounts: [{ name: "Fixture player", tag: "#ABC", clan_name: "Main" }],
      }}
    />,
  );
  expect(html).toContain('aria-label="Action result" role="status"');
  expect(html).not.toContain("<h3>Result</h3>");
  expect(html).toContain('aria-hidden="true"');
  for (const text of [
    "Saved.",
    "Updated channels.",
    "View in Discord",
    "Fixture player",
    "#ABC",
    "Main",
  ])
    expect(html).toContain(text);
  expect(
    renderToStaticMarkup(
      <ManagementActionResult
        actionResult={{ message: "Saved.", url: "javascript:alert(1)" }}
      />,
    ),
  ).not.toContain("href=");
});
it("error geometry stays red and independent from the three-pixel warning edge", () => {
  const css = readFileSync(
    new URL("./ServerManagement.css", import.meta.url),
    "utf8",
  );
  const error = css.match(/\.manage-error \{([^}]+)\}/)![1];
  expect(error).toContain("1px solid var(--wu-danger-border)");
  expect(error).toContain("var(--wu-danger-surface)");
  expect(error).not.toContain("wu-warning");
  expect(error).not.toContain("3px");
  const warning = css.match(/\.manage-notice \{([^}]+)\}/)![1];
  expect(warning).toContain("3px solid var(--wu-warning)");
});

it("world clock warning edge wins the border-color cascade", () => {
  const css = readFileSync(
    new URL("./worldClocks/WorldClocks.css", import.meta.url),
    "utf8",
  );
  const rule = css.match(/\.world-clock-warning \{([^}]+)\}/)![1];
  expect(
    rule.lastIndexOf("border-left: 3px solid var(--wu-warning)"),
  ).toBeGreaterThan(rule.lastIndexOf("border-color:"));
});
