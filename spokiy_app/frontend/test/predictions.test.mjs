import test from "node:test";
import assert from "node:assert/strict";
import { parsePrediction, readPredictions, openSerial } from "../src/predictions.ts";

test("parses firmware predictions and rejects unrelated or invalid lines", () => {
  const p = parsePrediction("# pred t=25670 class=Lying p=0.969\r");
  assert.equal(p.activity, "Lying");
  assert.equal(p.timestampMs, 25670);
  assert.equal(p.confidence, 0.969);
  assert.equal(parsePrediction("# rate=27 Hz"), null);
  assert.equal(parsePrediction("# pred t=1 class=Walk p=1.500"), null);
});

test("reads split serial lines and ignores status and CSV", async () => {
  const encoder = new TextEncoder();
  const chunks = ["# pred t=12 class=Wal", "king p=0.750\r\n42,0,0,0\r\n# pred t=20 class=Lying p=0.969\r\n"];
  const port = { readable: new ReadableStream({ start(controller) { for (const chunk of chunks) controller.enqueue(encoder.encode(chunk)); controller.close(); } }) };
  const received = [];
  await readPredictions(port, p => received.push(p), new AbortController().signal);
  assert.deepEqual(received.map(p => p.activity), ["Walking", "Lying"]);
});

test("opens at the firmware baud rate", async () => {
  let options;
  const port = { async open(value) { options = value; } };
  assert.equal(await openSerial({ async requestPort() { return port; } }), port);
  assert.deepEqual(options, { baudRate: 115200 });
  await assert.rejects(openSerial(undefined), /USB serial is unavailable/);
});
