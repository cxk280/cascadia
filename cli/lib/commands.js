"use strict";

const readline = require("node:readline");
const {
  c,
  log,
  step,
  ok,
  warn,
  fail,
  commandExists,
  portInUse,
  pickPort,
  waitForHttp,
} = require("./util");
const { resolveSource, findLocalCheckout } = require("./source");
const {
  dockerReady,
  compose,
  DEMO_FILE,
  LIVE_FILE,
  DEMO_PROJECT,
  LIVE_PROJECT,
  BUNDLED_DEMO_FILE,
  bundledDemoExists,
} = require("./docker");

// Prebuilt demo images live in GHCR under the repo owner's namespace. The
// default `cascadia demo` PULLS these (no git, no local build); `--build`
// builds from source instead. PUBLISHED_IMAGE_TAG is bumped in lockstep with
// the image release published by CI (see .circleci publish-images); override at
// runtime with CASCADIA_TAG / CASCADIA_REGISTRY.
const DEFAULT_REGISTRY = "ghcr.io/cxk280/";
const PUBLISHED_IMAGE_TAG = "v0.1.0";

// --- demo traffic -----------------------------------------------------------
// A SMALL, fixed set of prompts on purpose. Cluster assignment is a hash of the
// prompt, so a handful of distinct prompts means each cluster is dominated by
// ONE prompt — and therefore one behaviour. We use only two clear modes:
//   • confident → the mock answers "Yes." → judge scores the cheap tier high
//     (~0.67, cheap ≈ expensive) → controller LOWERS that cluster's threshold.
//   • "uncertain" → the mock hedges → judge scores the cheap tier low (~0.25)
//     → controller RAISES that cluster's threshold.
// That gives clusters whose mean judge score lands clearly outside the refit
// dead zone (target ± margin), in OPPOSITE directions — so thresholds visibly
// move. (A broadly *varied* prompt mix averages every cluster back to ~0.5 and
// nothing moves — the controller working as designed, just an unwatchable demo.)
const PROMPTS = [
  // Confident — cheap tier wins → threshold drifts down (more cheap routing).
  "Answer in one word: what is 2 + 2?",
  "One word only — what is the capital of France?",
  "Reply yes or no: is the sky blue on a clear day?",
  "In a single word, what color is grass?",
  // Uncertain — cheap tier hedges and loses → threshold drifts up.
  "I'm uncertain about how DNS resolution works — can you explain?",
  "I'm uncertain about the CAP theorem — walk me through the tradeoffs.",
  "I'm uncertain how OAuth refresh tokens are rotated — help?",
  "I'm uncertain about TCP slow start — what's going on there?",
];

async function driveTraffic(proxyBase, n) {
  const url = `${proxyBase.replace(/\/$/, "")}/v1/chat/completions`;
  let okCount = 0;
  for (let i = 0; i < n; i++) {
    const prompt = PROMPTS[i % PROMPTS.length];
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: "auto",
          messages: [{ role: "user", content: prompt }],
        }),
        signal: AbortSignal.timeout(30000),
      });
      if (res.ok) okCount++;
      await res.arrayBuffer().catch(() => {});
    } catch {
      /* keep going; a few failures are fine */
    }
    if ((i + 1) % 10 === 0) process.stdout.write(c.dim(`  …${i + 1}/${n}\n`));
  }
  return okCount;
}

// --- small prompt helpers ---------------------------------------------------
function promptLine(query) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(query, (a) => {
      rl.close();
      resolve(a.trim());
    });
  });
}

// Read a secret without echoing it to the terminal (masks with '*').
function promptHidden(query) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: true,
    });
    rl.stdoutMuted = true;
    rl._writeToOutput = function (s) {
      if (!rl.stdoutMuted) return rl.output.write(s);
      rl.output.write(s.includes("\n") ? "\n" : "*");
    };
    process.stdout.write(query);
    rl.question("", (a) => {
      rl.close();
      process.stdout.write("\n");
      resolve(a.trim());
    });
  });
}

// --- commands ---------------------------------------------------------------

// Where the demo compose file lives, WITHOUT ever cloning: the bundled copy in
// the published package first, else a local checkout. Returns {src, file} for
// compose(), or null if neither is available. `src` is null for the bundled
// path (compose() resolves the absolute file and picks a cwd).
function demoComposeLocation() {
  if (bundledDemoExists()) return { src: null, file: BUNDLED_DEMO_FILE };
  const local = findLocalCheckout();
  if (local) return { src: local, file: DEMO_FILE };
  return null;
}

