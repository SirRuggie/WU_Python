/* Disposable fixture; no fixed preview port or production configuration. */
const { spawn } = require("node:child_process");
const { mkdtempSync, rmSync } = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../../..");
const temp = mkdtempSync(
  path.join(require("node:os").tmpdir(), "wu-announcement-polish-layout-"),
);
const server = spawn(
  process.env.WU_TEST_PYTHON || path.join(root, ".venv/bin/python"),
  [
    "-I",
    path.join(__dirname, "fixtures/announcement_images.py"),
    path.join(root, "web/cwl/dist"),
    "0",
  ],
  {
    env: {
      PATH: process.env.PATH,
      HOME: temp,
      WU_FIXTURE_BACKEND: root,
      PYTHONDONTWRITEBYTECODE: "1",
    },
    stdio: ["ignore", "pipe", "inherit"],
  },
);
let child,
  ready = false,
  buffered = "";
const timer = setTimeout(() => {
  console.error("Announcement polish fixture timed out");
  process.exitCode = 1;
  server.kill();
}, 30000);
server.stdout.on("data", (chunk) => {
  buffered += chunk;
  for (const line of buffered.split("\n").slice(0, -1)) {
    if (ready || !line.includes('"ready": true')) continue;
    ready = true;
    clearTimeout(timer);
    const { port } = JSON.parse(line);
    child = spawn(
      process.execPath,
      [
        path.join(__dirname, "announcement-polish-send.browser.cjs"),
        String(port),
      ],
      {
        stdio: "inherit",
        env: {
          ...process.env,
          WU_POLISH_EVIDENCE: path.join(
            root,
            ".local/announcement-polish-layout",
          ),
        },
      },
    );
    child.on("error", (e) => {
      console.error(e);
      process.exitCode = 1;
      server.kill();
    });
    child.on("exit", (code) => {
      process.exitCode = code === 0 ? 0 : code || 1;
      server.kill();
    });
  }
  buffered = buffered.slice(buffered.lastIndexOf("\n") + 1);
});
server.on("error", (e) => {
  console.error(e);
  clearTimeout(timer);
  process.exitCode = 1;
  rmSync(temp, { recursive: true, force: true });
});
server.on("exit", (code) => {
  clearTimeout(timer);
  if (!ready) process.exitCode = code || 1;
  rmSync(temp, { recursive: true, force: true });
});
process.on("SIGINT", () => {
  child?.kill();
  server.kill();
});
process.on("SIGTERM", () => {
  child?.kill();
  server.kill();
});
