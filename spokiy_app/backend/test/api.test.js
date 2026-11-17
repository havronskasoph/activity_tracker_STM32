import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../src/server.js';

test('accounts, persistence, ownership, atomic uploads, retries and summaries', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'spokiy-test-'));
  const databasePath = join(directory, 'test.sqlite');
  let server;
  let base;
  async function start() {
    server = createApp({ databasePath });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    base = `http://127.0.0.1:${server.address().port}`;
  }
  async function stop() { await new Promise(resolve => server.close(resolve)); }
  async function request(path, { method = 'GET', body, cookie, origin } = {}) {
    const response = await fetch(base + '/api' + path, {
      method,
      headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(cookie ? { Cookie: cookie } : {}), ...(origin ? { Origin: origin } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, data: await response.json(), cookie: response.headers.get('set-cookie')?.split(';')[0] };
  }
  try {
    await start();
    assert.equal((await request('/health')).status, 200);
    assert.equal((await request('/profile')).status, 401);
    assert.equal((await request('/health', { origin: 'https://evil.example' })).status, 403);
    const account = { email: 'alex@example.com', password: 'a-secure-password' };
    const registered = await request('/auth/register', { method: 'POST', body: account });
    assert.equal(registered.status, 201);
    assert.equal(registered.data.user.password, undefined);
    const cookie = registered.cookie;
    assert.equal((await request('/auth/register', { method: 'POST', body: account })).status, 409);
    assert.equal((await request('/auth/login', { method: 'POST', body: { ...account, password: 'wrong-password' } })).status, 401);
    assert.equal((await request('/auth/login', { method: 'POST', body: account })).status, 200);
    assert.equal((await request('/profile', { method: 'PATCH', cookie, body: { firstName: 'Alex', dailyStepGoal: 8000 } })).status, 200);
    assert.equal((await request('/profile', { method: 'PATCH', cookie, body: { dateOfBirth: '2020-02-31' } })).status, 400);
    assert.equal((await request('/profile', { method: 'PATCH', cookie, body: { constructor: 2 } })).status, 400);
    const body = { identifier: 'browser-bluetooth-id', name: 'STM32' };
    const device = (await request('/devices', { method: 'POST', cookie, body })).data.device;
    assert.equal((await request('/devices', { method: 'POST', cookie, body })).data.device.id, device.id);
    const second = await request('/auth/register', { method: 'POST', body: { email: 'other@example.com', password: account.password } });
    const endpoint = `/devices/${device.id}/measurements`;
    const sample = { sampleId: 'boot-1:1', recordedAt: '2026-01-01T12:00:00Z', steps: 50, heartRate: 75, battery: 90 };
    assert.equal((await request(endpoint, { method: 'POST', cookie: second.cookie, body: { measurements: [sample] } })).status, 404);
    assert.equal((await request(endpoint, { method: 'POST', cookie, body: { measurements: [sample, { ...sample, sampleId: 'bad', steps: -1 }] } })).status, 400);
    const upload = await request(endpoint, { method: 'POST', cookie, body: { measurements: [sample] } });
    assert.deepEqual(upload.data, { inserted: 1, duplicates: 0 });
    assert.deepEqual((await request(endpoint, { method: 'POST', cookie, body: { measurements: [sample] } })).data, { inserted: 0, duplicates: 1 });
    const range = '?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z';
    assert.equal((await request('/activity/summary' + range, { cookie })).data.steps, 50);
    assert.equal((await request('/activity/summary' + range, { cookie: second.cookie })).data.steps, 0);
    assert.deepEqual((await request('/activity/history' + range, { cookie })).data.days, [{ date: '2026-01-01', steps: 50, averageHeartRate: 75 }]);
    await stop(); await start();
    assert.equal((await request('/profile', { cookie })).data.profile.firstName, 'Alex');
    assert.equal((await request('/activity/summary' + range, { cookie })).data.steps, 50);
    assert.equal((await request('/auth/logout', { method: 'POST', cookie, body: {} })).status, 200);
    assert.equal((await request('/auth/me', { cookie })).status, 401);
  } finally {
    if (server?.listening) await stop();
    rmSync(directory, { recursive: true, force: true });
  }
});
