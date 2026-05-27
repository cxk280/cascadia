"""Pure logic: given current policy + cluster stats, produce next policy.

No I/O. Test exhaustively. Real refit math goes here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from cascadia_policy.types import ClusterPolicy, ClusterStats, PolicyTable


@dataclass(frozen=True)
class UpdateRule:
    """Phase-4 threshold update — a simple bounded step toward a target.

    The judge score is the probability that the cheap response is at least as
    good as the expensive response. If the cheap tier is winning by a clear
    margin (mean > target + margin), we lower the threshold (more cheap path).
    If it's losing (mean < target - margin), we raise it. The step is a fixed
    fraction; bounds prevent runaway behavior. Phase 5 swaps for UCB.
    """

    target: float = 0.5
    margin: float = 0.05
    step: float = 0.03
    min_threshold: float = 0.3
    max_threshold: float = 0.95
    min_sample_size: int = 20
    """Don't update a cluster's threshold with fewer than N scores."""


class PolicyController:
    def __init__(self, rule: UpdateRule | None = None) -> None:
        self._rule = rule or UpdateRule()

    def refit(
        self,
        current: PolicyTable,
        stats: Mapping[str, ClusterStats],
        *,
        version: str | None = None,
    ) -> PolicyTable:
        """Return a new policy table with updated thresholds.

        `current` is the policy currently in effect (read from disk).
        `stats` maps cluster_id -> ClusterStats from the storage layer.
        `version` is an opaque string the proxy logs on reload; defaults to
        a UTC ISO-8601 timestamp.

        If `stats` contains a cluster id that's missing from `current`
        (operator bumped `cluster_buckets` in the proxy env before the
        controller had ever seen that bucket), we synthesize a new
        `ClusterPolicy` from the default-cluster's policy. Without this,
        new clusters would silently keep their nonexistent-in-policy
        fallback forever and never get tuned.
        """
        new_clusters: dict[str, ClusterPolicy] = {}
        for cid, policy in current.clusters.items():
            new_clusters[cid] = self._refit_cluster(policy, stats.get(cid))

        # Adopt new clusters seen in stats but missing from current policy.
        default_policy = current.clusters.get(current.default_cluster)
        for cid in stats:
            if cid in new_clusters:
                continue
            if default_policy is None:
                continue  # malformed table; nothing to clone from
            adopted = default_policy.model_copy(update={"cluster_id": cid})
            new_clusters[cid] = self._refit_cluster(adopted, stats[cid])

        return PolicyTable(
            default_cluster=current.default_cluster,
            version=version or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            cluster_buckets=current.cluster_buckets,
            clusters=new_clusters,
        )

    def _refit_cluster(
        self,
        policy: ClusterPolicy,
        stats: ClusterStats | None,
    ) -> ClusterPolicy:
        if (
            stats is None
            or stats.mean_score is None
            or stats.sample_size < self._rule.min_sample_size
        ):
            return policy  # too thin to act on

        delta = 0.0
        if stats.mean_score > self._rule.target + self._rule.margin:
            delta = -self._rule.step  # cheap is winning → lower threshold
        elif stats.mean_score < self._rule.target - self._rule.margin:
            delta = +self._rule.step  # cheap is losing → raise threshold

        new_threshold = _clamp(
            policy.threshold + delta,
            self._rule.min_threshold,
            self._rule.max_threshold,
        )
        return policy.model_copy(update={"threshold": round(new_threshold, 4)})


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
