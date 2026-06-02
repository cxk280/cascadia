#!/usr/bin/env node
"use strict";

// `cascadia` — one-command launcher for the Cascadia LLM cascade gateway.
//
//   cascadia demo     keyless, zero-cost demo of the live closed loop (Docker)
//   cascadia up       self-host against real providers (BYO keys)
//   cascadia down     stop + wipe the stack       [--live] [--all]
//   cascadia logs     tail stack logs             [--live] [service…]
//   cascadia doctor   preflight checks
//
// Built on Node 18+ built-ins only — no dependencies.

const { parseArgs } = require("node:util");
const { c, log, fail } = require("../lib/util");
const { cmdDemo, cmdUp, cmdDown, cmdLogs, cmdDoctor } = require("../lib/commands");

const HELP = `${c.bold("cascadia")} — self-hostable LLM cascade gateway

${c.bold("Usage:")} cascadia <command> [options]

${c.bold("Commands:")}
  demo            Keyless, zero-cost demo of the live cost/quality closed loop.
                  Only needs Docker. Builds images on first run, then opens a
                  dashboard at http://localhost:3000.
                    --no-build      reuse existing images (skip the build)
                    --no-traffic    don't auto-drive demo traffic
                    --traffic N     drive N requests (default 60)
  up | start      Self-host against REAL providers (spends API budget). Prompts
                  for OpenAI + Anthropic keys (or reads them from the env).
                    --no-build      reuse existing images
  down            Stop the stack and remove its volume.
                    --live          target the self-host stack instead of demo
                    --all           tear down both
  logs            Tail stack logs (Ctrl-C to stop).
                    --live          the self-host stack
  doctor          Check Docker / ports / source before running.

${c.bold("Environment:")}
  CASCADIA_HOME   path to a Cascadia checkout (else auto-detected or cloned)
  CASCADIA_REPO   git URL to clone on a cold run
  CASCADIA_PROXY_PORT / CASCADIA_DASHBOARD_PORT   override published ports
`;

async function main() {
  const argv = process.argv.slice(2);
  const command = argv[0];

  if (!command || command === "help" || command === "--help" || command === "-h") {
    log(HELP);
    return command ? 0 : 1;
  }
  if (command === "--version" || command === "version") {
    log(require("../package.json").version);
    return 0;
  }

  // Parse the remaining args permissively (flags + positionals).
  let parsed;
  try {
    parsed = parseArgs({
      args: argv.slice(1),
      allowPositionals: true,
      strict: false,
      options: {
        build: { type: "boolean" },
        "no-build": { type: "boolean" },
        traffic: { type: "string" },
        "no-traffic": { type: "boolean" },
        live: { type: "boolean" },
        all: { type: "boolean" },
      },
    });
  } catch (e) {
    fail(e.message);
    return 2;
  }

  const v = parsed.values;
  const flags = {
    build: v["no-build"] ? false : v.build === undefined ? undefined : v.build,
    traffic: v["no-traffic"] ? 0 : v.traffic !== undefined ? Number(v.traffic) : undefined,
    live: !!v.live,
    all: !!v.all,
  };
  const positional = parsed.positionals;

  switch (command) {
    case "demo":
      return cmdDemo(flags);
    case "up":
    case "start":
      return cmdUp(flags);
    case "down":
      return cmdDown(flags);
    case "logs":
      return cmdLogs(flags, positional);
    case "doctor":
      return cmdDoctor();
    default:
      fail(`unknown command: ${command}`);
      log(`Run ${c.cyan("cascadia help")} for usage.`);
      return 2;
  }
}

main()
  .then((code) => process.exit(code || 0))
  .catch((err) => {
    fail(err && err.message ? err.message : String(err));
    process.exit(1);
  });
