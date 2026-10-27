import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import RosterSelectionBar from "./RosterSelectionBar";
const props = {
  hiddenCount: 0,
  busy: false,
  canRoster: true,
  canSignups: true,
  onAssign: () => {},
  onBalance: () => {},
  onSignup: () => {},
  onClear: () => {},
  onHeight: () => {},
};
it("blocks every bulk action above 50 while retaining clear and visibility warnings", () => {
  const html = renderToStaticMarkup(
    <RosterSelectionBar
      {...props}
      selectedCount={65}
      hiddenCount={2}
      unloadedCount={15}
    />,
  );
  expect(html).toContain("Max 50 per action");
  expect(html).toContain("hidden by filters");
  expect(html).toContain("not shown yet");
  expect((html.match(/disabled=""/g) || []).length).toBe(3);
  expect(
    renderToStaticMarkup(<RosterSelectionBar {...props} selectedCount={50} />),
  ).not.toContain('disabled=""');
});
it("hides unauthorized actions and makes a covered dock inert", () => {
  const html = renderToStaticMarkup(
    <RosterSelectionBar
      {...props}
      selectedCount={1}
      canRoster={false}
      hidden
    />,
  );
  expect(html).not.toContain("<span>Assign</span>");
  expect(html).not.toContain("<span>Balance</span>");
  expect(html).toContain('inert=""');
  expect(html).toContain("<span>Signup</span>");
});
