"""Kaggriculture Agent V8 Titan (100k+ Target Engine)

Architectural Focus:
1. Full Land Expansion Protocol (NE -> SW -> SE quad acquisition).
2. Maximum Labor Scaling (4-6 Hired Hands with zero-friction parallel dispatch).
3. Compound Strawberry/Melon Mass Production + Livestock Swarm.
4. Active Shed Capacity Throttling (< 80 items) to prevent discard waste.
5. Endogenous Market Arbitrage + Metered Demand Dumping.
"""

CROPS = {
    "WHEAT": {"seed": 10, "first": 2, "maxday": 4, "yield": 6, "ongoing": False},
    "CARROT": {"seed": 20, "first": 2, "maxday": 3, "yield": 4, "ongoing": False},
    "TOMATO": {"seed": 50, "first": 8, "maxday": 8, "yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first": 10, "maxday": 10, "yield": 4, "ongoing": True},
    "MELON": {"seed": 80, "first": 10, "maxday": 12, "yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP", "product": "EGG"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "product": "WOOL"},
    "COW": {"cost": 600, "structure": "PASTURE", "product": "MILK"},
}

BASE = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60,
    "STRAWBERRY": 120, "MELON": 250,
    "EGG": 50, "MILK": 160, "WOOL": 200,
}

PRODUCTS = ("MELON", "STRAWBERRY", "TOMATO", "WOOL", "MILK", "EGG", "CARROT", "WHEAT")


def _i(x, d=0):
    try: return int(x)
    except Exception: return d


def _f(x, d=0.0):
    try: return float(x)
    except Exception: return d


def _pos(x):
    try: return (int(x[0]), int(x[1]))
    except Exception: return (0, 0)


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_to(a, b):
    x, y = a
    tx, ty = b
    if x < tx: return ["EAST"]
    if x > tx: return ["WEST"]
    if y < ty: return ["SOUTH"]
    if y > ty: return ["NORTH"]
    return ["PASS"]


def prices(obs):
    return dict((obs.get("market") or {}).get("prices") or {})


def private(obs):
    return obs.get("private") or {}


def tiles(farm):
    return farm.get("tiles") or []


def empty_tiles(farm):
    out = []
    for y, row in enumerate(tiles(farm)):
        for x, t in enumerate(row):
            if t is None:
                out.append((x, y))
    return out


def structures(farm, kind=None):
    out = []
    for y, row in enumerate(tiles(farm)):
        for x, t in enumerate(row):
            if isinstance(t, dict) and (kind is None or t.get("kind") == kind):
                out.append(((x, y), t))
    return out


def shed_access(farm):
    n = len(tiles(farm)) or 10
    h = n // 2
    return [(max(0, h-1), max(0, h-1)), (h, max(0, h-1)),
            (max(0, h-1), h), (h, h)]


def nearest(pos, pts):
    return min(pts, key=lambda q: dist(pos, q)) if pts else None


def choose_titan_crop(obs, farm, priv):
    day = _i(obs.get("day"))
    money = _f(farm.get("money"))
    seeds = priv.get("seeds") or {}

    # Late game cash conversion (Days 22-30)
    if day >= 22:
        return "CARROT" if _i(seeds.get("CARROT", 0)) > 0 or money > 200 else "WHEAT"

    # Peak Industrial Expansion Phase (Days 4-21)
    if money >= 1500:
        if day <= 14:
            return "STRAWBERRY"  # Compounding ongoing harvest
        return "MELON"       # High-burst profit harvest

    if money >= 400:
        return "TOMATO"
    return "CARROT" if money >= 100 else "WHEAT"


