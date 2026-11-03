/* Disconnected, ephemeral fixtures. No existing preview or production port is reused. */
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs"),
  path = require("node:path");
const root = path.resolve(__dirname, "../../..");
const common = execFileSync(
  "git",
  ["rev-parse", "--path-format=absolute", "--git-common-dir"],
  { cwd: root, encoding: "utf8" },
).trim();
const python =
  process.env.WU_TEST_PYTHON ||
  path.join(path.dirname(common), ".venv/bin/python");
const chrome = process.env.CHROME_PATH || "/usr/bin/google-chrome";
const output = path.resolve(
  process.env.WU_LAYOUT_OUTPUT ||
    path.join(root, ".local", "less-on-top-layout"),
);
const dist = path.resolve(
  process.env.WU_LAYOUT_DIST || path.join(root, "web/cwl/dist"),
);
for (const file of [python, chrome, path.join(dist, "index.html")])
  if (!fs.existsSync(file))
    throw new Error("Missing layout prerequisite: " + file);
if (path.relative(path.join(root, ".local"), output).startsWith(".."))
  throw new Error("Layout artifacts must stay in workspace .local");
fs.mkdirSync(output, { recursive: true });
const temp = fs.mkdtempSync(path.join(output, "owned-tmp-"));
const alias = "/tmp/wu-density-" + process.pid;
fs.symlinkSync(temp, alias);
const owned = [];
const env = {
  PATH: process.env.PATH,
  HOME: process.env.HOME,
  TMPDIR: alias,
  PYTHONDONTWRITEBYTECODE: "1",
  WU_FIXTURE_BACKEND: root,
  PRANK_ENABLED: "false",
};
function fixture(role) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      ["-I", path.join(__dirname, "fixtures/less_on_top.py"), role, dist],
      { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    owned.push(child);
    const log = fs.createWriteStream(path.join(output, role + "-fixture.log"));
    let buffer = "",
      ready = false;
    const timer = setTimeout(
      () => reject(new Error(role + " fixture startup timeout")),
      30000,
    );
    child.stdout.on("data", (chunk) => {
      log.write(chunk);
      buffer += chunk;
      let i;
      while ((i = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, i);
        buffer = buffer.slice(i + 1);
        try {
          const value = JSON.parse(line);
          if (value.less_on_top_ready) {
            ready = true;
            clearTimeout(timer);
            resolve("http://127.0.0.1:" + value.port);
          }
        } catch {}
      }
    });
    child.stderr.on("data", (chunk) => log.write(chunk));
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      log.end();
      if (!ready) reject(new Error(role + " fixture exited " + code));
    });
  });
}
async function stop(child) {
  if (child.exitCode !== null || child.signalCode) return;
  const exited = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGTERM");
  await Promise.race([
    exited,
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  if (child.exitCode === null && !child.signalCode) child.kill("SIGKILL");
}
(async () => {
  try {
    const staff = await fixture("staff"),
      member = await fixture("member");
    const child = spawn(
      process.execPath,
      [
        path.join(
          __dirname,
          process.env.WU_LAYOUT_SUITE === "same-look"
            ? "same-look.browser.cjs"
            : "less-on-top.browser.cjs",
        ),
      ],
      {
        cwd: root,
        env: {
          ...env,
          CHROME_PATH: chrome,
          NODE_COMPILE_CACHE: path.join(temp, "node-cache"),
          WU_LESS_STAFF_URL: staff,
          WU_LESS_MEMBER_URL: member,
          WU_LAYOUT_OUTPUT: output,
          WU_LAYOUT_PHASE: process.env.WU_LAYOUT_PHASE || "candidate",
        },
        stdio: "inherit",
      },
    );
    const code = await new Promise((resolve, reject) => {
      child.once("exit", resolve);
      child.once("error", reject);
    });
    if (code) process.exitCode = code;
  } finally {
    await Promise.all(owned.map(stop));
    if (fs.lstatSync(alias).isSymbolicLink() && fs.readlinkSync(alias) === temp)
      fs.unlinkSync(alias);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
