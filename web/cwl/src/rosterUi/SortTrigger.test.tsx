import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SortTrigger, { sortTriggerLabel } from "./SortTrigger";
import { rosterSortOptions } from "../rosterSortOptions";
describe("active sort trigger", () => {
  it("exposes the full label and grouping without changing options", () => {
    const html = renderToStaticMarkup(
      <SortTrigger label="Signup: newest first" grouped />,
    );
    expect(html).toContain(
      'aria-label="Sort: Signup: newest first, grouped by Discord user"',
    );
    expect(html).toContain("Signup: newest first · Grouped");
    expect(html).toContain('aria-hidden="true"');
    expect(rosterSortOptions).toHaveLength(9);
  });
  it("does not invent grouping for Compare", () => {
    expect(sortTriggerLabel("Town Hall: high to low")).toBe(
      "Sort: Town Hall: high to low",
    );
    expect(
      renderToStaticMarkup(<SortTrigger label="Town Hall: high to low" />),
    ).not.toContain("Grouped");
  });
});
