def agent(obs):
    """Starter template for participants.

    Replace this strategy with your own.
    """

    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]

    market = []

    # Example: buy one wheat seed if we have none.
    if private["seeds"].get("WHEAT", 0) == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])

    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]

    if tile is None and private["seeds"].get("WHEAT", 0) > 0:
        farmer_action = ["PLANT", "WHEAT"]

    elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
        if not tile.get("watered_today", False):
            farmer_action = ["WATER"]
        elif (
            tile.get("crop") == "WHEAT"
            and obs["day"] - tile.get("planted_day", obs["day"]) >= 2
        ):
            farmer_action = ["HARVEST"]
        else:
            farmer_action = ["PASS"]
    else:
        farmer_action = ["PASS"]

    wheat = private["shed"].get("WHEAT", 0)
    if wheat:
        market.append(["SELL", "WHEAT", wheat])

    return {
        "farmer": farmer_action,
        "hands": [],
        "market": market,
    }
