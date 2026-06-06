"use strict";

// Tiny shared helpers — no third-party deps, Node 18+ built-ins only.

const net = require("node:net");
const { spawn, spawnSync } = require("node:child_process");

const useColor = process.stdout.isTTY && process.env.NO_COLOR === undefined;
const paint = (code, s) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : s);
const c = {
  bold: (s) => paint("1", s),
  dim: (s) => paint("2", s),
  red: (s) => paint("31", s),
  green: (s) => paint("32", s),
  yellow: (s) => paint("33", s),
  cyan: (s) => paint("36", s),
};

const log = (msg = "") => process.stdout.write(`${msg}\n`);
const step = (msg) => log(`${c.cyan("›")} ${msg}`);
const ok = (msg) => log(`${c.green("✓")} ${msg}`);
const warn = (msg) => log(`${c.yellow("!")} ${msg}`);
const fail = (msg) => log(`${c.red("✗")} ${msg}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Run a command inheriting stdio (user sees live output). Resolves with the
// exit code; never rejects.
function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { stdio: "inherit", ...opts });
    child.on("error", () => resolve(127));
    child.on("close", (code) => resolve(code == null ? 1 : code));
  });
}

// Run a command capturing output (for probes). Returns {code, stdout, stderr}.
function capture(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { encoding: "utf8", ...opts });
  return {
    code: r.status == null ? 1 : r.status,
    stdout: r.stdout || "",
    stderr: r.stderr || "",
    error: r.error,
  };
}

// True if `cmd --version`-style probe succeeds.
function commandExists(cmd, probeArgs = ["--version"]) {
  const r = capture(cmd, probeArgs);
  return r.code === 0 && !r.error;
}

// Would Docker fail to publish this TCP port? Test-bind the SAME address Docker
// publishes on — 0.0.0.0 (the IPv4 wildcard) — not 127.0.0.1. A process holding
// the wildcard (e.g. a dev server on `*:3000`) doesn't block a loopback-specific
// bind, so a 127.0.0.1 probe reports the port free while `docker compose up`
// still hits "bind: address already in use". Matching Docker's bind address
// makes the port-fallback actually fall back.
function portInUse(port) {
  return new Promise((resolve) => {
    const srv = net
      .createServer()
      .once("error", () => resolve(true))
      .once("listening", () => srv.close(() => resolve(false)))
      .listen(port, "0.0.0.0");
  });
}

// Return `preferred` if free, else the next free port above it (up to +20).
async function pickPort(preferred) {
  for (let p = preferred; p < preferred + 20; p++) {
    if (!(await portInUse(p))) return p;
  }
  throw new Error(`no free port near ${preferred}`);
}

// Poll an HTTP URL until it answers (any status) or the deadline passes.
async function waitForHttp(url, { timeoutMs = 180000, intervalMs = 1500 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (res.status) return true;
    } catch {
      /* not up yet */
    }
    await sleep(intervalMs);
  }
  return false;
}

module.exports = {
  c,
  log,
  step,
  ok,
  warn,
  fail,
  sleep,
  run,
  capture,
  commandExists,
  portInUse,
  pickPort,
  waitForHttp,
};
