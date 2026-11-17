# Spokiy

React/Vite frontend and a Node.js backend for activity measurements read from an STM32 Bluetooth device by the browser.

## Requirements

- Node.js **24 or later** (check `node --version`). The backend uses Node's built-in SQLite and has no third-party dependencies. Node may print a SQLite experimental warning.
- pnpm **10.34.3** for the frontend.
- Two terminals, starting in `spokiy_app/`.

## Run the backend

In PowerShell:

```powershell
cd backend
Copy-Item .env.example .env
npm run dev
```

Use `npm.cmd` if PowerShell blocks the `npm.ps1` script. Copy `.env.example` only for initial setup; preserve your configuration on subsequent runs.

The API listens at **http://127.0.0.1:3001**. Open http://127.0.0.1:3001/api/health to check it. For normal operation without file watching, run `npm start`. Stop with Ctrl+C.

SQLite tables are created automatically in `backend/data/spokiy.sqlite`. Accounts, sessions, profiles, devices, and measurements survive restarts. This directory and `.env` are excluded from Git. Paths are relative to the backend working directory. No separate database installation is needed.

Configuration in `backend/.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `3001` | API port |
| `FRONTEND_ORIGIN` | `http://localhost:8443` | Exact allowed browser origin |
| `DATABASE_PATH` | `./data/spokiy.sqlite` | SQLite file |
| `COOKIE_SECURE` | `false` | Set to `true` behind HTTPS in production |

## Run the frontend

In a second PowerShell terminal:

```powershell
cd frontend
npx.cmd --yes pnpm@10.34.3 install --frozen-lockfile
npx.cmd --yes pnpm@10.34.3 dev
```

Open **http://localhost:8443**. Keep that hostname: switching to `127.0.0.1` changes the origin and cookie behavior. If pnpm is already installed, use `pnpm install --frozen-lockfile` and `pnpm dev` instead. The initial install needs internet access.

Build and preview:

```powershell
npx.cmd --yes pnpm@10.34.3 build
npx.cmd --yes pnpm@10.34.3 exec tsc --noEmit
npx.cmd --yes pnpm@10.34.3 preview
```

Stop the development server before running preview: both use port 8443.

**Integration status:** registration, sign-in, sign-out, session restoration, profile saving, automatic device registration after Bluetooth pairing, and activity charts now use the backend. Start both servers, open the frontend, choose **Create an account**, and use a password of at least 12 characters. The dashboard starts empty until measurements reach the backend. Use **Refresh data** to retrieve newer readings. Today uses your local day; weekly bars use UTC dates.

The frontend sends `/api` requests through Vite to `http://127.0.0.1:3001`, including session cookies. This works in development and preview. If your backend uses a different address, set `$env:API_PROXY_TARGET="http://127.0.0.1:YOUR_PORT"` before starting Vite. If you change the frontend URL, update the backend's `FRONTEND_ORIGIN` and restart it. For production hosting, configure your web server to forward `/api` to the backend; Vite's proxy is a local development/preview feature.

## Bluetooth connection

Click **Connect device**, then **Find Bluetooth devices**. Choose your STM32 tracker in the browser's Bluetooth chooser. The app opens a real BLE GATT connection and automatically registers the selected browser device ID with your account. Use **Disconnect device** to disconnect. Connection indicators reflect the current Bluetooth link, not saved database devices.

Use a browser with Web Bluetooth support, such as Chrome or Edge on Windows. Open the app on localhost for development, or HTTPS in production. The hardware must advertise Bluetooth Low Energy (BLE); Bluetooth Classic serial modules cannot use this GATT flow.

**Current limitation:** device selection and GATT connection are implemented. Measurement subscription, decoding, and automatic uploads cannot be completed until the STM32 firmware service UUID, notification characteristic UUID, and payload layout are supplied. The dialog explicitly distinguishes connection from measurement syncing. No readings are fabricated. Manual registration and JSON upload forms have been removed from the normal connection flow.

If the service UUID is known, set `$env:VITE_BLE_SERVICE_UUID="your-service-uuid"` in the frontend terminal before starting Vite. This grants access to that service during pairing; it does not yet implement its measurement decoder. Once the firmware protocol is available, decoded readings can be sent using `uploadMeasurements` in `frontend/src/api.ts`.

## API

Requests and responses use JSON. Errors return `{ "error": "message" }`. For POST/PATCH requests, send `Content-Type: application/json`, including `{}` for logout. Registration and login set an HttpOnly session cookie valid for seven days; subsequent browser calls must use `credentials: 'include'`. Passwords must contain 12–128 characters and are stored as salted scrypt hashes. Authentication attempts are limited to 20 per minute per connection IP.

