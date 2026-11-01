/* Real profile adapter + approximate Discord builders. All data is isolated. */
const { spawn, spawnSync } = require("node:child_process");
const { mkdtempSync, writeFileSync, readFileSync, rmSync } = require("node:fs");
const { createServer } = require("node:http");
const path = require("node:path");
const os = require("node:os");
const web = path.resolve(__dirname, ".."),
  root = path.resolve(web, "../..");
const python =
  process.env.WU_TEST_PYTHON || path.join(root, ".venv/bin/python");
const port = Number(process.env.WU_LAYOUT_PROFILE_PORT || 8915);
if (port < 8900 || port > 8999)
  throw new Error("Use an isolated profile fixture port");
const probe = spawnSync(python, [
  "-I",
  "-c",
  "import socket,sys;s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[1])));s.close()",
  String(port),
]);
if (probe.status !== 0)
  throw new Error(`Profile fixture port ${port} occupied`);
const temp = mkdtempSync(path.join(os.tmpdir(), "wu-profile-layout-"));
const fixture = spawn(
  python,
  [
    "-I",
    path.join(__dirname, "fixtures/member_profiles.py"),
    path.join(web, "dist"),
    String(port),
  ],
  {
    env: { PATH: process.env.PATH, HOME: temp, WU_FIXTURE_BACKEND: root },
    stdio: ["ignore", "pipe", "inherit"],
  },
);
let ready = false,
  buffer = "";
const readyPromise = new Promise((resolve, reject) => {
  const timer = setTimeout(
    () => reject(new Error("Profile fixture readiness timed out")),
    30000,
  );
  fixture.stdout.on("data", (data) => {
    buffer += data;
    for (const line of buffer.split("\n").slice(0, -1)) {
      if (!ready && line.includes('"ready": true')) {
        ready = true;
        clearTimeout(timer);
        resolve();
      }
    }
    buffer = buffer.slice(buffer.lastIndexOf("\n") + 1);
  });
  fixture.on("error", (error) => {
    clearTimeout(timer);
    reject(error);
  });
  fixture.on("exit", () => {
    clearTimeout(timer);
    if (!ready) reject(new Error("Profile fixture exited before ready"));
  });
});
function run(command, args, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: web, env, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0
        ? resolve()
        : reject(new Error(`${path.basename(args[0])} exited ${code}`)),
    );
  });
}
(async () => {
  let server;
  try {
    await readyPromise;
    await run(
      process.execPath,
      [path.join(__dirname, "compare-timezones.browser.cjs"), String(port)],
      {
        ...process.env,
        WU_PROFILE_EXPECTED: "1",
        WU_TIMEZONE_OUTPUT:
          process.env.WU_PROFILE_OUTPUT || "/tmp/wu-member-profile-layout",
      },
    );
    const panels = spawnSync(
      python,
      ["-I", path.join(__dirname, "fixtures/warrior_profile_panels.py")],
      { encoding: "utf8", env: { PATH: process.env.PATH, HOME: temp } },
    );
    if (panels.status !== 0)
      throw new Error("Warrior panel builder failed: " + panels.stderr);
    JSON.parse(panels.stdout);
    writeFileSync(path.join(temp, "panels.json"), panels.stdout);
    const dist = path.join(temp, "dist");
    const config = path.join(temp, "vite.config.mjs");
    writeFileSync(
      config,
      "export default " +
        JSON.stringify({
          root: web,
          resolve: {
            alias: { "@warrior-panels": path.join(temp, "panels.json") },
          },
          build: {
            outDir: dist,
            emptyOutDir: true,
            rollupOptions: {
              input: path.join(
                __dirname,
                "fixtures/warrior-profile-preview.html",
              ),
            },
          },
        }),
    );
    await run(process.execPath, [
      path.join(web, "node_modules/vite/bin/vite.js"),
      "build",
      "--config",
      config,
    ]);
    server = createServer((req, res) => {
      const file = path.resolve(
        dist,
        "." + new URL(req.url, "http://localhost").pathname,
      );
      if (!file.startsWith(dist + path.sep)) {
        res.writeHead(403).end();
        return;
      }
      try {
        res
          .writeHead(200, {
            "Content-Type": file.endsWith(".js")
              ? "application/javascript"
              : file.endsWith(".css")
                ? "text/css"
                : "text/html",
          })
          .end(readFileSync(file));
      } catch {
        res.writeHead(404).end();
      }
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    await run(process.execPath, [
      path.join(__dirname, "warrior-profile-preview.browser.cjs"),
      String(server.address().port),
    ]);
  } finally {
    fixture.kill();
    if (server) await new Promise((resolve) => server.close(resolve));
    rmSync(temp, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
