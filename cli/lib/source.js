"use strict";

// Locate the Cascadia source tree (which holds the compose files + Dockerfiles
// the launcher orchestrates). Three cases, in order:
//   1. $CASCADIA_HOME points at a checkout.
//   2. We're running inside a checkout (walk up from cwd, then from this file).
//   3. Cold `npx` with no checkout → git clone (or pull) into ~/.cascadia/checkout.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { step, ok, warn, capture, commandExists } = require("./util");

const MARKER = path.join("deploy", "compose", "docker-compose.demo.yml");
const DEFAULT_REPO =
  process.env.CASCADIA_REPO || "https://github.com/cxk280/cascadia.git";

function isCheckout(dir) {
  return fs.existsSync(path.join(dir, MARKER));
}

function walkUp(start) {
  let dir = start;
  // Bound the climb so we never loop forever on odd filesystems.
  for (let i = 0; i < 40; i++) {
    if (isCheckout(dir)) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

// Resolve (and if needed, fetch) the source tree. Returns its absolute path.
async function resolveSource() {
  if (process.env.CASCADIA_HOME) {
    const home = path.resolve(process.env.CASCADIA_HOME);
    if (isCheckout(home)) return home;
    throw new Error(
      `CASCADIA_HOME=${home} is not a Cascadia checkout (missing ${MARKER})`
    );
  }

  const fromCwd = walkUp(process.cwd());
  if (fromCwd) return fromCwd;

  const fromSelf = walkUp(path.resolve(__dirname, ".."));
  if (fromSelf) return fromSelf;

  // Cold run: clone (or update) into a cache dir.
  if (!commandExists("git")) {
    throw new Error(
      "git is required to fetch Cascadia on first run (or run from a clone, or set CASCADIA_HOME)."
    );
  }
  const cache = path.join(os.homedir(), ".cascadia", "checkout");
  if (isCheckout(cache)) {
    step("Updating cached Cascadia source…");
    const r = capture("git", ["-C", cache, "pull", "--ff-only"]);
    if (r.code !== 0) warn("git pull failed; using the existing cached copy.");
    return cache;
  }
  step(`Fetching Cascadia source → ${cache}`);
  fs.mkdirSync(path.dirname(cache), { recursive: true });
  const r = capture("git", ["clone", "--depth", "1", DEFAULT_REPO, cache]);
  if (r.code !== 0) {
    throw new Error(`git clone failed:\n${r.stderr || r.stdout}`);
  }
  if (!isCheckout(cache)) {
    throw new Error(`cloned repo at ${cache} is missing ${MARKER}`);
  }
  ok("Source ready.");
  return cache;
}

module.exports = { resolveSource, DEFAULT_REPO };
