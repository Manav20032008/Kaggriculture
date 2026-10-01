const path = require('path');
const { runKnockoutRound } = require('./tournament');

// Path to sample agents inside your cloned repository
const sampleAgent1 = path.join(__dirname, 'NITW_Farm_AI_Participant_Starter', 'agent.py');
const sampleAgent2 = path.join(__dirname, 'NITW_Farm_AI_Participant_Starter', 'agent.py');

// Mock list of 4 uploaded participants
const dummyParticipants = [
  { username: "Player_Alpha", filePath: sampleAgent1 },
  { username: "Player_Beta", filePath: sampleAgent2 },
  { username: "Player_Gamma", filePath: sampleAgent1 },
  { username: "Player_Delta", filePath: sampleAgent2 }
];

async function startTest() {
  console.log("Starting 1v1 Tournament Simulation...\n");
  
  const result = await runKnockoutRound(dummyParticipants);
  
  console.log("\n================ MATCH RESULTS ================");
  console.dir(result.matches, { depth: null });
  
  console.log("\n================ QUALIFIED PLAYERS ================");
  console.log(result.qualified.map(p => p.username));
}

startTest();