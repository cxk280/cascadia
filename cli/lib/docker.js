"use strict";

// Docker / docker-compose preflight + invocation helpers.

const path = require("node:path");
const { capture, run, commandExists, fail, warn } = require("./util");

// Returns {cmd, base} for running compose, or null if unavailable.
function composeRunner() {
  if (commandExists("docker", ["compose", "version"])) {
    return { cmd: "docker", base: ["compose"] };
  }
  if (commandExists("docker-compose")) {
    return { cmd: "docker-compose", base: [] };
  }
  return null;
}

// Verify Docker is installed AND the daemon is reachable. Returns true/false.
function dockerReady() {
  if (!commandExists("docker")) {
    fail("Docker is not installed. Install Docker Desktop / Engine: https://docs.docker.com/get-docker/");
    return false;
  }
  const info = capture("docker", ["info"]);
  if (info.code !== 0) {
    fail("Docker is installed but the daemon isn't reachable. Is Docker running?");
    return false;
  }
  if (!composeRunner()) {
    fail("docker compose plugin not found. Install Compose v2: https://docs.docker.com/compose/install/");
    return false;
  }
  return true;
}

// Run a compose command for a given file + project, inheriting stdio.
// `sourceDir` is the Cascadia checkout root; `relFile` is resolved against it,
// UNLESS it's already absolute (the bundled-compose pull path passes an absolute
// path with no checkout). When the args include `--build` we force compose's
// `--progress plain` renderer: the default `tty` renderer redraws the per-service
// status block in place via cursor-up escapes, which flickers badly during the
// long multi-image build. `plain` is linear/append-only — no flicker.
function compose(sourceDir, relFile, project, args, opts = {}) {
  const runner = composeRunner();
  if (!runner) {
    warn("docker compose unavailable");
    return Promise.resolve(127);
  }
  const file = path.isAbsolute(relFile) ? relFile : path.join(sourceDir, relFile);
  const cwd = sourceDir || path.dirname(file);
  const globals = args.includes("--build") ? ["--progress", "plain"] : [];
  const argv = [...runner.base, ...globals, "-f", file, "-p", project, ...args];
  return run(runner.cmd, argv, { cwd, ...opts });
}

const DEMO_FILE = path.join("deploy", "compose", "docker-compose.demo.yml");
const LIVE_FILE = path.join("deploy", "compose", "docker-compose.full.yml");
const DEMO_PROJECT = "cascadia-demo";
const LIVE_PROJECT = "cascadia-live";

// The demo compose file is also bundled INTO the published npm package (see
// scripts/sync-assets.js + the `prepack` hook) so a cold `npx cascadia-gateway
// demo` can pull prebuilt images with no git clone. Resolved absolute so it
// works regardless of cwd.
const BUNDLED_DEMO_FILE = path.resolve(__dirname, "..", "assets", "docker-compose.demo.yml");

function bundledDemoExists() {
  return require("node:fs").existsSync(BUNDLED_DEMO_FILE);
}

module.exports = {
  dockerReady,
  compose,
  DEMO_FILE,
  LIVE_FILE,
  DEMO_PROJECT,
  LIVE_PROJECT,
  BUNDLED_DEMO_FILE,
  bundledDemoExists,
};
