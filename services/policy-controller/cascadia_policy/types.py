"""Shared data shapes.

The pydantic models here mirror what the Rust proxy expects in its policy
JSON (`crates/proxy/src/policy.rs::PolicyTable`). Don't drift the field names
or types without updating both sides.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClusterPolicy(BaseModel):
    cluster_id: str
    cheap_model: str
    expensive_model: str
    threshold: float = Field(ge=0.0, le=1.0)
    shadow_rate: float = Field(ge=0.0, le=1.0)


class PolicyTable(BaseModel):
    default_cluster: str
    version: str | None = None
    cluster_buckets: int = 1
    clusters: dict[str, ClusterPolicy]


class ClusterStats(BaseModel):
    """Aggregate statistics for one cluster over the lookback window."""

    cluster_id: str
    sample_size: int
    mean_score: float | None = None
    """Mean judge score in [0, 1]. None when sample_size == 0."""
    escalation_rate: float | None = None
    """Fraction of requests that escalated. None when no events."""
