import os
import random
import subprocess
import json

from py_env import get_kaggle_python

# Sample agent paths inside cloned repository
starter_agent = os.path.join(os.path.dirname(__file__), 'NITW_Farm_AI_Participant_Starter', 'main.py')

dummy_participants = [
    {"username": "Player_Alpha", "filePath": starter_agent},
    {"username": "Player_Beta", "filePath": starter_agent},
    {"username": "Player_Gamma", "filePath": starter_agent},
    {"username": "Player_Delta", "filePath": starter_agent}
]

def run_match(p1_path, p2_path):
    python_exe = get_kaggle_python()
    cmd = [python_exe, "run_match.py", "--agent1", p1_path, "--agent2", p2_path]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        raise Exception(f"Match Error: {stderr or stdout}")
        
    return json.loads(stdout)

def run_tournament(participants):
    random.shuffle(participants)
    pairs = [participants[i:i + 2] for i in range(0, len(participants), 2)]
    
    winners = []
    results = []
    
    for pair in pairs:
        p1, p2 = pair[0], pair[1]
        print(f"Running 1v1 Match: {p1['username']} vs {p2['username']}...")
        
        match_data = run_match(p1['filePath'], p2['filePath'])
        winner = p1 if match_data['winner'] == 0 else p2
        loser = p2 if match_data['winner'] == 0 else p1
        
        winners.append(winner)
        results.append({
            "p1": p1['username'],
            "p2": p2['username'],
            "p1Score": match_data['p1Score'],
            "p2Score": match_data['p2Score'],
            "winner": winner['username'],
            "eliminated": loser['username']
        })
        
    return winners, results

if __name__ == "__main__":
    print("--- STARTING 1v1 KNOCKOUT TOURNAMENT TEST ---")
    qualified, matches = run_tournament(dummy_participants)
    
    print("\n================ MATCH RESULTS ================")
    print(json.dumps(matches, indent=2))
    
    print("\n================ QUALIFIED PLAYERS ================")
    print([p['username'] for p in qualified])