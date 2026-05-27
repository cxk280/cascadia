"""Policy output adapters: where the refit policy gets written."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from cascadia_policy.types import PolicyTable


@runtime_checkable
class PolicyWriter(Protocol):
    async def write(self, table: PolicyTable) -> None:
        ...


class JsonFileWriter(PolicyWriter):
    """Atomic write — temp file in the same directory, then rename.

    The Rust proxy's file watcher only sees fully-formed files because the
    rename is atomic within the same filesystem. Crucially: never write to
    the destination path in chunks.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    async def write(self, table: PolicyTable) -> None:
        # The Rust proxy rejects a policy whose `default_cluster` isn't a key
        # in `clusters` (it keeps the previous policy and logs a warn). Catch
        # that here so the controller doesn't silently persist a
        # structurally-valid-but-semantically-broken policy the proxy can't
        # load.
        if table.default_cluster not in table.clusters:
            raise ValueError(
                f"refusing to write policy: default_cluster "
                f"{table.default_cluster!r} is not present in clusters "
                f"{sorted(table.clusters)} — the proxy would reject this on reload"
            )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = table.model_dump_json(indent=2)
        # Same directory so rename is atomic (cross-filesystem rename can fail).
        # mkstemp gives us the path up front so we can always clean it up — a
        # write/fsync/replace failure must not leave an orphaned `.tmp` file
        # accumulating in the policy directory.
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=self._path.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            # On success os.replace renamed tmp_path away, so this only runs
            # on a failure path.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
