"""Labeling write surface — extends the dashboard-api with calibration routes.

Read endpoints already exist for displaying state; this submodule adds the
write side a reviewer needs to label pairs:

  GET  /api/calibrate/rubric         — the markdown rubric, served as JSON
  POST /api/calibrate/reviewers      — onboard a reviewer (idempotent)
  GET  /api/calibrate/next?reviewer  — next pair to label (or null)
  POST /api/calibrate/labels         — submit a label
  GET  /api/calibrate/progress?reviewer — counts for this reviewer

Position randomization is decided here (server-side) and persisted in
`calibration_labels.shown_swapped` so the aggregator can un-swap correctly.
"""

from cascadia_dashboard.calibrate.store import (
    CalibrationStore,
    AsyncpgCalibrationStore,
    InMemoryCalibrationStore,
)
from cascadia_dashboard.calibrate.routes import attach_calibrate_routes
from cascadia_dashboard.calibrate.types import (
    LabelSubmission,
    NextPairResponse,
    ProgressResponse,
    ReviewerOnboardRequest,
    ReviewerOnboardResponse,
    RubricResponse,
)

__all__ = [
    "AsyncpgCalibrationStore",
    "CalibrationStore",
    "InMemoryCalibrationStore",
    "LabelSubmission",
    "NextPairResponse",
    "ProgressResponse",
    "ReviewerOnboardRequest",
    "ReviewerOnboardResponse",
    "RubricResponse",
    "attach_calibrate_routes",
]
