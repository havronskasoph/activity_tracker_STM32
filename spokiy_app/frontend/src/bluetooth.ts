// Minimal Web Bluetooth types used here; the DOM library does not include them.
export interface BluetoothDevice extends EventTarget {
  id: string;
  name?: string;
  gatt?: { connected: boolean; connect(): Promise<unknown>; disconnect(): void };
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