def scan_titan_jobs(farm, obs):
    day = _i(obs.get("day"))
    jobs = []
    empty = []
    animal_count = 0

    for y, row in enumerate(tiles(farm)):
        for x, t in enumerate(row):
            p = (x, y)
            if t is None:
                empty.append(p)
                continue
            if t == "LOCKED" or not isinstance(t, dict):
                continue
            
            k = t.get("kind")
            if k == "WEED":
                jobs.append((0, "DIG", p))
            elif k == "PLANT":
                crop = t.get("crop", "WHEAT")
                rule = CROPS.get(crop, CROPS["WHEAT"])
                age = day - _i(t.get("planted_day"), day)
                yld = _i(t.get("yield_units"))
                
                if yld > 0 and age >= rule["first"]:
                    # Highest priority harvest on high-margin cash crops
                    prio = 0.2 if crop in ("MELON", "STRAWBERRY") else 0.8
                    jobs.append((prio, "HARVEST", p))
                elif not t.get("watered_today", False):
                    if crop in ("STRAWBERRY", "MELON", "TOMATO"):
                        jobs.append((1.5, "WATER", p))
            elif k in ("COOP", "PASTURE"):
                if t.get("animal"):
                    animal_count += 1
                    if _i(t.get("yield_units")) > 0:
                        jobs.append((0.5, "HARVEST", p))
                    if not t.get("fed_today", False):
                        jobs.append((1.0, "FEED", p))
                    if not t.get("cared_today", False):
                        jobs.append((2.0, "CARE", p))

    jobs.sort(key=lambda z: z[0])
    return jobs, empty, animal_count


def schedule_titan_workers(obs, farm, priv):
    jobs, empty, animal_count = scan_titan_jobs(farm, obs)
    farmer = _pos(farm.get("farmer"))
    hands = [_pos(x) for x in (farm.get("hands") or [])]
    positions = [farmer] + hands
    
    invs_raw = priv.get("inventories") or []
    invs = [
        dict(invs_raw[i]) if i < len(invs_raw) and isinstance(invs_raw[i], dict) else {} 
        for i in range(len(positions))
    ]
    access = shed_access(farm)
    assigned = [None] * len(positions)
    claimed_targets = set()

    # 1. Harvest & Maintenance Operations
    for job in jobs:
        target = job[2]
        if target in claimed_targets:
            continue
        
        candidates = [(dist(p, target), i) for i, p in enumerate(positions) if assigned[i] is None]
        if not candidates:
            continue
        
        _, i = min(candidates)
        p = positions[i]
        
        if p == target:
            assigned[i] = [job[1]]
        else:
            assigned[i] = step_to(p, target)
        claimed_targets.add(target)

    # 2. Maximum Industrial Planting
    day = _i(obs.get("day"))
    crop = choose_titan_crop(obs, farm, priv)
    seeds = priv.get("seeds") or {}

    if day < 27 and empty:
        for p in empty:
            candidates = [(dist(pos, p), i) for i, pos in enumerate(positions) if assigned[i] is None]
            if not candidates:
                break
            
            d, i = min(candidates)
            if d <= 12:
                if positions[i] == p:
                    if _i(seeds.get(crop, 0)) > 0 or _f(farm.get("money")) >= CROPS[crop]["seed"]:
                        assigned[i] = ["PLANT", crop]
                else:
                    assigned[i] = step_to(positions[i], p)

    # 3. Offload Logistics
    for i, p in enumerate(positions):
        if assigned[i] is not None:
            continue
        
        cargo = sum(_i(v) for v in invs[i].values() if isinstance(v, (int, float)))
        if cargo > 0:
            a = nearest(p, access)
            if p == a:
                assigned[i] = ["DROP"]
            else:
                assigned[i] = step_to(p, a)
        else:
            t = nearest(p, empty) if empty else None
            assigned[i] = step_to(p, t) if t else ["PASS"]

    return assigned, animal_count


