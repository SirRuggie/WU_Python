/* Build and serve the browser-only fixture: no API proxy or live backend. */
const { spawnSync, spawn } = require("node:child_process");
const { mkdtempSync, writeFileSync, readFileSync, rmSync } = require("node:fs");
const { createServer } = require("node:http");
const path = require("node:path");
const os = require("node:os");
const root = path.resolve(__dirname, "..");
const temp = mkdtempSync(path.join(os.tmpdir(), "wu-strikes-layout-"));
const dist = path.join(temp, "dist");
const config = path.join(temp, "vite.config.mjs");
writeFileSync(
  config,
  `export default ${JSON.stringify({ root, build: { outDir: dist, emptyOutDir: true, rollupOptions: { input: path.join(root, "strikes-preview.html") } }, server: { host: "127.0.0.1", proxy: {} } })}`,
);
const build = spawnSync(
  process.execPath,
  [
    path.join(root, "node_modules/vite/bin/vite.js"),
    "build",
    "--config",
    config,
  ],
  { stdio: "inherit" },
);
if (build.status !== 0) {
  rmSync(temp, { recursive: true, force: true });
  process.exit(build.status || 1);
}
const server = createServer((req, res) => {
  const relative = new URL(req.url, "http://localhost").pathname;
  const file = path.resolve(dist, "." + relative);
  if (!file.startsWith(dist + path.sep)) {
    res.writeHead(403).end();
    return;
  }
  try {
    const type = file.endsWith(".js")
      ? "text/javascript"
      : file.endsWith(".css")
        ? "text/css"
        : file.endsWith(".html")
          ? "text/html"
          : "application/octet-stream";
    res.writeHead(200, { "Content-Type": type }).end(readFileSync(file));
  } catch {
    res.writeHead(404).end();
  }
});
server.listen(0, "127.0.0.1", () => {
  const test = spawn(
    process.execPath,
    [
      path.join(__dirname, "strikes-ux.browser.cjs"),
      String(server.address().port),
    ],
    { stdio: "inherit", env: process.env },
  );
  test.on("exit", (code) => {
    process.exitCode = code || 0;
    server.close();
    rmSync(temp, { recursive: true, force: true });
  });
});
