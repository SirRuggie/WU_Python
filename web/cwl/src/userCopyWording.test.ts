// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { expect, it } from "vitest";

const sourceRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(sourceRoot, "../../..");
const forbidden = /\bthe bot\b|\bbot['’]s\b/i;
type Literal = { line: number; text: string };
type Exception = { file: string; text: string; reason: string };
// Exact file + decoded literal only. Each code-only exception needs a reason.
const allowlist: readonly Exception[] = [];
const entity = /&(?:#[xX]?[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);/;
const decodedJsx = new Map<string, string>();

function compiledJsxValue(source: string, attribute = false): string {
  const key = `${attribute}:${source}`;
  const saved = decodedJsx.get(key);
  if (saved !== undefined) return saved;
  const output = ts.transpileModule(source, {
    fileName: "wording-fixture.tsx",
    compilerOptions: { target: ts.ScriptTarget.ESNext, jsx: ts.JsxEmit.React },
  }).outputText;
  const tree = ts.createSourceFile(
    "wording-fixture.js",
    output,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.JS,
  );
  let value = "";
  const visit = (node: ts.Node) => {
    if (
      attribute &&
      ts.isPropertyAssignment(node) &&
      node.name.getText(tree) === "title" &&
      ts.isStringLiteral(node.initializer)
    ) {
      value = node.initializer.text;
    } else if (
      !attribute &&
      ts.isCallExpression(node) &&
      node.arguments.length > 2 &&
      ts.isStringLiteral(node.arguments[2])
    ) {
      value = node.arguments[2].text;
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  decodedJsx.set(key, value);
  return value;
}

function literals(source: string, file = "fixture.tsx"): Literal[] {
  const tree = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found: Literal[] = [];
  const record = (node: ts.Node, text: string) => {
    if (text)
      found.push({
        line: tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1,
        text,
      });
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      record(
        node,
        entity.test(node.text)
          ? compiledJsxValue(`const sample = <p>${node.text}</p>;`)
          : node.text.replace(/\s+/g, " ").trim(),
      );
      return;
    }
    if (ts.isStringLiteral(node)) {
      record(
        node,
        ts.isJsxAttribute(node.parent) && entity.test(node.text)
          ? compiledJsxValue(
              `const sample = <p title=${node.getText(tree)} />;`,
              true,
            )
          : node.text,
      );
      return;
    }
    if (ts.isNoSubstitutionTemplateLiteral(node)) {
      record(node, node.text);
      return;
    }
    if (ts.isTemplateExpression(node)) {
      record(node.head, node.head.text);
      for (const span of node.templateSpans) {
        visit(span.expression);
        record(span.literal, span.literal.text);
      }
      return;
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  return found;
}

function violations(
  file: string,
  values: Literal[],
  exceptions: readonly Exception[],
) {
  const failures: string[] = [];
  const used = new Set<string>();
  for (const { line, text } of values) {
    if (!forbidden.test(text)) continue;
    const exception = exceptions.find(
      (item) => item.file === file && item.text === text,
    );
    if (exception) {
      if (!exception.reason.trim())
        throw new Error("Every code-only exception needs a reason.");
      used.add(JSON.stringify([file, text]));
    } else failures.push(`${file}:${line}: ${JSON.stringify(text)}`);
  }
  return { failures, used };
}

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((item) => {
    const path = resolve(directory, item.name);
    return item.isDirectory()
      ? files(path)
      : /\.tsx?$/.test(item.name) && !item.name.includes(".test.")
        ? [path]
        : [];
  });
}

it("rejects forbidden user-facing frontend strings and JSX using the lockfile compiler", () => {
  const failures: string[] = [];
  const used = new Set<string>();
  for (const path of files(sourceRoot)) {
    const file = relative(repositoryRoot, path).replaceAll("\\", "/");
    const result = violations(
      file,
      literals(readFileSync(path, "utf8"), path),
      allowlist,
    );
    failures.push(...result.failures);
    result.used.forEach((key) => used.add(key));
  }
  expect(failures).toEqual([]);
  expect([...used].sort()).toEqual(
    allowlist.map((item) => JSON.stringify([item.file, item.text])).sort(),
  );
  for (const item of allowlist) {
    expect(
      item.file.startsWith("web/cwl/src/") &&
        forbidden.test(item.text) &&
        !!item.reason.trim(),
    ).toBe(true);
  }
});

const cases: [string, number][] = [
  ["<p>https://example.invalid: the bot</p>", 1],
  ["<p>Don't worry</p>; // the bot is internal-only comment", 0],
  ["const x = `ok ${/* the bot comment */ 1}`;", 0],
  ["const x = <div>{/* the bot comment */}<p>the bot</p></div>;", 1],
  ['const x = /https?:\\/\\/the bot/; const y="the bot";', 1],
  ["const x = <><p>the bot</p></>;", 1],
  ["api<Foo>(); // the bot comment", 0],
  ["const x = <T extends Foo>(a: T) => a; // the bot comment", 0],
  ['const x = "https://example.invalid/the bot"; // internal', 1],
  ['const x = <p title="extends">https://x/the bot</p>;', 1],
  ["const x = `outer ${`inner ${/* the bot comment */ 1}`}`;", 0],
  ['const x = <p>{[{x: "the bot"}].map(v => <span>{v.x}</span>)}</p>;', 1],
  ["const pattern = /* note */ /the bot/;", 0],
  ["const element = /* note */ <p>the bot</p>;", 1],
  [
    "const value = async () => await <p>https://example.invalid: the bot</p>;",
    1,
  ],
  ["const value = void <p>https://example.invalid: the bot</p>;", 1],
  ["const value = typeof <p>https://example.invalid: the bot</p>;", 1],
  ['const x = "the \\u0062ot"; const y = <p>the&#32;bot</p>;', 2],
  ['const x = <p title="the&#32;bot" />;', 1],
];
it.each(cases)("handles real TS/TSX token contexts: %s", (source, expected) => {
  expect(
    literals(source).filter((item) => forbidden.test(item.text)),
  ).toHaveLength(expected);
});

it("applies only exact file and decoded literal exceptions", () => {
  const file = "web/cwl/src/internal.ts";
  const values = literals(
    'const a = "the bot code"; const b = "the bot code extra";',
    "fixture.ts",
  );
  const exceptions = [
    { file, text: "the bot code", reason: "A diagnostic protocol fixture." },
  ];
  expect(violations(file, values, exceptions).failures).toHaveLength(1);
  expect(
    violations("web/cwl/src/other.ts", values, exceptions).failures,
  ).toHaveLength(2);
  expect(() =>
    violations(file, values, [{ ...exceptions[0], reason: "" }]),
  ).toThrow("needs a reason");
});

it("reports original source line numbers", () => {
  expect(
    literals(
      'const safe = "ready";\nconst bad = "the bot";',
      "fixture.ts",
    ).find((item) => forbidden.test(item.text))?.line,
  ).toBe(2);
});