def titan_market_engine(obs, farm, priv, animal_count):
    day = _i(obs.get("day"))
    hour = _i(obs.get("hour"))
    money = _f(farm.get("money"))
    shed = dict(priv.get("shed") or {})
    seeds = dict(priv.get("seeds") or {})
    ps = prices(obs)
    orders = []

    total_shed = sum(_i(v) for v in shed.values() if isinstance(v, (int, float)))

    # 1. Product Liquidation & Price Balancing
    for item in PRODUCTS:
        qty = _i(shed.get(item, 0))
        if item == "WHEAT" and animal_count > 0:
            qty = max(0, qty - animal_count * 2)
        
        if qty > 0:
            p = _i(ps.get(item, BASE[item]), BASE[item])
            if total_shed >= 50 or p >= BASE[item] * 0.80 or day >= 24:
                orders.append(["SELL", item, min(qty, 20)])
                if len(orders) >= 6:
                    break

    # 2. Bulk Seed Pipeline Purchasing
    if len(orders) < 10 and day < 26:
        crop = choose_titan_crop(obs, farm, priv)
        cost = CROPS[crop]["seed"]
        have = _i(seeds.get(crop, 0))
        target_stock = 12 if crop in ("MELON", "STRAWBERRY") else 16
        
        if have < target_stock and money > (cost * 4) + 400:
            buy_qty = min(target_stock - have, int((money - 400) // cost))
            if buy_qty > 0:
                orders.append(["BUY_SEED", crop, buy_qty])
                money -= buy_qty * cost

    # 3. Compounding Livestock Swarm
    if len(orders) < 10 and 5 <= day <= 20 and money >= 2000:
        coops = [(p, t) for p, t in structures(farm, "COOP") if not t.get("animal")]
        pastures = [(p, t) for p, t in structures(farm, "PASTURE") if not t.get("animal")]
        
        if coops:
            orders.append(["BUY_ANIMAL", "GOOSE", 1])
            money -= 300
        elif pastures and money >= 3500:
            orders.append(["BUY_ANIMAL", "SHEEP", 1])
            money -= 500

    # 4. Aggressive Land Expansion (Unlock NE -> SW -> SE)
    unlocked = len(farm.get("unlocked_quadrants") or ["NW"])
    empties = len(empty_tiles(farm))
    land_costs = [1000, 2000, 4000]
    
    if len(orders) < 10 and unlocked < 4 and day <= 22:
        cost = land_costs[unlocked - 1]
        if empties <= 3 and money > cost + 1200:
            orders.append(["BUY_LAND"])
            money -= cost

    # 5. Full Labor Force Scaling
    if hour == 0 and len(orders) < 10 and day <= 24:
        hands = len(farm.get("hands") or [])
        target_hands = max(2, (unlocked - 1) * 2)
        if money > 2500 and hands < target_hands:
            orders.append(["HIRE"])

    return orders[:10]


def _safe_agent(obs):
    farms = obs.get("farms") or []
    player = _i(obs.get("player"))
    if not farms or player < 0 or player >= len(farms):
        return {"farmer": ["PASS"], "hands": [], "market": []}

    farm = farms[player]
    priv = private(obs)
    actions, animal_count = schedule_titan_workers(obs, farm, priv)
    orders = titan_market_engine(obs, farm, priv, animal_count)

    # Terminal Step 695+ Complete Cash Clearance
    step = _i(obs.get("day")) * 24 + _i(obs.get("hour"))
    if step >= 695:
        shed = priv.get("shed") or {}
        orders = [["SELL", item, _i(shed.get(item, 0))] for item in PRODUCTS if _i(shed.get(item, 0)) > 0]

    n_hands = len(farm.get("hands") or [])
    if len(actions) < n_hands + 1:
        actions += [["PASS"]] * (n_hands + 1 - len(actions))
        
    return {
        "farmer": actions[0],
        "hands": actions[1:1+n_hands],
        "market": orders[:10],
    }


def agent(obs):
    try:
        return _safe_agent(obs)
    except Exception:
        try:
            n = len((obs.get("farms") or [])[0].get("hands") or [])
        except Exception:
            n = 0
        return {"farmer": ["PASS"], "hands": [["PASS"] for _ in range(n)], "market": []}