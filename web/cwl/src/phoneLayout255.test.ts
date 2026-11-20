import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
it("keeps phone season unwrapped and pool buttons sharing free width at44px minimum", () => {
  const header = readFileSync(
    new URL("./RosterHeader.css", import.meta.url),
    "utf8",
  );
  const workspace = readFileSync(
    new URL("./RosterWorkspace.css", import.meta.url),
    "utf8",
  );
  expect(header).toMatch(
    /grid-template-columns:\s*minmax\(0, 1fr\) max-content 44px/,
  );
  expect(header).toMatch(
    /roster-header-season \.roster-menu-current\s*\{\s*white-space:\s*nowrap/,
  );
  expect(workspace).not.toContain("132px");
  expect(workspace).toMatch(
    /roster-list-pool-tabs\s*\{\s*flex:\s*1 1 auto;\s*width:\s*0;\s*min-width:\s*0/,
  );
  expect(workspace).toMatch(
    /@media \(max-width: 340px\)[\s\S]*column-gap:\s*2px/,
  );
  expect(workspace).toMatch(/roster-member-heading\s*\{\s*display:\s*flex;/);
  expect(workspace).toMatch(
    /roster-member-heading \.discord-contact\s*\{[\s\S]*?min-width:\s*44px;\s*min-height:\s*44px/,
  );
  expect(workspace).toMatch(/roster-list-pool-tabs\s*\{\s*flex:\s*1 1 auto/);
  expect(workspace).toMatch(
    /roster-list-pool-tabs > button\s*\{\s*box-sizing:\s*border-box;\s*flex:\s*1 1 0;\s*min-width:\s*44px/,
  );
});
