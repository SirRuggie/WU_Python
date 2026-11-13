import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ServerManagement from "./ServerManagement";

vi.mock("./useCompactPreview", () => ({ default: () => false }));

it.each([
  ["applications-settings", "Ticket settings"],
  ["fwa-settings", "FWA tools"],
  ["connections-settings", "Band monitor"],
  ["cwl-returns", "Return reminders"],
] as const)("uses one focusable page h1 for %s", (area, title) => {
  const html = renderToStaticMarkup(<ServerManagement area={area} />);
  expect(html.match(/<h1\b/g)).toHaveLength(1);
  expect(html).toContain(`<h1 tabindex="-1">${title}</h1>`);
});
