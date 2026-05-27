"""FastAPI route registration for the labeling write surface."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Callable

import asyncpg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status

from cascadia_dashboard.calibrate.store import (
    CalibrationStore,
    decide_swap,
)
from cascadia_dashboard.calibrate.types import (
    REVIEWER_ID_MAX_LEN,
    REVIEWER_ID_PATTERN,
    LabelAck,
    LabelSubmission,
    NextPair,
    NextPairResponse,
    ProgressResponse,
    ReviewerOnboardRequest,
    ReviewerOnboardResponse,
    RubricResponse,
    validate_reviewer_id,
)

log = logging.getLogger(__name__)


def _reviewer_id_query(
    reviewer_id: Annotated[
        str,
        Query(min_length=1, max_length=REVIEWER_ID_MAX_LEN, pattern=REVIEWER_ID_PATTERN),
    ],
) -> str:
    # The Query constraints reject the obvious junk early (length, charset);
    # validate_reviewer_id adds the "must contain an alphanumeric" rule so the
    # query params match the onboarding/label contract exactly.
    try:
        return validate_reviewer_id(reviewer_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


ReviewerIdQuery = Annotated[str, Depends(_reviewer_id_query)]

# The rubric ships in the judge-worker package because that's where the
# calibration code lives. The dashboard-api reads the file at runtime so a
# rubric edit doesn't require redeploying the API.
_DEFAULT_RUBRIC_PATH = (
    Path(__file__).resolve().parents[4]
    / "services" / "judge-worker" / "calibration" / "rubric_v2.md"
)
RUBRIC_PATH = Path(os.environ.get("CASCADIA_RUBRIC_PATH", str(_DEFAULT_RUBRIC_PATH)))


def _compute_rubric_version() -> str:
    """Content-hash the rubric file so a silent mid-batch edit shows up as a
    different `rubric_version` in `calibration_labels`. Hardcoded `"v2"`
    strings were vulnerable to silent edits — two labels stamped identically
    despite seeing different rubric content. Now we hash sha256 of the file
    bytes at startup; the version stamp on every label is a stable fingerprint.

    Falls back to the literal `"v2"` if the file isn't readable (i.e. the
    rubric endpoint will also fail, and the existing FileNotFoundError
    handler will surface it to the operator). The fallback keeps unrelated
    flows working in dev environments where the rubric file isn't checked
    out yet.
    """
    import hashlib
    try:
        digest = hashlib.sha256(RUBRIC_PATH.read_bytes()).hexdigest()
        return f"v2+sha256:{digest[:16]}"
    except OSError as exc:
        # The fallback is intentional (keeps dev environments working when
        # the rubric file isn't checked out yet) but it does mean any label
        # submitted in this window is stamped `"v2"` with no hash. Log a
        # loud warning so an operator running prod can spot the regression.
        log.warning(
            "rubric file at %s unreadable (%s); RUBRIC_VERSION falling back "
            "to 'v2' with no content-hash. Labels submitted in this window "
            "will lack a hash stamp.",
            RUBRIC_PATH, exc,
        )
        return "v2"


# Computed once at module load. A rubric edit requires a process restart
# to be reflected in the version stamp — that's intentional. Hot-reloading
# the hash mid-batch would invert the bug we're fixing.
RUBRIC_VERSION = _compute_rubric_version()


def attach_calibrate_routes(
    app: FastAPI,
    get_store: Callable[[], CalibrationStore],
) -> None:
    router = APIRouter(prefix="/api/calibrate", tags=["calibrate"])

    @router.get("/rubric", response_model=RubricResponse)
    async def rubric() -> RubricResponse:
        try:
            text = RUBRIC_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rubric file not found at {RUBRIC_PATH}",
            )
        return RubricResponse(version=RUBRIC_VERSION, markdown=text)

    @router.post("/reviewers", response_model=ReviewerOnboardResponse)
    async def onboard_reviewer(req: ReviewerOnboardRequest) -> ReviewerOnboardResponse:
        onboarded_at, already_existed, actual_display_name = (
            await get_store().upsert_reviewer(req.reviewer_id, req.display_name)
        )
        # Echo the *existing* display_name on collision so the frontend can
        # show the operator who they're about to log in as. The request's
        # display_name is intentionally discarded for existing reviewers.
        return ReviewerOnboardResponse(
            reviewer_id=req.reviewer_id,
            display_name=actual_display_name,
            onboarded_at=onboarded_at,
            already_existed=already_existed,
        )

    @router.get("/next", response_model=NextPairResponse)
    async def next_pair(reviewer_id: ReviewerIdQuery) -> NextPairResponse:
        store = get_store()
        pair = await store.next_pair_for(reviewer_id)
        queue_size = await store.queue_size_for(reviewer_id)
        if pair is None:
            return NextPairResponse(pair=None, queue_size=queue_size)
        swap = decide_swap(pair_id=pair.pair_id, reviewer_id=reviewer_id)
        display_a = pair.response_b if swap else pair.response_a
        display_b = pair.response_a if swap else pair.response_b
        return NextPairResponse(
            pair=NextPair(
                pair_id=pair.pair_id,
                prompt=pair.prompt,
                display_a=display_a,
                display_b=display_b,
                cluster_id=pair.cluster_id,
                selection_round=pair.selection_round,
                selection_reason=pair.selection_reason,
                queue_position=pair.queue_position,
                queue_size=queue_size,
            ),
            queue_size=queue_size,
        )

    @router.post("/labels", response_model=LabelAck)
    async def submit_label(req: LabelSubmission) -> LabelAck:
        # Recompute the swap server-side from the (pair, reviewer) pair so
        # we don't trust the client about which way the pair was shown.
        swap = decide_swap(pair_id=req.pair_id, reviewer_id=req.reviewer_id)
        try:
            label_id = await get_store().submit_label(
                pair_id=req.pair_id,
                reviewer_id=req.reviewer_id,
                shown_swapped=swap,
                raw_label=req.raw_label,
                rationale=req.rationale,
                time_ms=req.time_ms,
                rubric_version=RUBRIC_VERSION,
            )
        except asyncpg.exceptions.DataError as exc:
            # The DB rejected the input itself (e.g. pair_id not a valid uuid).
            # That IS the client's fault → 400.
            log.warning("label rejected (bad input) pair=%s reviewer=%s: %r",
                        req.pair_id, req.reviewer_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="label rejected: invalid input",
            )
        except asyncpg.exceptions.IntegrityConstraintViolationError as exc:
            # e.g. FK violation: pair_id references a pair that doesn't exist.
            log.warning("label rejected (unknown pair) pair=%s reviewer=%s: %r",
                        req.pair_id, req.reviewer_id, exc)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="unknown pair_id",
            )
        except Exception as exc:
            # Everything else (DB down, pool exhausted, timeout) is an
            # infrastructure failure, NOT the client's input. Returning 400
            # here previously masked outages as "your label was bad" and the
            # label was silently dropped. Surface 503 + log at error level so
            # monitoring fires and a well-behaved client can retry.
            log.error("label submit failed (store unavailable) pair=%s reviewer=%s: %r",
                      req.pair_id, req.reviewer_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="label store unavailable",
            )
        return LabelAck(
            pair_id=req.pair_id,
            reviewer_id=req.reviewer_id,
            label_id=label_id,
            accepted=True,
        )

    @router.get("/progress", response_model=ProgressResponse)
    async def progress(reviewer_id: ReviewerIdQuery) -> ProgressResponse:
        p = await get_store().progress_for(reviewer_id)
        return ProgressResponse(
            reviewer_id=reviewer_id,
            n_labeled=p.n_labeled,
            n_pending=p.n_pending,
            n_attention_passed=p.n_attention_passed,
            n_attention_failed=p.n_attention_failed,
        )

    app.include_router(router)
