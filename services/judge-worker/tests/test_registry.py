from __future__ import annotations

import pytest

from cascadia_judge.judges import REGISTRY
from cascadia_judge.judges.base import BaseJudge, JudgeRegistry
from cascadia_judge.types import JudgeVerdict, ShadowPair


def test_pairwise_judge_is_auto_registered() -> None:
    assert "pairwise_preference_v1" in REGISTRY.names()


def test_register_rejects_missing_class_attrs() -> None:
    reg = JudgeRegistry()

    class IncompleteJudge(BaseJudge):
        name = ""
        description = "missing name"
        prompt_variant = "x/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(TypeError):
        reg.register(IncompleteJudge)


def test_register_rejects_name_collision() -> None:
    reg = JudgeRegistry()

    class JudgeA(BaseJudge):
        name = "collide_v1"
        description = "first"
        prompt_variant = "x/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:  # pragma: no cover
            raise NotImplementedError

    class JudgeB(BaseJudge):
        name = "collide_v1"
        description = "second"
        prompt_variant = "x/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:  # pragma: no cover
            raise NotImplementedError

    reg.register(JudgeA)
    with pytest.raises(ValueError):
        reg.register(JudgeB)


def test_register_decorator_is_idempotent_for_same_class() -> None:
    """Reimporting a module should not raise."""
    reg = JudgeRegistry()

    class JudgeReimport(BaseJudge):
        name = "reimport_v1"
        description = "x"
        prompt_variant = "x/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:  # pragma: no cover
            raise NotImplementedError

    reg.register(JudgeReimport)
    reg.register(JudgeReimport)
    assert reg.names() == ["reimport_v1"]


def test_select_filters_by_name() -> None:
    reg = JudgeRegistry()

    class JudgeOne(BaseJudge):
        name = "one"
        description = "x"
        prompt_variant = "x/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:  # pragma: no cover
            raise NotImplementedError

    class JudgeTwo(BaseJudge):
        name = "two"
        description = "x"
        prompt_variant = "x/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:  # pragma: no cover
            raise NotImplementedError

    reg.register(JudgeOne)
    reg.register(JudgeTwo)
    assert [c.name for c in reg.select(["two"])] == ["two"]
    assert [c.name for c in reg.select(None)] == ["one", "two"]
