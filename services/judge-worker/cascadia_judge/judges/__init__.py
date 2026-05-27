from cascadia_judge.judges.base import REGISTRY, BaseJudge, JudgeRegistry, register_judge

# Side-effect imports — each module registers its judge class on import.
from cascadia_judge.judges import pairwise_preference as _pairwise  # noqa: F401
from cascadia_judge.judges import pairwise_swapped as _pairwise_swapped  # noqa: F401
from cascadia_judge.judges import rubric as _rubric  # noqa: F401

__all__ = ["REGISTRY", "BaseJudge", "JudgeRegistry", "register_judge"]
