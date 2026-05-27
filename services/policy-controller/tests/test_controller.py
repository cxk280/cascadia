"""Tests for the pure refit logic.

No I/O. We pass synthetic ClusterStats and assert the rule moves the
threshold in the expected direction.
"""

from __future__ import annotations

from cascadia_policy.controller import PolicyController, UpdateRule
from cascadia_policy.types import ClusterPolicy, ClusterStats, PolicyTable


def _table(threshold: float = 0.7) -> PolicyTable:
    return PolicyTable(
        default_cluster="default",
        cluster_buckets=1,
        clusters={
            "default": ClusterPolicy(
                cluster_id="default",
                cheap_model="cheap",
                expensive_model="expensive",
                threshold=threshold,
                shadow_rate=0.05,
            ),
        },
    )


def _stats(mean: float, n: int = 100) -> dict[str, ClusterStats]:
    return {
        "default": ClusterStats(
            cluster_id="default",
            sample_size=n,
            mean_score=mean,
        )
    }


def test_cheap_winning_lowers_threshold() -> None:
    c = PolicyController(UpdateRule(target=0.5, margin=0.05, step=0.03))
    new = c.refit(_table(0.7), _stats(mean=0.75))
    assert new.clusters["default"].threshold == 0.67


def test_cheap_losing_raises_threshold() -> None:
    c = PolicyController(UpdateRule(target=0.5, margin=0.05, step=0.03))
    new = c.refit(_table(0.7), _stats(mean=0.3))
    assert new.clusters["default"].threshold == 0.73


def test_within_margin_holds_threshold() -> None:
    c = PolicyController(UpdateRule(target=0.5, margin=0.05, step=0.03))
    new = c.refit(_table(0.7), _stats(mean=0.52))
    assert new.clusters["default"].threshold == 0.7


def test_min_sample_size_blocks_update() -> None:
    c = PolicyController(UpdateRule(min_sample_size=50, step=0.03))
    # Below threshold mean would normally raise threshold, but n=5 < 50.
    new = c.refit(_table(0.7), _stats(mean=0.2, n=5))
    assert new.clusters["default"].threshold == 0.7


def test_no_stats_holds_threshold() -> None:
    c = PolicyController(UpdateRule())
    new = c.refit(_table(0.7), {})
    assert new.clusters["default"].threshold == 0.7


def test_threshold_clamps_at_max() -> None:
    c = PolicyController(UpdateRule(step=0.5, max_threshold=0.9))
    new = c.refit(_table(0.85), _stats(mean=0.0))
    # 0.85 + 0.5 = 1.35 → clamp 0.9
    assert new.clusters["default"].threshold == 0.9


def test_threshold_clamps_at_min() -> None:
    c = PolicyController(UpdateRule(step=0.5, min_threshold=0.4))
    new = c.refit(_table(0.45), _stats(mean=1.0))
    # 0.45 - 0.5 = -0.05 → clamp 0.4
    assert new.clusters["default"].threshold == 0.4


def test_version_set_on_output() -> None:
    c = PolicyController()
    out = c.refit(_table(0.7), _stats(0.5), version="my-test-v1")
    assert out.version == "my-test-v1"


def test_new_cluster_seen_in_stats_gets_adopted_from_default() -> None:
    """If the proxy bumps cluster_buckets and we see a new cluster id in stats
    that's not in current policy, we synthesize one from the default-cluster
    policy (and may refit it if there's enough data)."""
    table = PolicyTable(
        default_cluster="default",
        cluster_buckets=4,
        clusters={
            "default": ClusterPolicy(
                cluster_id="default", cheap_model="a", expensive_model="b",
                threshold=0.7, shadow_rate=0.05,
            ),
        },
    )
    stats = {
        # Brand new cluster the controller has never refit.
        "cluster-7": ClusterStats(cluster_id="cluster-7", sample_size=100, mean_score=0.8),
    }
    c = PolicyController(UpdateRule(step=0.03))
    out = c.refit(table, stats)
    assert "cluster-7" in out.clusters
    # Inherited cheap/expensive from default + refit step applied (mean 0.8 > 0.55 → lower).
    assert out.clusters["cluster-7"].cheap_model == "a"
    assert out.clusters["cluster-7"].threshold == 0.67


def test_refit_preserves_provider_prefix_in_model_strings() -> None:
    """Phase 7 contract: the proxy hard-fails on unprefixed model strings,
    so the controller MUST preserve `provider/model` prefixes when it refits
    thresholds — for both existing clusters and newly-adopted ones.
    """
    table = PolicyTable(
        default_cluster="default",
        cluster_buckets=4,
        clusters={
            "default": ClusterPolicy(
                cluster_id="default",
                cheap_model="groq/llama-3.3-70b-versatile",
                expensive_model="anthropic/claude-opus-4-7",
                threshold=0.7,
                shadow_rate=0.05,
            ),
        },
    )
    stats = {
        "default":   ClusterStats(cluster_id="default",   sample_size=100, mean_score=0.8),
        "cluster-2": ClusterStats(cluster_id="cluster-2", sample_size=100, mean_score=0.4),
    }
    c = PolicyController(UpdateRule(step=0.03))
    out = c.refit(table, stats)
    # Existing cluster keeps prefixes.
    assert out.clusters["default"].cheap_model == "groq/llama-3.3-70b-versatile"
    assert out.clusters["default"].expensive_model == "anthropic/claude-opus-4-7"
    # Newly-adopted cluster inherits prefixed defaults.
    assert out.clusters["cluster-2"].cheap_model == "groq/llama-3.3-70b-versatile"
    assert out.clusters["cluster-2"].expensive_model == "anthropic/claude-opus-4-7"


def test_multiple_clusters_updated_independently() -> None:
    table = PolicyTable(
        default_cluster="default",
        cluster_buckets=4,
        clusters={
            "default": ClusterPolicy(
                cluster_id="default", cheap_model="a", expensive_model="b",
                threshold=0.7, shadow_rate=0.05,
            ),
            "cluster-0": ClusterPolicy(
                cluster_id="cluster-0", cheap_model="a", expensive_model="b",
                threshold=0.7, shadow_rate=0.05,
            ),
            "cluster-1": ClusterPolicy(
                cluster_id="cluster-1", cheap_model="a", expensive_model="b",
                threshold=0.7, shadow_rate=0.05,
            ),
        },
    )
    stats = {
        "default":   ClusterStats(cluster_id="default",   sample_size=100, mean_score=0.8),
        "cluster-0": ClusterStats(cluster_id="cluster-0", sample_size=100, mean_score=0.2),
        # cluster-1 has no stats
    }
    c = PolicyController(UpdateRule(step=0.03))
    out = c.refit(table, stats)
    assert out.clusters["default"].threshold == 0.67
    assert out.clusters["cluster-0"].threshold == 0.73
    assert out.clusters["cluster-1"].threshold == 0.7
