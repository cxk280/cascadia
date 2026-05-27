"""Pydantic wire types for the labeling write surface."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LabelChoice = Literal["a", "b", "tie", "unknown"]


_HTML_TAG = re.compile(r"<[^>]+>")

REVIEWER_ID_PATTERN = r"^[a-z0-9_\-]+$"
REVIEWER_ID_MAX_LEN = 64
_REVIEWER_ID_RE = re.compile(REVIEWER_ID_PATTERN)


def validate_reviewer_id(v: str) -> str:
    """Single source of truth for reviewer_id shape.

    Applied identically on onboarding, label submission, and the
    `?reviewer_id=` query params so an id that can never be onboarded can't
    leak in via the write/read paths (the asymmetry previously let labels be
    attributed to ids the onboarding endpoint would have rejected).
    """
    if not (1 <= len(v) <= REVIEWER_ID_MAX_LEN):
        raise ValueError(f"reviewer_id must be 1-{REVIEWER_ID_MAX_LEN} characters")
    if not _REVIEWER_ID_RE.fullmatch(v):
        raise ValueError(r"reviewer_id must match ^[a-z0-9_\-]+$")
    # The pattern permits `---` / `___` — strings with zero alphanumeric
    # characters. Require at least one a-z or 0-9 so the id is
    # human-discriminable in logs + dashboards.
    if not any(c.isalnum() for c in v):
        raise ValueError("reviewer_id must contain at least one letter or digit")
    return v


class ReviewerOnboardRequest(BaseModel):
    reviewer_id: str
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("reviewer_id")
    @classmethod
    def _check_reviewer_id(cls, v: str) -> str:
        return validate_reviewer_id(v)

    @field_validator("display_name")
    @classmethod
    def display_name_no_html_no_blank(cls, v: str) -> str:
        if _HTML_TAG.search(v):
            raise ValueError("display_name must not contain HTML tags")
        if not v.strip():
            raise ValueError("display_name must not be blank")
        return v


class ReviewerOnboardResponse(BaseModel):
    reviewer_id: str
    display_name: str
    onboarded_at: datetime
    already_existed: bool


class NextPair(BaseModel):
    pair_id: str
    prompt: str
    # The responses are ALREADY in display order — the server randomizes
    # before sending. `shown_swapped` is recorded server-side and won't be
    # echoed back to the client (the reviewer must not see it).
    display_a: str
    display_b: str
    cluster_id: str | None = None
    selection_round: int
    selection_reason: str
    queue_position: int    # 1-indexed
    queue_size: int


class NextPairResponse(BaseModel):
    pair: NextPair | None
    queue_size: int


class LabelSubmission(BaseModel):
    pair_id: str
    reviewer_id: str
    # The reviewer's pick on what they saw on screen. The server un-swaps
    # internally when storing.
    raw_label: LabelChoice
    rationale: str | None = Field(default=None, max_length=4000)
    time_ms: int | None = Field(default=None, ge=0)

    @field_validator("reviewer_id")
    @classmethod
    def _check_reviewer_id(cls, v: str) -> str:
        return validate_reviewer_id(v)


class LabelAck(BaseModel):
    pair_id: str
    reviewer_id: str
    label_id: str
    accepted: bool


class ProgressResponse(BaseModel):
    reviewer_id: str
    n_labeled: int
    n_pending: int
    n_attention_passed: int
    n_attention_failed: int


class RubricResponse(BaseModel):
    version: str
    markdown: str
