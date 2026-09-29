import random

MOVES = ["NORTH", "SOUTH", "EAST", "WEST", "PASS"]


def agent(obs):
    # Simple movement baseline for testing the platform.
    move = random.choice(MOVES)

    return {
        "farmer": [move],
        "hands": [],
        "market": [],
    }
