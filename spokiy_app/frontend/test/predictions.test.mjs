import test from "node:test";
import assert from "node:assert/strict";
import { parsePrediction } from "../src/predictions.ts";

test("parses firmware predictions and rejects unrelated or invalid lines", () => {
  const p = parsePrediction("# pred t=25670 class=Lying p=0.969\r");
  assert.equal(p.activity, "Lying");
  assert.equal(p.timestampMs, 25670);
  assert.equal(p.confidence, 0.969);
  assert.equal(parsePrediction("# rate=27 Hz"), null);
  assert.equal(parsePrediction("# pred t=1 class=Walk p=1.500"), null);
});

