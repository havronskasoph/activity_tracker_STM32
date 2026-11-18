import { parsePrediction, type Prediction } from "./predictions.ts";

// Minimal Web Bluetooth types used here; the DOM library does not include them.
export interface BluetoothCharacteristic extends EventTarget {
  value?: DataView;
  startNotifications(): Promise<BluetoothCharacteristic>;
  stopNotifications(): Promise<BluetoothCharacteristic>;
}
export interface BluetoothService {
  getCharacteristic(uuid: string): Promise<BluetoothCharacteristic>;
}
export interface BluetoothDevice extends EventTarget {
  id: string;
  name?: string;
  gatt?: { connected: boolean; connect(): Promise<unknown>; disconnect(): void; getPrimaryService(uuid: string): Promise<BluetoothService> };
}
export interface Bluetooth {
  requestDevice(options: {
    acceptAllDevices: true;
    optionalServices: string[];
  }): Promise<BluetoothDevice>;
}

export async function pairDevice(
  bluetooth: Bluetooth | undefined,
  service?: string,
): Promise<BluetoothDevice> {
  if (!bluetooth)
    throw new Error(
      "Bluetooth is unavailable. Open this app in Chrome or Edge on localhost or HTTPS.",
    );
  // Keep requestDevice before any await: the browser requires a user gesture.
  const device = await bluetooth.requestDevice({
    acceptAllDevices: true,
    optionalServices: service ? [service] : [],
  });
  if (!device.gatt)
    throw new Error("This device does not offer a Bluetooth Low Energy GATT connection.");
  try {
    await device.gatt.connect();
    if (!device.gatt.connected)
      throw new Error("The Bluetooth device disconnected. Please try again.");
    return device;
  } catch (error) {
    device.gatt.disconnect();
    throw error;
  }
}

// The firmware sends each prediction as a CRLF-terminated line, split across
// notifications of at most 18 bytes, so payloads are accumulated until a "\n"
// arrives before parsing. See firmware/BLE_SETUP.md.
export async function subscribePredictions(
  device: BluetoothDevice,
  serviceUuid: string,
  characteristicUuid: string,
  onPrediction: (prediction: Prediction) => void,
): Promise<() => void> {
  if (!serviceUuid || !characteristicUuid)
    throw new Error("Set both VITE_BLE_SERVICE_UUID and VITE_BLE_CHARACTERISTIC_UUID to receive predictions.");
  if (!device.gatt?.connected) throw new Error("Bluetooth device is not connected.");
  const service = await device.gatt.getPrimaryService(serviceUuid);
  const characteristic = await service.getCharacteristic(characteristicUuid);
  const decoder = new TextDecoder();
  let pending = "";
  const listener = () => {
    if (!characteristic.value) return;
    pending += decoder.decode(characteristic.value, { stream: true });
    const lines = pending.split("\n");
    pending = lines.pop() || "";
    if (pending.length > 512) pending = "";
    for (const line of lines) {
      const prediction = parsePrediction(line);
      if (prediction) onPrediction(prediction);
    }
  };
  characteristic.addEventListener("characteristicvaluechanged", listener);
  try {
    await characteristic.startNotifications();
  } catch (error) {
    characteristic.removeEventListener("characteristicvaluechanged", listener);
    throw error;
  }
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    characteristic.removeEventListener("characteristicvaluechanged", listener);
    void characteristic.stopNotifications().catch(() => {});
  };
}
