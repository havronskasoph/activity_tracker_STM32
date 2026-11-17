import test from "node:test";
import assert from "node:assert/strict";
import { pairDevice } from "../src/bluetooth.ts";

test("opens the real picker contract, connects GATT, and permits configured service", async () => {
  const device = new EventTarget();
  let disconnected = false;
  device.id = "browser-id";
  device.gatt = {
    connected: false,
    async connect() {
      this.connected = true;
    },
    disconnect() {
      disconnected = true;
    },
  };
  let options;
  const bluetooth = {
    async requestDevice(value) {
      options = value;
      return device;
    },
  };
  assert.equal(await pairDevice(bluetooth, "battery_service"), device);
  assert.deepEqual(options, { acceptAllDevices: true, optionalServices: ["battery_service"] });
  assert.equal(disconnected, false);
});

test("unsupported browser and failed connections produce errors without a fake connection", async () => {
  await assert.rejects(pairDevice(undefined), /Bluetooth is unavailable/);
  let disconnected = false;
  const device = {
    gatt: {
      connected: false,
      async connect() {
        throw new Error("Out of range");
      },
      disconnect() {
        disconnected = true;
      },
    },
  };
  await assert.rejects(
    pairDevice({
      async requestDevice() {
        return device;
      },
    }),
    /Out of range/,
  );
  assert.equal(disconnected, true);
});
