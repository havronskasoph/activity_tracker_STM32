import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { createServer as netServer } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer, preview } from "vite";

// Exercise the real Vite config: cookies and /api requests must work through
// the same frontend origin in development and production preview.
test("frontend dev and preview proxy authenticated API requests", async () => {
  const socket = netServer();
  socket.listen(0, "127.0.0.1");
  await once(socket, "listening");
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const directory = await mkdtemp(join(tmpdir(), "spokiy-proxy-"));
  const backend = spawn(process.env.SPOKIY_PYTHON || "python", ["-m", "uvicorn", "server:create_app", "--factory", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: fileURLToPath(new URL("../../backend/", import.meta.url)),
    env: { ...process.env, DATABASE_PATH: join(directory, "test.sqlite") }, stdio: "ignore"
  });
  const oldTarget = process.env.API_PROXY_TARGET;
  process.env.API_PROXY_TARGET = `http://127.0.0.1:${port}`;
  let ready = false;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${process.env.API_PROXY_TARGET}/api/health`)).ok) { ready = true; break; } } catch {}
    if (backend.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ready) { backend.kill(); await rm(directory, {recursive: true, force: true}); throw new Error("FastAPI backend did not start; install backend requirements and set SPOKIY_PYTHON if needed"); }
  const root = fileURLToPath(new URL("../", import.meta.url));
  let dev;
  let built;
  try {
    dev = await createServer({ root, server: { host: "127.0.0.1", port: 0 } });
    await dev.listen();
    built = await preview({ root, preview: { host: "127.0.0.1", port: 0 } });
    for (const [index, server] of [dev.httpServer, built.httpServer].entries()) {
      const base = `http://127.0.0.1:${server.address().port}`;
      const request = (path, method = "GET", body, cookie) =>
        fetch(base + "/api" + path, {
          method,
          headers: {
            Origin: "http://localhost:8443",
            ...(body ? { "Content-Type": "application/json" } : {}),
            ...(cookie ? { Cookie: cookie } : {}),
          },
          body: body ? JSON.stringify(body) : undefined,
        });
      assert.equal((await request("/health")).status, 200);
      const registration = await request("/auth/register", "POST", {
        email: `proxy${index}@example.com`,
        password: "a-long-test-password",
      });
      assert.equal(registration.status, 201);
      const cookie = registration.headers.get("set-cookie").split(";")[0];
      assert.match(registration.headers.get("set-cookie"), /HttpOnly/);
      assert.equal((await request("/auth/me", "GET", undefined, cookie)).status, 200);
      const save = await request(
        "/profile",
        "PATCH",
        { firstName: "Proxy", dailyStepGoal: 9000 },
        cookie,
      );
      assert.equal(save.status, 200);
      const profile = await (await request("/profile", "GET", undefined, cookie)).json();
      assert.equal(profile.profile.firstName, "Proxy");
      assert.equal(profile.profile.dailyStepGoal, 9000);
      const device = await (
        await request("/devices", "POST", { identifier: "stm32", name: "Tracker" }, cookie)
      ).json();
      const now = new Date();
      const from = new Date(now);
      from.setHours(0, 0, 0, 0);
      const upload = await request(
        `/devices/${device.device.id}/measurements`,
        "POST",
        { measurements: [{ sampleId: "boot:1", recordedAt: now.toISOString(), steps: 42 }] },
        cookie,
      );
      assert.equal(upload.status, 200);
      const range = `?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(new Date(Date.now() + 1000).toISOString())}`;
      const summary = await (
        await request("/activity/summary" + range, "GET", undefined, cookie)
      ).json();
      assert.equal(summary.steps, 42);
      assert.equal((await request("/auth/logout", "POST", {}, cookie)).status, 200);
      assert.equal((await request("/auth/me", "GET", undefined, cookie)).status, 401);
    }
  } finally {
    if (dev) await dev.close();
    if (built) await new Promise((resolve) => built.httpServer.close(resolve));
    if (backend.exitCode === null) { backend.kill(); await once(backend, "exit"); }
    await rm(directory, { recursive: true, force: true });
    if (oldTarget === undefined) delete process.env.API_PROXY_TARGET;
    else process.env.API_PROXY_TARGET = oldTarget;
  }
});
