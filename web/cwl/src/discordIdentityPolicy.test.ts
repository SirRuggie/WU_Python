import { expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
function sourceFiles(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? sourceFiles(join(folder, entry.name))
      : /\.(tsx|ts)$/.test(entry.name) &&
          !entry.name.includes(".test.") &&
          !entry.name.includes("Preview")
        ? [join(folder, entry.name)]
        : [],
  );
}
it("blocks Discord plus a raw identity as a primary label in dashboard source", () => {
  const offenders = sourceFiles(
    fileURLToPath(new URL(".", import.meta.url)),
  ).filter((file) =>
    /Discord\s+\$\{[^}]*\b(?:discordId|discord_id|userId|user_id|member\.id)\b/.test(
      readFileSync(file, "utf8"),
    ),
  );
  expect(offenders).toEqual([]);
});
