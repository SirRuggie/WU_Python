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
function rawIdentityLabel(source: string) {
  return /Discord\s+(?:member\s*·\s*)?(?:\$\{[^}]+\}|\{\s*[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*\}|[1-9][0-9]{14,21})/.test(
    source,
  );
}
it("rejects raw identity labels for nested template and JSX values and real IDs", () => {
  for (const source of [
    "`Discord ${item.id}`",
    "<small>Discord {id}</small>",
    "<small>Discord member · {item.id}</small>",
    "<strong>Discord 700731132936978456</strong>",
  ])
    expect(rawIdentityLabel(source)).toBe(true);
  for (const source of [
    "<summary>Discord details</summary>",
    "Discord ID: <code>{userId}</code>",
    "<DiscordIdentity userId={item.id}/>",
  ])
    expect(rawIdentityLabel(source)).toBe(false);
});
it("blocks Discord plus a raw identity as a primary label in dashboard source", () => {
  const offenders = sourceFiles(
    fileURLToPath(new URL(".", import.meta.url)),
  ).filter((file) => rawIdentityLabel(readFileSync(file, "utf8")));
  expect(offenders).toEqual([]);
});