async function cmdDemo(flags) {
  if (!dockerReady()) return 1;

  // Two modes:
  //   default → PULL prebuilt images from the registry (no git, no build).
  //   --build → build from source (needs a checkout; clones on a cold run).
  const wantBuild = flags.build === true;

  const proxyPort = await pickPort(Number(process.env.CASCADIA_PROXY_PORT) || 8080);
  const dashPort = await pickPort(Number(process.env.CASCADIA_DASHBOARD_PORT) || 3000);
  const env = {
    ...process.env,
    CASCADIA_PROXY_PORT: String(proxyPort),
    CASCADIA_DASHBOARD_PORT: String(dashPort),
  };

  // `composeArgs` lets the build path keep using the in-tree compose file and
  // the pull path use the bundled copy (absolute path, no checkout needed).
  let src, demoFile;
  if (wantBuild) {
    src = await resolveSource(); // may clone; requires git on a cold run
    demoFile = DEMO_FILE;
  } else {
    const loc = demoComposeLocation();
    if (!loc) {
      fail("No bundled compose file and no local checkout found. Reinstall the package, or run `cascadia demo --build`.");
      return 1;
    }
    src = loc.src;
    demoFile = loc.file;
    env.CASCADIA_REGISTRY = process.env.CASCADIA_REGISTRY || DEFAULT_REGISTRY;
    env.CASCADIA_TAG = process.env.CASCADIA_TAG || PUBLISHED_IMAGE_TAG;
  }

  if (wantBuild) {
    log(c.dim("Building images from source (a few minutes); cached afterward."));
  } else {
    // Pull explicitly so a missing image fails loudly here instead of silently
    // falling back to an in-place build (compose `up` builds services that have
    // a build: section when their image is absent).
    step(`Pulling prebuilt images (${env.CASCADIA_REGISTRY}…:${env.CASCADIA_TAG})…`);
    const pull = await compose(src, demoFile, DEMO_PROJECT, ["pull"], { env });
    if (pull !== 0) {
      fail(`Could not pull prebuilt images for tag '${env.CASCADIA_TAG}'.`);
      log(c.dim("   Build from source instead with:  cascadia demo --build"));
      return pull;
    }
  }

  const upArgs = wantBuild ? ["up", "-d", "--build"] : ["up", "-d", "--no-build"];
  step("Starting the demo stack…");
  const code = await compose(src, demoFile, DEMO_PROJECT, upArgs, { env });
  if (code !== 0) {
    fail("docker compose up failed.");
    return code;
  }

  step(`Waiting for the proxy on :${proxyPort} …`);
  const proxyBase = `http://localhost:${proxyPort}`;
  if (!(await waitForHttp(`${proxyBase}/readyz`))) {
    warn("Proxy didn't become ready in time. Check logs: cascadia logs");
    return 1;
  }
  ok("Proxy is up.");

  // The dashboard-api seeds a representative Pareto frontier on first boot
  // (CASCADIA_DEMO=true), so the demo is populated without driving traffic.
  // Pushing live mock traffic is opt-in (--traffic N): it's the single-model
  // path, which collapses the frontier to one corner, so it's off by default.
  const n = flags.traffic ?? 0;
  if (n > 0) {
    step(`Driving ${n} live requests through the proxy (keyless, free)…`);
    const got = await driveTraffic(proxyBase, n);
    if (got === 0) warn("No requests succeeded.");
    else ok(`${got}/${n} requests served.`);
  }

  log("");
  ok(c.bold("Cascadia demo is up — no API keys, no cost."));
  log(`   Dashboard  →  ${c.cyan(`http://localhost:${dashPort}`)}  ${c.dim("(log in: foo@bar.com / admin123)")}`);
  log(`   Pareto     →  ${c.cyan(`http://localhost:${dashPort}/pareto`)}  ${c.dim("(cost/quality frontier + slider)")}`);
  log(`   Proxy      →  ${c.cyan(proxyBase)}  ${c.dim("(OpenAI-compatible at /v1)")}`);
  log("");
  log(c.dim("   The dashboard is pre-populated with a representative frontier, and"));
  log(c.dim("   the controller refits thresholds from it every ~30s. Push your own"));
  log(c.dim("   live requests with:  cascadia demo --traffic 60"));
  log("");
  log(c.dim("   Stop + wipe:  cascadia down       Tail logs:  cascadia logs"));
  return 0;
}

async function cmdUp(flags) {
  if (!dockerReady()) return 1;
  const src = await resolveSource();

  log(c.bold("Self-host Cascadia against real providers."));
  log(c.dim("This spends real API budget. Keys are passed to the containers in-memory"));
  log(c.dim("(not written to disk). Export OPENAI_API_KEY / ANTHROPIC_API_KEY to skip this."));
  log("");

  let openaiKey = process.env.OPENAI_API_KEY;
  let anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!openaiKey) openaiKey = await promptHidden("OpenAI API key (cascade tiers): ");
  if (!anthropicKey)
    anthropicKey = await promptHidden("Anthropic API key (cross-family judge): ");
  if (!openaiKey || !anthropicKey) {
    fail("Both keys are required for the live stack (OpenAI cascade + Anthropic judge).");
    return 2;
  }

  const env = {
    ...process.env,
    OPENAI_API_KEY: openaiKey,
    ANTHROPIC_API_KEY: anthropicKey,
    CASCADIA_CALIBRATE_PASS: process.env.CASCADIA_CALIBRATE_PASS || "localdev",
  };

  const upArgs = ["up", "-d"];
  if (flags.build !== false) upArgs.push("--build");
  step("Starting the live stack…");
  const code = await compose(src, LIVE_FILE, LIVE_PROJECT, upArgs, { env });
  if (code !== 0) {
    fail("docker compose up failed.");
    return code;
  }

  log("");
  ok(c.bold("Cascadia (live) is up."));
  log(`   Dashboard  →  ${c.cyan("http://localhost:3000")}  ${c.dim("(first visit → /signup; first account is admin)")}`);
  log(`   Proxy      →  ${c.cyan("http://localhost:18080")}  ${c.dim("(OpenAI-compatible at /v1)")}`);
  log("");
  log(c.dim("   Send your own traffic through the proxy; the judge panel + controller"));
  log(c.dim("   run the closed loop live. Stop + wipe: cascadia down --live"));
  return 0;
}

async function cmdDown(flags) {
  if (!dockerReady()) return 1;
  const live = flags.live || flags.all;
  const demo = !flags.live || flags.all;
  let code = 0;
  if (demo) {
    // No clone for teardown: bundled compose, else a local checkout.
    const loc = demoComposeLocation();
    if (loc) {
      step("Tearing down the demo stack (and its volume)…");
      code = (await compose(loc.src, loc.file, DEMO_PROJECT, ["down", "-v"])) || code;
    } else if (!live) {
      warn("No demo compose file found to tear down.");
    }
  }
  if (live) {
    const src = await resolveSource(); // live stack only ships from source
    step("Tearing down the live stack (and its volume)…");
    code = (await compose(src, LIVE_FILE, LIVE_PROJECT, ["down", "-v"])) || code;
  }
  if (code === 0) ok("Stopped.");
  return code;
}

async function cmdLogs(flags, positional) {
  if (!dockerReady()) return 1;
  const args = ["logs", "-f", "--tail", "60", ...positional];
  if (flags.live) {
    const src = await resolveSource();
    return compose(src, LIVE_FILE, LIVE_PROJECT, args);
  }
  const loc = demoComposeLocation();
  if (!loc) {
    fail("No demo compose file found.");
    return 1;
  }
  return compose(loc.src, loc.file, DEMO_PROJECT, args);
}

async function cmdDoctor() {
  let allGood = true;
  const check = (label, good, hint) => {
    if (good) ok(label);
    else {
      fail(`${label}${hint ? ` — ${hint}` : ""}`);
      allGood = false;
    }
  };

  check("Node >= 18", Number(process.versions.node.split(".")[0]) >= 18, "upgrade Node");
  check("Docker installed", commandExists("docker"), "https://docs.docker.com/get-docker/");
  check(
    "Docker daemon running",
    commandExists("docker") && require("./util").capture("docker", ["info"]).code === 0,
    "start Docker"
  );
  check(
    "docker compose v2",
    commandExists("docker", ["compose", "version"]),
    "install the Compose plugin"
  );
  check("git available", commandExists("git"), "needed only for `cascadia demo --build` / `cascadia up`");

  for (const p of [8080, 3000]) {
    const used = await portInUse(p);
    if (used) warn(`port ${p} is in use — the launcher will fall back to the next free port`);
    else ok(`port ${p} free`);
  }

  // Default demo path: bundled compose + prebuilt images — no clone needed.
  if (bundledDemoExists()) {
    ok("Demo compose: bundled (pulls prebuilt images — no git, no build)");
  } else {
    try {
      const local = findLocalCheckout();
      if (local) ok(`Demo compose: local checkout (${local})`);
      else {
        warn("Demo compose: no bundled file and no checkout — reinstall, or use `--build`");
      }
    } catch (e) {
      fail(`Cascadia source: ${e.message}`);
      log(c.dim(`   (set CASCADIA_HOME to a checkout, or reinstall the package)`));
      allGood = false;
    }
  }

  log("");
  log(allGood ? c.green("All good — `cascadia demo` should just work.") : c.yellow("Some checks failed (see above)."));
  return allGood ? 0 : 1;
}

module.exports = { cmdDemo, cmdUp, cmdDown, cmdLogs, cmdDoctor };
