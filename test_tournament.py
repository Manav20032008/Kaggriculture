import sys
from pathlib import Path
from tournament import run_tournament, load_registered_players

def test_odd_tournament():
    players = load_registered_players()
    if len(players) < 3:
        print("Need at least 3 players")
        return

    # Use 3 players
    three_players = players[:3]
    print(f"\n--- Testing 3-player tournament (BYE test): {[p['username'] for p in three_players]} ---")
    
    events = []
    def on_prog(evt, data):
        events.append((evt, data))
        if evt == "ROUND_START":
            print(f"  [Progress] Round {data['round']} started. Bye player: {data['byePlayer']}")
        elif evt == "MATCH_END":
            print(f"  [Progress] Match done: {data['player1']} ({data['p1Score']}) vs {data['player2']} ({data['p2Score']}) -> Winner: {data['winner']}")
        elif evt == "TOURNAMENT_END":
            print(f"  [Progress] Tournament ended! Champion: {data['champion']['username']}")

    res = run_tournament(three_players, seed=20260929, random_seed=42, on_progress=on_prog)
    assert res["champion"] is not None, "Champion should not be None"
    assert res["totalRounds"] == 2, f"Expected 2 rounds for 3 players, got {res['totalRounds']}"
    assert len(res["history"]) == 2, f"Expected 2 matches total (1 in R1 + 1 in R2), got {len(res['history'])}"
    print(f"*** 3-Player BYE test PASSED! Champion: {res['champion']['username']} ***\n")

if __name__ == "__main__":
    test_odd_tournament()
