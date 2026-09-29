from dataclasses import dataclass, asdict
from typing import Any
import json
from pathlib import Path


@dataclass
class EvaluationResult:
    team: str
    score: float
    reward: float
    status: str
    runtime_seconds: float
    seed: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
