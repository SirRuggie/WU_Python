// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import EmptyState from "./EmptyState";
it("renders the reason, short line and one native action", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <EmptyState
      title="Roster not published yet"
      line="Publish the selected month to check declarations."
      action={<a href="/cwl/publication">Go to Finalize roster ›</a>}
    />,
  );
  expect(host.querySelector("h2")?.textContent).toBe(
    "Roster not published yet",
  );
  expect(host.querySelector("p")?.textContent).toBe(
    "Publish the selected month to check declarations.",
  );
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/cwl/publication",
  );
  expect(host.querySelectorAll("a,button")).toHaveLength(1);
});
it("does not invent an action when none is useful", () => {
  expect(
    renderToStaticMarkup(
      <EmptyState
        title="No recorded issues"
        line="New reports appear here when a request fails."
      />,
    ),
  ).not.toContain("empty-state-action");
});
