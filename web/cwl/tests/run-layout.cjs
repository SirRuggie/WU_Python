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
  process.exit(2);
}
const port = 8952;
const python =
  process.env.WU_TEST_PYTHON || path.join(root, ".venv/bin/python");
if (!existsSync(python)) {
  console.error(
    `Cannot run test:layout: Python interpreter not found at ${python}. Set WU_TEST_PYTHON to the backend test environment.`,
  );
  rmSync(temp, { recursive: true, force: true });
  process.exit(1);
}

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
    if (code) {
      process.exitCode = code;
      server.kill();
      return;
    }
    const tourPort = 8976;
    const tourServer = spawn(
      python,
      [
        "-I",
        path.join(__dirname, "fixtures/tour_deadline.py"),
        path.join(root, "web/cwl/dist"),
        String(tourPort),
      ],
      {
        env: { PATH: process.env.PATH, HOME: temp, WU_FIXTURE_BACKEND: root },
        stdio: ["ignore", "ignore", "inherit"],
      },
    );
    const runTour = async () => {
      try {
        await new Promise((resolve) => setTimeout(resolve, 300));
        let ready = false;
        for (let i = 0; i < 100; i++) {
          if (tourServer.exitCode !== null)
            throw new Error("Tour fixture exited before readiness");
          try {
            ready = (await fetch(`http://127.0.0.1:${tourPort}/api/cwl/config`))
              .ok;
          } catch {
            /* starting */
          }
          if (ready) break;
          await new Promise((resolve) => setTimeout(resolve, 200));
        }
        if (!ready) throw new Error("Tour fixture startup timed out");
        for (const script of [
          "member-tour.browser.cjs",
          "member-tour-cleanup.browser.cjs",
        ]) {
          const code = await new Promise((resolve) => {
            const child = spawn(
              process.execPath,
              [path.join(__dirname, script), String(tourPort)],
              { stdio: "inherit", env: process.env },
            );
            child.on("exit", resolve);
          });
          if (code) {
            process.exitCode = code;
            break;
          }
        }
      } catch (error) {
        console.error(error);
        process.exitCode = 1;
      } finally {
        tourServer.kill();
        server.kill();
      }
    };
    void runTour();
  });
});
server.on("exit", (code) => {
  clearTimeout(timer);
  if (!started) process.exitCode = code || 1;
  rmSync(temp, { recursive: true, force: true });
});
process.on("SIGINT", () => server.kill());
