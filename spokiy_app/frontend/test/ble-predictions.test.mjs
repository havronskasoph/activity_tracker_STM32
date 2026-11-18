import test from "node:test";
import assert from "node:assert/strict";
import { subscribePredictions } from "../src/bluetooth.ts";

test("subscribes to the configured characteristic and decodes notification bytes", async () => {
  const characteristic = new EventTarget();
  let starts = 0, stops = 0;
  characteristic.startNotifications = async () => { starts++; return characteristic; };
  characteristic.stopNotifications = async () => { stops++; return characteristic; };
  const service = { async getCharacteristic(uuid) { assert.equal(uuid, "char-id"); return characteristic; } };
  const device = { gatt: { connected: true, async getPrimaryService(uuid) { assert.equal(uuid, "service-id"); return service; } } };
  const values = [];
  const unsubscribe = await subscribePredictions(device, "service-id", "char-id", value => values.push(value));
  const encode = text => new TextEncoder().encode(text);
  const bytes = encode("# pred t=25670 class");
  const padded = new Uint8Array(bytes.length + 4); padded.set(bytes, 2);
  characteristic.value = new DataView(padded.buffer, 2, bytes.length);
  characteristic.dispatchEvent(new Event("characteristicvaluechanged"));
  assert.equal(values.length, 0);
  characteristic.value = new DataView(encode("=Lying p=0.969\r\n").buffer);
  characteristic.dispatchEvent(new Event("characteristicvaluechanged"));
  assert.equal(values.length, 1);
  assert.equal(values[0].activity, "Lying");
  assert.equal(values[0].confidence, 0.969);
  characteristic.value = new DataView(new TextEncoder().encode("# rate=27 Hz\n").buffer);
  characteristic.dispatchEvent(new Event("characteristicvaluechanged"));
  assert.equal(values.length, 1);
  unsubscribe(); unsubscribe();
  characteristic.dispatchEvent(new Event("characteristicvaluechanged"));
  assert.equal(values.length, 1);
  assert.equal(starts, 1); assert.equal(stops, 1);
});

test("reports missing configuration and notification failures", async () => {
  await assert.rejects(subscribePredictions({}, "", "", () => {}), /VITE_BLE_SERVICE_UUID/);
  const characteristic = new EventTarget();
  characteristic.startNotifications = async () => { throw new Error("notifications unavailable"); };
  const device = { gatt: { connected: true, async getPrimaryService() { return { async getCharacteristic() { return characteristic; } }; } } };
  await assert.rejects(subscribePredictions(device, "svc", "char", () => {}), /notifications unavailable/);
});
