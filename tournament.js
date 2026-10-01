const { exec } = require('child_process');
const path = require('path');

// Shuffle participants (Fisher-Yates)
function shuffle(array) {
  const arr = [...array];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// 1. Group participants into 1v1 pairs
function createPairs(participants) {
  const shuffled = shuffle(participants);
  const pairs = [];

  for (let i = 0; i < shuffled.length; i += 2) {
    if (i + 1 < shuffled.length) {
      pairs.push({ p1: shuffled[i], p2: shuffled[i + 1] });
    } else {
      // Unpaired player gets an automatic BYE pass
      pairs.push({ p1: shuffled[i], p2: null, autoQualify: true });
    }
  }
  return pairs;
}

// 2. Execute a single match via run_match.py
function runSingleMatch(p1Path, p2Path, seed = 42) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(__dirname, 'run_match.py');
    const command = `py "${scriptPath}" --agent1 "${p1Path}" --agent2 "${p2Path}" --seed ${seed}`;

    exec(command, (error, stdout, stderr) => {
      if (error && !stdout) {
        return reject(new Error(stderr || error.message));
      }
      try {
        // Find JSON block in stdout (filters out OpenSpiel/Kaggle print noise)
        const jsonMatch = stdout.match(/\{[\s\S]*?\}/g);
        if (!jsonMatch) throw new Error(`No JSON output found. Raw stdout:\n${stdout}`);
        
        const result = JSON.parse(jsonMatch[jsonMatch.length - 1]);
        if (result.error) return reject(new Error(result.error));
        
        resolve(result);
      } catch (e) {
        reject(new Error(`Failed to parse match output: ${e.message}\nStdout: ${stdout}`));
      }
    });
  });
}

// 3. Run a single Knockout Round
async function runKnockoutRound(participants, roundNumber = 1) {
  console.log(`\n=================== STARTING ROUND ${roundNumber} ===================`);
  console.log(`Active Players (${participants.length}): ${participants.map(p => p.username).join(', ')}`);

  const pairs = createPairs(participants);
  const winners = [];
  const matchLogs = [];

  for (const pair of pairs) {
    if (pair.autoQualify) {
      console.log(`[BYE] ${pair.p1.username} advances automatically.`);
      winners.push(pair.p1);
      matchLogs.push({
        player1: pair.p1.username,
        player2: "BYE",
        winner: pair.p1.username,
        status: "AUTO_QUALIFIED"
      });
      continue;
    }

    console.log(`[MATCH] ${pair.p1.username} VS ${pair.p2.username}...`);

    try {
      const match = await runSingleMatch(pair.p1.filePath, pair.p2.filePath);
      const winner = match.winner === 0 ? pair.p1 : pair.p2;
      const loser = match.winner === 0 ? pair.p2 : pair.p1;

      winners.push(winner);
      matchLogs.push({
        player1: pair.p1.username,
        player2: pair.p2.username,
        p1Score: match.p1Score,
        p2Score: match.p2Score,
        winner: winner.username,
        eliminated: loser.username
      });

      console.log(`  -> Winner: ${winner.username} (Score: ${match.winner === 0 ? match.p1Score : match.p2Score} vs ${match.winner === 0 ? match.p2Score : match.p1Score})`);
    } catch (err) {
      console.error(`  -> Match failed between ${pair.p1.username} and ${pair.p2.username}:`, err.message);
    }
  }

  return { qualified: winners, matches: matchLogs };
}

// 4. Run Full Tournament until 1 Champion remains
async function runFullTournament(participants) {
  let currentPlayers = [...participants];
  let round = 1;
  const fullTournamentHistory = [];

  while (currentPlayers.length > 1) {
    const roundResult = await runKnockoutRound(currentPlayers, round);
    fullTournamentHistory.push({
      round: round,
      matches: roundResult.matches
    });
    currentPlayers = roundResult.qualified;
    round++;
  }

  const champion = currentPlayers[0] || null;
  console.log(`\n🏆 TOURNAMENT CHAMPION: ${champion ? champion.username : 'None'} 🏆`);

  return {
    champion: champion,
    history: fullTournamentHistory
  };
}

module.exports = { runSingleMatch, runKnockoutRound, runFullTournament };