# Spokiy

React/Vite frontend and a Python FastAPI backend for activity measurements read from an STM32 Bluetooth device by the browser.

## Requirements

- Python **3.10 or later** for the FastAPI backend.
- Node.js **24 or later** for the frontend.
- pnpm **10.34.3** for the frontend.
- Two terminals, starting in `spokiy_app/`.

## Run the backend

In PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn server:create_app --factory --host 127.0.0.1 --port 3001 --env-file .env --reload
```

Copy `.env.example` only for initial setup; preserve your configuration on subsequent runs. If PowerShell blocks activation, run `.venv\Scripts\python.exe` directly instead.

The API listens at **http://127.0.0.1:3001**. Open http://127.0.0.1:3001/api/health to check it. For normal operation without file watching, omit `--reload`. Uvicorn command-line options determine the host and port. Stop with Ctrl+C.

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

The tracker firmware creates a custom service on ST's `BLE_AT_Server`. The website defaults to these UUIDs:

- Service: `0000aabb-cc7a-482a-984a-7f2ed5b3e58f`
- Notification characteristic: `00003344-8e22-4541-9d4c-21edae82ed19`

Build and flash the main STM32 firmware with `HAR_BLE_ENABLED` set to `1` in `Core/Inc/har_ble.h` (the default). The STM32WB5MMG module must already have a compatible ST BLE stack and `BLE_AT_Server` installed; see the repository's [BLE setup guide](../firmware/BLE_SETUP.md). Power-cycle the board after flashing, then use **Connect device** and choose `Spokiy` if it appears. Chrome or Edge on a Bluetooth-capable Windows computer and localhost or HTTPS are required; iPhone browsers do not support this Web Bluetooth flow. Close the phone's BLE connection first if the board cannot accept another connection.

Check the service with a BLE scanner and test notifications on the board. The implementation is unverified on hardware. The latest prediction is saved for explicitly authorized administrators; predictions are not uploaded as steps. They are sent as newline-terminated UTF-8 text split into notifications of at most 18 bytes; the browser reassembles them.

To override the UUIDs for a compatible server, set `VITE_BLE_SERVICE_UUID` and `VITE_BLE_CHARACTERISTIC_UUID` in the frontend environment before starting Vite. Both must match the running firmware.

## Administrator monitoring

During registration choose a regular user or administrator account. Administrators cannot access other accounts automatically. A regular user can share their latest activity with an administrator by entering their registered email on the dashboard, and can revoke access there at any time. Administrators see authorized users and their most recently received activity; the dashboard polls the server every three seconds and shows an in-app notice when an observed activity changes. An old timestamp means the status may no longer be current. Activity is sent only while the user's browser is connected to the tracker and backend.

The model does not classify falls, so the app does not generate sudden-drop or fall alerts. It is not a safety monitoring or emergency notification system. An administrator account does not grant access to private measurements or profiles.

## API

Requests and responses use JSON. Errors return `{ "error": "message" }`. For POST/PATCH requests, send `Content-Type: application/json`, including `{}` for logout. Registration and login set an HttpOnly session cookie valid for seven days; subsequent browser calls must use `credentials: 'include'`. Passwords must contain 12–128 characters and are stored as salted scrypt hashes. Authentication attempts are limited to 20 per minute per connection IP.

| Method | Endpoint | Body / result |
| --- | --- | --- |
| GET | `/api/health` | Public health check |
| POST | `/api/auth/register` | `{ email, password, role }`; role is `user` or `admin` |
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

Hardware notification behavior must be verified before using the Bluetooth reader; timestamp and counter semantics must be established before uploading measurements. Use a browser that supports Web Bluetooth; production requires HTTPS, while localhost can be used for local development.

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
python -m unittest discover -s test -p "test_*.py"
```

Tests use an isolated temporary SQLite file and exercise registration, login/logout, validation, profile persistence, restart persistence, device ownership, atomic batch validation, duplicate uploads, summaries, and history.

To check frontend types and test the full HTTP flow through the actual Vite development and preview proxies:

```powershell
cd frontend
npx.cmd --yes pnpm@10.34.3 typecheck
npx.cmd --yes pnpm@10.34.3 test
```

The frontend test builds the app and starts a temporary FastAPI backend; set `SPOKIY_PYTHON` to the backend virtual environment?s Python executable if needed; it does not modify your account database. It checks registration cookies, authenticated profile changes, device registration, measurement uploads, dashboard totals, and logout through both proxies. It is an HTTP integration test; browser interactions and physical Bluetooth hardware need separate manual verification.

## Deployment notes

This is a single-process backend suitable for local development and an initial small deployment. Before public deployment, serve both apps over HTTPS (preferably through the same origin), set `COOKIE_SECURE=true`, set the exact frontend origin, back up SQLite using a consistent SQLite backup procedure, and add password recovery/email verification as needed. The in-memory authentication limiter is per process and resets on restart; use a shared limiter when scaling. The API currently has no password recovery, account deletion, or device removal endpoints.

FastAPI documentation: https://fastapi.tiangolo.com/
