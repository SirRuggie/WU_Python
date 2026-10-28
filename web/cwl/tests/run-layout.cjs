/* npm run test:layout: isolated fixture, working-tree backend and frontend, no live services. */
const { spawn } = require("node:child_process");
const { mkdtempSync, existsSync, rmSync } = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const root = path.resolve(__dirname, "../../..");
const temp = mkdtempSync(path.join(os.tmpdir(), "wu-card-layout-"));
const chrome = process.env.CHROME_PATH || "/usr/bin/google-chrome";
if (!existsSync(chrome)) {
  console.log(
    `SKIP test:layout: Chrome not found at ${chrome}. Set CHROME_PATH to an installed Chrome.`,
  );
  rmSync(temp, { recursive: true, force: true });
  process.exit(0);
}
const port = 8952;
const python =
  process.env.WU_TEST_PYTHON || path.join(root, ".venv/bin/python");
const server = spawn(
  python,
  [
    "-I",
    path.join(__dirname, "fixtures/player_cards.py"),
    path.join(root, "web/cwl/dist"),
    String(port),
  ],
  {
    env: { PATH: process.env.PATH, HOME: temp, WU_FIXTURE_BACKEND: root },
    stdio: ["ignore", "pipe", "inherit"],
  },
);
let started = false;
const timer = setTimeout(() => {
  console.error("Fixture startup timed out");
  server.kill();
  process.exitCode = 1;
}, 30000);
server.stdout.on("data", (chunk) => {
  if (started || !chunk.toString().includes('"ready": true')) return;
  started = true;
  clearTimeout(timer);
  const test = spawn(
    process.execPath,
    [path.join(__dirname, "player-card-line2.browser.cjs"), String(port)],
    { stdio: "inherit", env: process.env },
  );
  test.on("exit", (code) => {
    process.exitCode = code || 0;
    server.kill();
  });
});
server.on("exit", (code) => {
  clearTimeout(timer);
  if (!started) process.exitCode = code || 1;
  rmSync(temp, { recursive: true, force: true });
});
process.on("SIGINT", () => server.kill());
