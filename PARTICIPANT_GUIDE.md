# Kaggriculture agent interface

Upload a UTF-8 Python file named `agent.py` (the supplied `main.py` starter is
also accepted), at most 100 KB, that defines a synchronous `agent(obs)`
function. The evaluator calls it once each turn. The function must return an
action dictionary; a compact example is in
[`NITW_Farm_AI_Participant_Starter/main.py`](NITW_Farm_AI_Participant_Starter/main.py).

```python
def agent(obs):
    return {"farmer": ["PASS"], "hands": [], "market": []}
```

The observation has `player`, `step`, `day`, `hour`, `farms`, `private`,
`market`, and `town` fields. `farms` contains both public farms. Each farm
contains `money`, `tiles[y][x]`, `farmer`, `hands`, `unlocked_quadrants`, and
`hires_today`. `private` contains your `shed`, `seeds`, and carried
`inventories`. The README's **Observation** and **Action format** sections
describe each field and action in full.

Return a mapping with `farmer` set to one operation and its arguments,
`hands` set to one operation per hired hand, and `market` set to an ordered list
of market orders. Movement operations are `NORTH`, `SOUTH`, `EAST`, `WEST`, and
`PASS`. Other farmer operations include `PLANT`, `WATER`, `HARVEST`, `DIG`,
`FERTILIZE`, `BUILD_COOP`, `BUILD_PASTURE`, `FEED`, `CARE`,
`COLLECT_FERTILIZER`, `PICKUP`, `PLACE`, and `DROP`. Market orders include
`BUY_SEED`, `BUY_PRODUCT`, `BUY_ANIMAL`, `SELL`, `HIRE`, and `BUY_LAND`.

Invalid game actions are silently treated as no-ops by Kaggriculture. A Python
exception is recorded as `PLAYER_ERROR` and receives zero for that round. The
evaluator enforces a 120-second per-match timeout by default; a timed-out child
is terminated and recorded as `TIMEOUT`. These failures do not stop other
participants' jobs. Infrastructure failures are recorded separately as
`SYSTEM_ERROR` and retried rather than charged as player errors. Evaluation
runs in a separate child process. Local subprocess isolation protects the API
process but is not an OS security sandbox; use the included Docker worker for
deployment with untrusted public submissions.

The event runs exactly three non-elimination rounds. After Round 1, upload a
new agent for a later round or upload nothing to keep using your latest valid
submission. Each round freezes the selected submission at the close of its
upload window. Round scores are added to the cumulative total.
