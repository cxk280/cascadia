"""JSONL calibration-set loader.

Each line is one labeled pair:

    {"id": "pair-001",
     "prompt": "Solve: 17 * 24",
     "response_a": "408",
     "response_b": "418, approximately",
     "model_a": "cheap-model",
     "model_b": "expensive-model",
     "human_label": "a",          # "a" | "b" | "tie"
     "source": "synthetic_v0",
     "category": "math"}

`human_label` is the only required scoring field. `model_a`/`model_b`/
`category` are optional metadata that the report carries through verbatim.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

HumanLabel = Literal["a", "b", "tie"]
_VALID_LABELS = {"a", "b", "tie"}


@dataclass(frozen=True)
class CalibrationPair:
    id: str
    prompt: str
    response_a: str
    response_b: str
    human_label: HumanLabel
    model_a: str = "unknown-cheap"
    model_b: str = "unknown-expensive"
    source: str = "unknown"
    category: str = "uncategorized"
    metadata: dict[str, object] = field(default_factory=dict)


def load_dataset(path: str | Path) -> list[CalibrationPair]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        return list(_iter_jsonl(fh, source_path=str(p)))


def _iter_jsonl(fh: Iterable[str], *, source_path: str) -> Iterator[CalibrationPair]:
    for lineno, raw in enumerate(fh, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source_path}:{lineno}: invalid JSON: {exc}") from exc
        label = obj.get("human_label")
        if label not in _VALID_LABELS:
            raise ValueError(
                f"{source_path}:{lineno}: human_label must be one of {_VALID_LABELS}, "
                f"got {label!r}"
            )
        yield CalibrationPair(
            id=str(obj["id"]),
            prompt=str(obj["prompt"]),
            response_a=str(obj["response_a"]),
            response_b=str(obj["response_b"]),
            human_label=label,  # type: ignore[arg-type]
            model_a=str(obj.get("model_a", "unknown-cheap")),
            model_b=str(obj.get("model_b", "unknown-expensive")),
            source=str(obj.get("source", "unknown")),
            category=str(obj.get("category", "uncategorized")),
            metadata={
                k: v
                for k, v in obj.items()
                if k not in {
                    "id", "prompt", "response_a", "response_b",
                    "human_label", "model_a", "model_b", "source", "category",
                }
            },
        )
