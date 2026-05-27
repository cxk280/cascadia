"""Calibration harness — measures judge agreement vs human labels.

Phase 5 acceptance criterion: Kendall's τ ≥ 0.7 between the judge ensemble
and human-labeled pairs on the calibration set.
"""

from cascadia_judge.calibration.dataset import CalibrationPair, load_dataset
from cascadia_judge.calibration.metrics import (
    CalibrationMetrics,
    agreement_rate,
    compute_metrics,
    kendall_tau,
)
from cascadia_judge.calibration.runner import CalibrationResult, run_calibration

__all__ = [
    "CalibrationMetrics",
    "CalibrationPair",
    "CalibrationResult",
    "agreement_rate",
    "compute_metrics",
    "kendall_tau",
    "load_dataset",
    "run_calibration",
]
