//! Background task that watches a policy file and hot-reloads on change.
//!
//! The policy controller writes new versions via atomic `rename(2)` (see
//! `services/policy-controller/cascadia_policy/writer.py`). Filesystem-event
//! APIs handle that rename inconsistently across platforms: watching the
//! destination file directly binds to a vanished inode on most kernels, and
//! watching the parent directory works on inotify but not reliably on macOS
//! kqueue. Rather than litigate the platform-specific failure modes of every
//! API, we poll the file's modification time once a second. It's a fraction
//! of a syscall per second, robust through any number of atomic-replace
//! cycles, and trivially testable.
//!
//! Phase 5 acceptance criterion: "auto-tunes from cold start without manual
//! intervention." The policy-controller Python service is the one doing the
//! tuning; this module is the receiver that makes the proxy honor the new
//! policy without a restart.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use arc_swap::ArcSwap;
use tokio::time::{interval, MissedTickBehavior};

use crate::policy::PolicyTable;

const POLL_INTERVAL: Duration = Duration::from_secs(1);

/// Spawn the hot-reload watcher. Loads the file once synchronously (so a
/// malformed startup policy fails the boot), then polls for mtime changes
/// from a background task.
pub fn spawn(path: PathBuf, current: Arc<ArcSwap<PolicyTable>>) -> anyhow::Result<()> {
    let initial = PolicyTable::from_json_file(&path)?;
    current.store(Arc::new(initial));

    let last_mtime = std::fs::metadata(&path)
        .ok()
        .and_then(|m| m.modified().ok());

    tokio::spawn(poll_loop(path, current, last_mtime));
    Ok(())
}

async fn poll_loop(
    path: PathBuf,
    current: Arc<ArcSwap<PolicyTable>>,
    mut last_mtime: Option<std::time::SystemTime>,
) {
    let mut ticker = interval(POLL_INTERVAL);
    // Don't burst-reload if the proxy was paused (laptop sleep, CI freeze).
    ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        ticker.tick().await;
        let next_mtime = match std::fs::metadata(&path).and_then(|m| m.modified()) {
            Ok(t) => Some(t),
            Err(err) => {
                // File transiently missing during atomic rename is expected;
                // we'll pick it up on the next tick.
                tracing::debug!(?err, "policy file metadata read failed");
                continue;
            }
        };

        if next_mtime == last_mtime {
            continue;
        }
        last_mtime = next_mtime;

        match PolicyTable::from_json_file(&path) {
            Ok(new) => {
                let version = new.version.clone();
                current.store(Arc::new(new));
                tracing::info!(?version, "policy hot-reloaded");
            }
            Err(err) => {
                tracing::warn!(?err, "policy hot-reload failed; keeping previous policy");
            }
        }
    }
}
