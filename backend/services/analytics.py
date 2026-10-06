"""Replay-backed analytics using only fields recorded by Kaggriculture."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}


def load_replay(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _farm_counts(farm: dict) -> tuple[int, int, float]:
    animals = occupied = unlocked = 0
    for row in farm.get("tiles", []):
        for tile in row:
            if tile == "LOCKED":
                continue
            unlocked += 1
            if tile is not None:
                occupied += 1
            if isinstance(tile, dict) and tile.get("kind") in {"COOP", "PASTURE"} and tile.get("animal"):
                animals += 1
    utilization = occupied / unlocked if unlocked else 0.0
    return animals, unlocked, utilization


def analyze_replay(path: Path, player: int = 0) -> dict:
    replay = load_replay(path)
    steps = replay.get("steps", [])
    if not steps:
        raise ValueError("Replay contains no steps.")

    action_counts = Counter()
    products_sold = Counter()
    peak_cash = 0.0
    series = []

    for index, pair in enumerate(steps):
        state = pair[player]
        obs = state.get("observation", {})
        farm = obs.get("farms", [{}, {}])[player]
        money = float(farm.get("money", 0))
        peak_cash = max(peak_cash, money)
        action = state.get("action") or {}
        unit_actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []))
        for unit_action in unit_actions:
            if unit_action:
                action_counts[str(unit_action[0]).upper()] += 1
        for market_action in action.get("market", []):
            if not market_action:
                continue
            op = str(market_action[0]).upper()
            action_counts[op] += 1
            if op == "SELL" and len(market_action) >= 3:
                products_sold[str(market_action[1])] += int(market_action[2])

        if index % 12 == 0 or index == len(steps) - 1:
            animals, _, utilization = _farm_counts(farm)
            series.append({
                "step": index,
                "money": money,
                "workers": 1 + len(farm.get("hands", [])),
                "animals": animals,
                "utilization": round(utilization * 100, 2),
                "prices": obs.get("market", {}).get("prices", {}),
            })

    final_state = steps[-1][player]
    final_obs = final_state.get("observation", {})
    final_farm = final_obs.get("farms", [{}, {}])[player]
    final_animals, _, final_utilization = _farm_counts(final_farm)
    return {
        "steps": len(steps),
        "finalCash": float(final_farm.get("money", final_state.get("reward", 0) or 0)),
        "peakCash": peak_cash,
        "landQuadrantsUnlocked": len(final_farm.get("unlocked_quadrants", [])),
        "plantsPlanted": action_counts["PLANT"],
        "plantsHarvested": action_counts["HARVEST"],
        "workersHired": action_counts["HIRE"],
        "animalsOwned": final_animals,
        "productsSold": dict(products_sold),
        "idleActions": action_counts["PASS"],
        "movementActions": sum(action_counts[move] for move in MOVES),
        "farmUtilization": round(final_utilization * 100, 2),
        "series": series,
    }


def replay_frame(path: Path, step: int, player: int = 0) -> dict:
    replay = load_replay(path)
    steps = replay.get("steps", [])
    if not steps:
        raise ValueError("Replay contains no steps.")
    step = max(0, min(step, len(steps) - 1))
    state = steps[step][player]
    obs = state.get("observation", {})
    farm = obs.get("farms", [{}, {}])[player]
    return {
        "step": step,
        "totalSteps": len(steps),
        "day": obs.get("day", step // 24),
        "hour": obs.get("hour", step % 24),
        "action": state.get("action"),
        "reward": state.get("reward"),
        "farm": {
            "money": farm.get("money"),
            "tiles": farm.get("tiles", []),
            "farmer": farm.get("farmer"),
            "hands": farm.get("hands", []),
            "unlockedQuadrants": farm.get("unlocked_quadrants", []),
        },
        "marketPrices": obs.get("market", {}).get("prices", {}),
    }
