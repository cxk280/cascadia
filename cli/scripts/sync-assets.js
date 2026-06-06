#!/usr/bin/env node
"use strict";

// Copy the in-tree demo compose file into the launcher package's bundled
// assets, so the published npm package can run `cascadia demo` (pull path)
// with no git checkout. Runs automatically on `prepack` (npm publish / pack);
// also run manually after editing the compose file.
//
//   node scripts/sync-assets.js          # copy
//   node scripts/sync-assets.js --check  # exit 1 if the bundled copy is stale
//
// Keeping ONE source of truth (deploy/compose/...) + a CI `--check` guard means
// the two copies can never silently drift.

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "deploy", "compose", "docker-compose.demo.yml");
const DEST_DIR = path.resolve(__dirname, "..", "assets");
const DEST = path.join(DEST_DIR, "docker-compose.demo.yml");

const check = process.argv.includes("--check");

if (!fs.existsSync(SRC)) {
  console.error(`sync-assets: source compose not found at ${SRC}`);
  process.exit(2);
}

const srcContent = fs.readFileSync(SRC, "utf8");

if (check) {
  const destContent = fs.existsSync(DEST) ? fs.readFileSync(DEST, "utf8") : null;
  if (destContent !== srcContent) {
    console.error(
      "sync-assets: cli/assets/docker-compose.demo.yml is out of date.\n" +
        "Run `node cli/scripts/sync-assets.js` and commit the result."
    );
    process.exit(1);
  }
  console.log("sync-assets: bundled compose is up to date.");
  process.exit(0);
}

fs.mkdirSync(DEST_DIR, { recursive: true });
fs.writeFileSync(DEST, srcContent);
console.log(`sync-assets: wrote ${path.relative(ROOT, DEST)}`);
