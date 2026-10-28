import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
it("announcement and image tests never use browser-native confirmation", () => {
  for (const file of ["ManageBridgeWorkspace.tsx", "ClanRosterImages.tsx"]) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    expect(source).not.toContain("window.confirm");
    expect(source).toContain("<ConfirmDialog");
  }
});
