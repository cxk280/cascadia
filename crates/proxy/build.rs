//! Build script: force a rebuild whenever the migration set changes.
//!
//! `sqlx::migrate!("./migrations")` embeds the migrations at compile time, but
//! on stable Rust the macro does not reliably emit a `rerun-if-changed` for the
//! directory. Without this, *adding* a migration (e.g. `0008_auth.sql`) leaves
//! a cached binary that never applies it — the proxy boots, runs the migrations
//! it knew about at its last build, and the new tables silently never appear.
//!
//! Watching the directory (and each file) here guarantees `cargo build`
//! recompiles the proxy — and re-runs `sqlx::migrate!` — on any migration add or
//! edit, so the boot-time migrator always reflects the on-disk migration set.

use std::fs;
use std::path::Path;

fn main() {
    let dir = Path::new("migrations");
    println!("cargo:rerun-if-changed=migrations");
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            println!("cargo:rerun-if-changed={}", entry.path().display());
        }
    }
}
