from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    role: Role
    content: str


class LLMResponse(BaseModel):
    text: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


class ShadowPair(BaseModel):
    request_id: str
    prompt: str
    cheap_model: str
    cheap_response: str
    expensive_model: str
    expensive_response: str
    cluster_id: str | None = None


class JudgeScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str


class JudgeVerdict(BaseModel):
    request_id: str
    judge_name: str
    prompt_variant: str
    model: str
    provider: str
    score: JudgeScore
    prompt_hash: str
    elapsed_ms: int
    error: str | None = None
