import json
from pathlib import Path
from typing import Any


class Leaderboard:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def upsert(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.load()

        team = result["team"]
        rows = [r for r in rows if r.get("team") != team]
        rows.append(result)

        rows.sort(
            key=lambda r: (
                float(r.get("score", float("-inf"))),
                -float(r.get("runtime_seconds", float("inf"))),
            ),
            reverse=True,
        )

        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank

        self.path.write_text(
            json.dumps(rows, indent=2),
            encoding="utf-8",
        )

        return rows
