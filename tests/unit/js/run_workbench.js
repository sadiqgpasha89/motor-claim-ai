// Runs the site's settlement engine for a list of input overrides (JSON on stdin) and prints the results as JSON.
// Used by tests/unit/test_settlement_workbench.py to prove the browser engine matches the Python engine.
"use strict";
const path = require("path");
const siteDir = path.resolve(__dirname, "..", "..", "..", "site");
const data = require(path.join(siteDir, "settlement-workbench-data.js"));
const engine = require(path.join(siteDir, "settlement-engine.js"));

let raw = "";
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  const cases = JSON.parse(raw);
  const results = cases.map((overrides) => engine.build(data, engine.inputsFromMapping(data, overrides)));
  process.stdout.write(JSON.stringify(results));
});
