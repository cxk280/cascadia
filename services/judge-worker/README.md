# cascadia-judge

Judge worker for Cascadia. Consumes shadow-routed response pairs (cheap vs expensive) and emits scored verdicts with full provenance.

Architecture follows the SOLID Agent Swarms pattern — see [`../../SOLID.md`](../../SOLID.md) at the repo root.

## Quick start

```bash
cd services/judge-worker
pip install -e ".[dev]"
pytest                                                 # 0 external calls
cascadia-judge --fixture tests/fixtures/pairwise_v1_basic.json
```

The `--fixture` flag uses `ScriptedLLMClient`, so the demo runs offline with no API keys.

## Layout

| Path                          | Role                                                                  |
| ----------------------------- | --------------------------------------------------------------------- |
| `cascadia_judge/llm/`         | `LLMClient` ABC + provider adapters + test doubles. Only `httpx`.     |
| `cascadia_judge/judges/`      | `BaseJudge` ABC + `@register_judge` decorator + concrete judges.      |
| `cascadia_judge/executor.py`  | `JudgeExecutor` Protocol + `AsyncioJudgeExecutor`.                    |
| `cascadia_judge/orchestrator.py` | Composition root. Holds registry + executor + clients.             |
| `cascadia_judge/cli.py`       | Entrypoint. Wires concrete implementations at the edge.               |
| `tests/`                      | Unit tests using `FakeLLMClient` / `ScriptedLLMClient`. No network.   |

## Adding a judge

```python
from cascadia_judge.judges.base import BaseJudge, register_judge

@register_judge
class MyJudge(BaseJudge):
    name = "my_judge_v1"
    description = "..."
    prompt_variant = "my/v1"

    async def judge(self, pair): ...
```

No orchestrator edits, no CLI edits. The registry discovers it on import.