| Method | Endpoint | Body / result |
| --- | --- | --- |
| GET | `/api/health` | Public health check |
| POST | `/api/auth/register` | `{ email, password }`; creates account and signs in |
| POST | `/api/auth/login` | `{ email, password }`; signs in |
| POST | `/api/auth/logout` | `{}`; revokes current session |
| GET | `/api/auth/me` | `{ user: { id, email, createdAt } }` |
| GET | `/api/profile` | `{ profile, email }` |
| PATCH | `/api/profile` | Any supported profile fields |
| GET | `/api/devices` | `{ devices: [...] }` for current user |
| POST | `/api/devices` | `{ identifier, name }`; returns `{ device }` |
| POST | `/api/devices/:id/measurements` | `{ measurements: [...] }`; returns `{ inserted, duplicates }` |
| GET | `/api/activity/summary?from=...&to=...` | Total steps, average heart rate, sample count |
| GET | `/api/activity/history?from=...&to=...` | Daily totals grouped by UTC date |

All endpoints except health, registration, and login require a session. Device registration is idempotent per user and browser device identifier. Uploads to another user's device return 404. Registering a browser identifier records the association; it does not prove physical ownership of the hardware.

Supported profile fields: `firstName`, `lastName`, `phone`, `dateOfBirth` (`YYYY-MM-DD`), `location`, `heightCm` (30–300), `weightKg` (1–700), and integer `dailyStepGoal` (1–1,000,000). Email is the account identity and cannot be changed through the profile endpoint.

Activity ranges use ISO 8601 timestamps with timezone offsets, include `from`, and exclude `to`. Maximum range: 366 days. Defaults are UTC midnight today through now. To show a user's local day, send that day's local midnight boundaries with their offsets. History groups by **UTC**, so local-day charts will need additional timezone-aware grouping. Multiple device increments are summed; avoid uploading overlapping step counts from different devices.

## Browser upload flow

Use an API helper in the frontend, or try this example in the browser console at `http://localhost:8443` while the backend runs:

```javascript
const api = async (path, method = 'GET', body) => {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  return result;
};

await api('/auth/register', 'POST', {
  email: 'alex@example.com',
  password: 'replace-with-a-long-password',
});
// On subsequent visits use /auth/login with the same credentials.
const { device } = await api('/devices', 'POST', {
  identifier: 'your-bluetooth-device-id', // Use BluetoothDevice.id after pairing.
  name: 'STM32 activity tracker',
});
await api(`/devices/${device.id}/measurements`, 'POST', {
  measurements: [{
    sampleId: 'boot-unique-id:sequence-1',
    recordedAt: new Date().toISOString(),
    steps: 42,
    heartRate: 76,
    battery: 90,
  }],
});
console.log(await api('/activity/summary'));
```

For real Bluetooth integration:

1. Request the device from a user gesture with Web Bluetooth, using the STM32 firmware's service UUID.
2. Connect to its GATT service, subscribe to the measurement characteristic, and decode notifications according to the firmware protocol.
3. Register `BluetoothDevice.id` through `/api/devices`; retain the returned backend device ID.
4. Queue decoded samples locally, then upload batches of 1–500 samples. Only remove queued samples after a successful response. Retain the same sample IDs when retrying.

The firmware's BLE service UUID, characteristic UUID, payload layout, timestamp source, and counter semantics must be supplied before implementing the real Bluetooth reader. Use a browser that supports Web Bluetooth; production requires HTTPS, while localhost can be used for local development.

Measurement contract:

- `sampleId`: stable, nonempty ID up to 128 characters, unique per device, ideally firmware boot ID plus sequence number. Repeated IDs are ignored, even if their payload changes; retries must preserve the original payload.
- `recordedAt`: measurement time as ISO 8601 with timezone, normalized to UTC. At most five minutes in the future. Historical samples are accepted.
- `steps`: integer **increment since the previous sample**, 0–1,000,000. Do not upload a cumulative counter as an increment. Convert cumulative firmware counters into deltas, explicitly handling resets and reconnects.
- `heartRate`: optional number, 0–300, or null.
- `battery`: optional percentage, 0–100, or null.

Every batch is validated before insertion and inserted in a transaction. Invalid batches return 400 without inserting any samples. Request bodies are limited to 256 KiB. Repeated samples return success with a duplicate count, making retries safe.

## Tests

```powershell
cd backend
npm test
```

Tests use an isolated temporary SQLite file and exercise registration, login/logout, validation, profile persistence, restart persistence, device ownership, atomic batch validation, duplicate uploads, summaries, and history.

To check frontend types and test the full HTTP flow through the actual Vite development and preview proxies:

```powershell
cd frontend
npx.cmd --yes pnpm@10.34.3 typecheck
npx.cmd --yes pnpm@10.34.3 test
```

The frontend test builds the app and uses an in-memory backend on temporary ports; it does not modify your account database. It checks registration cookies, authenticated profile changes, device registration, measurement uploads, dashboard totals, and logout through both proxies. It is an HTTP integration test; browser interactions and physical Bluetooth hardware need separate manual verification.

## Deployment notes

This is a single-process backend suitable for local development and an initial small deployment. Before public deployment, serve both apps over HTTPS (preferably through the same origin), set `COOKIE_SECURE=true`, set the exact frontend origin, back up SQLite using a consistent SQLite backup procedure, and add password recovery/email verification as needed. The in-memory authentication limiter is per process and resets on restart; use a shared limiter when scaling. The API currently has no password recovery, account deletion, or device removal endpoints.

SQLite API reference: https://nodejs.org/docs/latest-v24.x/api/sqlite.html
