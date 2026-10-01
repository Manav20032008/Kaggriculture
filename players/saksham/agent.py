# ============================================================
# NITW FARM AI CHALLENGE
# ============================================================
#
# Your task:
#   Write an AI agent that maximizes the amount of money
#   in the bank by the end of the Kaggriculture season.
#
# You may change this file.
#
# Your submission MUST define:
#
#   def agent(obs):
#       ...
#
# The evaluator will call your function once every turn.
#
# Observation:
#   obs["player"]
#   obs["step"]
#   obs["day"]
#   obs["hour"]
#   obs["farms"]
#   obs["private"]
#   obs["market"]
#   obs["town"]
#
# Action:
# {
#     "farmer": [op, ...args],
#     "hands": [[op, ...args], ...],
#     "market": [[op, ...args], ...]
# }
#
# Read the event rules before competing.
# ============================================================


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]

    # --------------------------------------------------------
    # Example baseline strategy:
    # buy wheat -> plant -> water -> harvest -> sell
    #
    # Improve this strategy!
    # --------------------------------------------------------

    market = []

    # Buy wheat seeds when we have none.
    if private["seeds"].get("WHEAT", 0) == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])

    # Sell harvested wheat.
    wheat_in_shed = private["shed"].get("WHEAT", 0)
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])

    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]

    # Plant wheat on an empty unlocked tile.
    if tile is None and private["seeds"].get("WHEAT", 0) > 0:
        return {
            "farmer": ["PLANT", "WHEAT"],
            "hands": [],
            "market": market,
        }

    # Manage an existing plant.
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop = tile.get("crop")
        age = obs["day"] - tile.get("planted_day", obs["day"])

        if crop == "WHEAT" and age >= 2:
            return {
                "farmer": ["HARVEST"],
                "hands": [],
                "market": market,
            }

        if not tile.get("watered_today", False):
            return {
                "farmer": ["WATER"],
                "hands": [],
                "market": market,
            }

    return {
        "farmer": ["PASS"],
        "hands": [],
        "market": market,
    }
