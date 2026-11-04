import { readFileSync, readdirSync } from "node:fs";
import ts from "typescript";
import { expect, it } from "vitest";

/** Canonical owner/reviewer wording, scoped to UI files (never API/status keys or Discord templates). */
const terms: [string, RegExp][] = [
  ["App.tsx", /Main: play at full strength\. No hero upgrades\./],
  ["App.tsx", /Lazy: relaxed CWL\. You can upgrade during the event\./],
  ["App.tsx", /If you’re in FWA… it’s Lazy Way or No Way!!!/],
  ["App.tsx", /<h1>Signup reminders<\/h1>/],
  ["ClanSettings.tsx", /Clan size/],
  ["RosterPlayerDialog.tsx", /Summary/],
  ["DeclarationPingReview.tsx", /Message \$\{i \+ 1\} of/],
  ["rosterImagePosting.ts", /Discord is slow · wait/],
  ["App.tsx", /'Bonus medals'/],
  ["MemberAssignments.tsx", /<h1>My clan assignments<\/h1>/],
  ["MemberAssignments.tsx", /<h2>Waiting for a clan<\/h2>/],
  ["RosterFilters.tsx", /unassigned: "Unplaced"/],
  ["RosterPlayerDialog.tsx", /account\.assigned_clan_tag \|\| "Unplaced"/],
  ["ClanSettings.tsx", /label="Clan size"/],
  ["PublicationWorkspace.tsx", /heading="Hide roster from members\?"/],
  ["PublicationWorkspace.tsx", /confirmLabel="Hide roster"/],
  [
    "PublicationWorkspace.tsx",
    /Roster hidden\. Members will see assignments only after you publish again\./,
  ],
  ["PublicationWorkspace.tsx", /"Announcements" : "Finalize roster"/],
  ["RosterHeader.tsx", /signup\s*\{accounts\.length === 1 \? "" : "s"\}/],
  ["StaffSignupControls.tsx", /label="Find a player or clan"/],
  ["DeclarationPingPanel.tsx", /row\.published_clan \|\| "Unplaced"/],
  ["DeclarationPingPanel.tsx", /row\.draft_clan \|\| "Unplaced"/],
  ["ParticipationWorkspace.tsx", /exportMonthLabel\(data\.sync\.cycle\)/],
  ["BonusWorkspace.tsx", /exportMonthLabel\(data\.cycle\)/],
];
it.each(terms)(
  "prevents reverted canonical UI term in %s (%s)",
  (file, pattern) => {
    const source = readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
    expect(source).toMatch(pattern);
  },
);
it("retains linking context and rejects obsolete visible labels without renaming transport keys", () => {
  const read = (file: string) =>
    readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
  expect(read("AccountLinkHelp.tsx")).toContain(
    "Already linked but missing here?",
  );
  expect(read("AccountLinkHelp.tsx")).toContain(
    "If the bots show different owners",
  );
  expect(read("MemberAssignments.tsx")).not.toMatch(
    /Published clan assignments|Not published yet|Published · your accounts/,
  );
  expect(read("StaffSignupControls.tsx")).not.toContain(
    'label="Find an account"',
  );
  expect(read("DeclarationPingPanel.tsx")).not.toMatch(/\|\| "unassigned"/);
});

it("keeps internal feature names out of visible dashboard words", () => {
  const bannedWords = /\bcampaign\b/i;
  const root = new URL("./", import.meta.url);
  const violations: string[] = [];
  function scan(folder: URL) {
    for (const entry of readdirSync(folder, { withFileTypes: true })) {
      const url = new URL(entry.name, folder);
      if (entry.isDirectory()) { scan(new URL(entry.name + "/", folder)); continue; }
      if (!/\.tsx?$/.test(entry.name) || /\.(test|spec)\./.test(entry.name)) continue;
      const source = readFileSync(url, "utf8");
      const tree = ts.createSourceFile(url.pathname, source, ts.ScriptTarget.Latest, true);
      function visit(node: ts.Node) {
        if (ts.isJsxText(node) || ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
          // Exempt syntax positions for keys, never exact text used as a label.
          const parent = node.parent;
          if (ts.isPropertyAssignment(parent) && parent.name === node) return;
          if (ts.isPropertySignature(parent) && parent.name === node) return;
          if (ts.isElementAccessExpression(parent) && parent.argumentExpression === node) return;
          if (ts.isCallExpression(parent) && parent.arguments[0] === node && ts.isPropertyAccessExpression(parent.expression) && ["get", "set", "delete"].includes(parent.expression.name.text)) return;
          if (bannedWords.test(node.text)) violations.push(`${entry.name}: ${node.text}`);
        } else ts.forEachChild(node, visit);
      }
      visit(tree);
    }
  }
  scan(root);
  expect(violations).toEqual([]);
});
