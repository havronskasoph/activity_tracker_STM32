export type Prediction = { timestampMs: number; activity: string; confidence: number; receivedAt: Date };

// Class names by index, mirroring HAR_CLASS_LIST in har_model_config.h.
export const ACTIVITIES = ["Lying", "Stationary", "Walking", "Running", "Stairs"] as const;

// Two wire formats carry the same prediction.
//
// Compact, used over BLE: "<class index> <confidence> <t_ms>". The radio link
// to the module runs at 9600 baud and every extra 18 bytes costs another
// notification plus about 65 ms during which the firmware cannot read the
// accelerometer. Measured on the board: the verbose line dropped the sample
// rate from 27.4 Hz to 18.8 Hz. The compact line fits one notification.
//
// Verbose, used over the USB cable and by tools/watch.py:
// "# pred t=<ms> class=<Name> p=<0.000>".
export function parsePrediction(line: string): Prediction | null {
  const text = line.trim();

  const compact = /^(\d) (\d+(?:\.\d+)?) (\d+)$/.exec(text);
  if (compact) {
    const index = Number(compact[1]);
    const confidence = Number(compact[2]);
    const timestampMs = Number(compact[3]);
    const activity = ACTIVITIES[index];
    if (!activity || !Number.isSafeInteger(timestampMs)) return null;
    if (confidence < 0 || confidence > 1) return null;
    return { timestampMs, activity, confidence, receivedAt: new Date() };
  }

  const verbose = /^# pred t=(\d+) class=([^\s]+) p=(\d+(?:\.\d+)?)$/.exec(text);
  if (!verbose) return null;
  const timestampMs = Number(verbose[1]);
  const confidence = Number(verbose[3]);
  if (!Number.isSafeInteger(timestampMs) || confidence < 0 || confidence > 1) return null;
  return { timestampMs, activity: verbose[2], confidence, receivedAt: new Date() };
}

