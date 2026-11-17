export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "include",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check that the backend is running.", 0);
  }
  const result = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      result?.error || "The server is unavailable. Check that the backend is running.",
      response.status,
    );
  return result as T;
}

export type User = { id: string; email: string; createdAt: string };
export type Profile = {
  firstName?: string;
  lastName?: string;
  phone?: string;
  dateOfBirth?: string;
  location?: string;
  heightCm?: number;
  weightKg?: number;
  dailyStepGoal?: number;
};
export type Device = { id: string; identifier: string; name: string; created_at: string };
export type Summary = { steps: number; averageHeartRate: number | null; samples: number };
export type ActivityDay = { date: string; steps: number; averageHeartRate: number | null };

// Called by the Bluetooth reader after decoding firmware notifications.
// Preserve sampleId and payload on retries. Steps are increments, not counters.
export type Measurement = {
  sampleId: string;
  recordedAt: string;
  steps: number;
  heartRate?: number | null;
  battery?: number | null;
};
export function uploadMeasurements(deviceId: string, measurements: Measurement[]) {
  return api<{ inserted: number; duplicates: number }>(
    `/devices/${encodeURIComponent(deviceId)}/measurements`,
    "POST",
    { measurements },
  );
}
