export type Prediction = { timestampMs: number; activity: string; confidence: number; receivedAt: Date };

export function parsePrediction(line: string): Prediction | null {
  const match = /^# pred t=(\d+) class=([^\s]+) p=(\d+(?:\.\d+)?)\s*$/.exec(line.trim());
  if (!match) return null;
  const timestampMs = Number(match[1]);
  const confidence = Number(match[3]);
  if (!Number.isSafeInteger(timestampMs) || confidence < 0 || confidence > 1) return null;
  return { timestampMs, activity: match[2], confidence, receivedAt: new Date() };
}

export interface SerialPort {
  readable: ReadableStream<Uint8Array> | null;
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
}
export interface Serial { requestPort(): Promise<SerialPort> }

export async function openSerial(serial: Serial | undefined): Promise<SerialPort> {
  if (!serial) throw new Error("USB serial is unavailable. Use Chrome or Edge on localhost or HTTPS.");
  const port = await serial.requestPort();
  await port.open({ baudRate: 115200 });
  return port;
}

export async function readPredictions(port: SerialPort, onPrediction: (prediction: Prediction) => void, signal: AbortSignal): Promise<void> {
  if (!port.readable) throw new Error("The serial port is not readable.");
  const reader = port.readable.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const lines = pending.split("\n");
      pending = lines.pop() || "";
      if (pending.length > 4096) pending = "";
      for (const line of lines) {
        const prediction = parsePrediction(line);
        if (prediction) onPrediction(prediction);
      }
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    reader.releaseLock();
  }
}
