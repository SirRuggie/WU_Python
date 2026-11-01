/* Isolated sample transport; exercises the real page, not live Discord delivery. */
const { spawn } = require("node:child_process");
const { createServer } = require("node:net");
const { mkdtempSync, rmSync } = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const web = path.resolve(__dirname, ".."),
  root = path.resolve(web, "../.."),
  python = process.env.WU_TEST_PYTHON || path.join(root, ".venv/bin/python"),
  port = Number(process.env.WU_LAYOUT_MEMBER_ZONES_PORT || 8916);
if (port < 8900 || port > 8999) throw new Error("Use an isolated fixture port");
const home = mkdtempSync(path.join(os.tmpdir(), "wu-member-zones-ui-"));
async function free() {
  await new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => server.close(resolve));
  });
}
(async () => {
  let fixture;
  try {
    await free();
    fixture = spawn(
      python,
      [
        "-I",
        path.join(__dirname, "fixtures/member_timezone_dashboard.py"),
        path.join(web, "dist"),
        String(port),
      ],
      {
        cwd: root,
        env: { PATH: process.env.PATH, HOME: home, WU_FIXTURE_BACKEND: root },
        stdio: ["ignore", "pipe", "inherit"],
      },
    );
    await new Promise((resolve, reject) => {
      let text = "";
      const timer = setTimeout(
        () => reject(new Error("Fixture readiness timeout")),
        30000,
      );
      fixture.stdout.on("data", (chunk) => {
        text += chunk;
        if (text.includes('"ready": true')) {
          clearTimeout(timer);
          resolve();
        }
      });
      fixture.once("error", reject);
      fixture.once("exit", (code) => {
        clearTimeout(timer);
        reject(new Error(`Fixture exited${code}`));
      });
    });
    await new Promise((resolve, reject) => {
      const child = spawn(
        process.execPath,
        [path.join(__dirname, "member-timezones.browser.cjs"), String(port)],
        { cwd: web, env: process.env, stdio: "inherit" },
      );
      child.once("error", reject);
      child.once("exit", (code) =>
        code === 0 ? resolve() : reject(new Error(`Browser exited${code}`)),
      );
    });
  } finally {
    if (fixture) {
      fixture.kill();
      await new Promise((resolve) => fixture.once("exit", resolve));
    }
    rmSync(home, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
