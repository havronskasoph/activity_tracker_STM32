import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { randomBytes, randomUUID, scrypt as scryptCallback, timingSafeEqual, createHash } from 'node:crypto';
import { promisify } from 'node:util';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const scrypt = promisify(scryptCallback);
const hash = value => createHash('sha256').update(value).digest('hex');
const fail = (status, message) => { throw Object.assign(new Error(message), { status }); };
const text = (value, name, max = 200) => {
  if (typeof value !== 'string' || !value.trim() || value.length > max) fail(400, `Invalid ${name}`);
  return value.trim();
};
const date = value => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) fail(400, 'Timestamp must be ISO 8601 with timezone');
  return new Date(value).toISOString();
};

export function createApp({ databasePath = process.env.DATABASE_PATH || './data/spokiy.sqlite', origin = process.env.FRONTEND_ORIGIN || 'http://localhost:8443', secure = process.env.COOKIE_SECURE === 'true' } = {}) {
  if (databasePath !== ':memory:') mkdirSync(dirname(resolve(databasePath)), { recursive: true });
  const db = new DatabaseSync(databasePath);
  db.exec(`PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY REFERENCES users(id),data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),identifier TEXT NOT NULL,name TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(user_id,identifier));
    CREATE TABLE IF NOT EXISTS measurements(device_id TEXT NOT NULL REFERENCES devices(id),sample_id TEXT NOT NULL,recorded_at TEXT NOT NULL,steps INTEGER NOT NULL,heart_rate REAL,battery REAL,PRIMARY KEY(device_id,sample_id));
    CREATE INDEX IF NOT EXISTS measurements_time ON measurements(device_id,recorded_at);`);
  const limits = new Map();
  const publicUser = user => ({ id: user.id, email: user.email, createdAt: user.created_at });
  const cookie = (token, age) => `spokiy_session=${token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${age}${secure ? '; Secure' : ''}`;
  const server = createServer(async (req, res) => {
    const send = (status, data) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    try {
      if (req.headers.origin && req.headers.origin !== origin) fail(403, 'Origin not allowed');
      if (req.headers.origin === origin) {
        res.setHeader('Access-Control-Allow-Origin', origin);
        res.setHeader('Access-Control-Allow-Credentials', 'true');
        res.setHeader('Vary', 'Origin');
      }
      if (req.method === 'OPTIONS') {
        res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PATCH,OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        res.writeHead(204); return res.end();
      }
      const url = new URL(req.url, 'http://localhost');
      const route = `${req.method} ${url.pathname}`;
      if (route === 'GET /api/health') return send(200, { status: 'ok' });
      let body = {};
      if (['POST', 'PATCH'].includes(req.method)) {
        if (!req.headers['content-type']?.startsWith('application/json')) fail(415, 'Use application/json');
        const chunks = []; let size = 0;
        for await (const chunk of req) { size += chunk.length; if (size > 262144) fail(413, 'Request too large'); chunks.push(chunk); }
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail(400, 'Invalid JSON'); }
        if (!body || Array.isArray(body) || typeof body !== 'object') fail(400, 'Expected JSON object');
      }
      if (['POST /api/auth/register', 'POST /api/auth/login'].includes(route)) {
        const now = Date.now();
        for (const [key, value] of limits) if (value.until < now) limits.delete(key);
        const key = req.socket.remoteAddress;
        const limit = limits.get(key) || { count: 0, until: now + 60000 };
        limits.set(key, limit);
        if (++limit.count > 20) fail(429, 'Too many attempts; retry after one minute');
        const email = text(body.email, 'email', 254).toLowerCase();
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) fail(400, 'Invalid email');
        if (typeof body.password !== 'string' || body.password.length < 12 || body.password.length > 128) fail(400, 'Password must contain 12–128 characters');
        let user = db.prepare('SELECT * FROM users WHERE email=?').get(email);
        if (route.endsWith('/register')) {
          if (user) fail(409, 'Email already registered');
          const salt = randomBytes(16).toString('hex');
          const digest = (await scrypt(body.password, salt, 64)).toString('hex');
          user = { id: randomUUID(), email, password: `${salt}:${digest}`, created_at: new Date().toISOString() };
          db.exec('BEGIN');
          try {
            db.prepare('INSERT INTO users VALUES(?,?,?,?)').run(user.id, email, user.password, user.created_at);
            db.prepare('INSERT INTO profiles VALUES(?,?)').run(user.id, JSON.stringify({ firstName: '', lastName: '', dailyStepGoal: 10000 }));
            db.exec('COMMIT');
          } catch (error) { db.exec('ROLLBACK'); if (String(error.message).includes('UNIQUE')) fail(409, 'Email already registered'); throw error; }
        } else {
          const [salt, digest] = (user?.password || `${'0'.repeat(32)}:${'0'.repeat(128)}`).split(':');
          const actual = await scrypt(body.password, salt, 64);
          if (!timingSafeEqual(actual, Buffer.from(digest, 'hex')) || !user) fail(401, 'Invalid email or password');
        }
        db.prepare('DELETE FROM sessions WHERE expires<=?').run(Date.now());
        const token = randomBytes(32).toString('hex');
        db.prepare('INSERT INTO sessions VALUES(?,?,?)').run(hash(token), user.id, Date.now() + 7 * 86400000);
        res.setHeader('Set-Cookie', cookie(token, 7 * 86400));
        return send(route.endsWith('/register') ? 201 : 200, { user: publicUser(user) });
      }
      const token = req.headers.cookie?.split(';').map(x => x.trim()).find(x => x.startsWith('spokiy_session='))?.slice(15) || '';
      const user = db.prepare('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?').get(hash(token), Date.now());
      if (!user) fail(401, 'Sign in required');
      if (route === 'GET /api/auth/me') return send(200, { user: publicUser(user) });
      if (route === 'POST /api/auth/logout') {
        db.prepare('DELETE FROM sessions WHERE token=?').run(hash(token));
        res.setHeader('Set-Cookie', cookie('', 0)); return send(200, { ok: true });
      }
      if (route === 'GET /api/profile' || route === 'PATCH /api/profile') {
        const profile = JSON.parse(db.prepare('SELECT data FROM profiles WHERE user_id=?').get(user.id).data);
        if (req.method === 'PATCH') {
          const strings = ['firstName', 'lastName', 'phone', 'dateOfBirth', 'location'];
          const numbers = { heightCm: [30, 300], weightKg: [1, 700], dailyStepGoal: [1, 1000000] };
          for (const [key, value] of Object.entries(body)) {
            if (strings.includes(key)) {
              if (typeof value !== 'string' || value.length > 200) fail(400, `Invalid ${key}`);
              if (key === 'dateOfBirth' && value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value || value > new Date().toISOString().slice(0, 10))) fail(400, 'Invalid dateOfBirth');
            } else if (Object.hasOwn(numbers, key)) {
              const [min, max] = numbers[key];
              if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max || (key === 'dailyStepGoal' && !Number.isInteger(value))) fail(400, `Invalid ${key}`);
            } else fail(400, `Unknown profile field: ${key}`);
            profile[key] = value;
          }
          db.prepare('UPDATE profiles SET data=? WHERE user_id=?').run(JSON.stringify(profile), user.id);
        }
        return send(200, { profile, email: user.email });
      }
      if (route === 'GET /api/devices') return send(200, { devices: db.prepare('SELECT id,identifier,name,created_at FROM devices WHERE user_id=?').all(user.id) });
      if (route === 'POST /api/devices') {
        const identifier = text(body.identifier, 'identifier'); const name = text(body.name, 'name');
        const existing = db.prepare('SELECT * FROM devices WHERE user_id=? AND identifier=?').get(user.id, identifier);
        if (existing) return send(200, { device: existing });
        const device = { id: randomUUID(), identifier, name, created_at: new Date().toISOString() };
        db.prepare('INSERT INTO devices VALUES(?,?,?,?,?)').run(device.id, user.id, identifier, name, device.created_at);
        return send(201, { device });
      }
      const upload = url.pathname.match(/^\/api\/devices\/([^/]+)\/measurements$/);
      if (req.method === 'POST' && upload) {
        if (!db.prepare('SELECT id FROM devices WHERE id=? AND user_id=?').get(upload[1], user.id)) fail(404, 'Device not found');
        if (!Array.isArray(body.measurements) || !body.measurements.length || body.measurements.length > 500) fail(400, 'Provide 1–500 measurements');
        const rows = body.measurements.map(m => {
          if (!m || typeof m !== 'object') fail(400, 'Invalid measurement');
          const id = text(m.sampleId, 'sampleId', 128); const timestamp = date(m.recordedAt);
          if (Date.parse(timestamp) > Date.now() + 300000) fail(400, 'Measurement is in the future');
          if (!Number.isInteger(m.steps) || m.steps < 0 || m.steps > 1000000) fail(400, 'Invalid step increment');
          for (const [key, max] of [['heartRate', 300], ['battery', 100]]) if (m[key] != null && (typeof m[key] !== 'number' || !Number.isFinite(m[key]) || m[key] < 0 || m[key] > max)) fail(400, `Invalid ${key}`);
          return [upload[1], id, timestamp, m.steps, m.heartRate ?? null, m.battery ?? null];
        });
        let inserted = 0;
        db.exec('BEGIN');
        try {
          const statement = db.prepare('INSERT INTO measurements VALUES(?,?,?,?,?,?) ON CONFLICT(device_id,sample_id) DO NOTHING');
          for (const row of rows) inserted += Number(statement.run(...row).changes);
          db.exec('COMMIT');
        } catch (error) { db.exec('ROLLBACK'); throw error; }
        return send(200, { inserted, duplicates: rows.length - inserted });
      }
      if (route === 'GET /api/activity/summary' || route === 'GET /api/activity/history') {
        const from = date(url.searchParams.get('from') || `${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
        const to = date(url.searchParams.get('to') || new Date().toISOString());
        if (from >= to || Date.parse(to) - Date.parse(from) > 366 * 86400000) fail(400, 'Use a time range greater than zero and at most 366 days');
        const args = [user.id, from, to];
        if (route.endsWith('/summary')) return send(200, { from, to, ...db.prepare('SELECT COALESCE(SUM(m.steps),0) AS steps, AVG(m.heart_rate) AS averageHeartRate, COUNT(*) AS samples FROM measurements m JOIN devices d ON d.id=m.device_id WHERE d.user_id=? AND m.recorded_at>=? AND m.recorded_at<?').get(...args) });
        return send(200, { from, to, days: db.prepare("SELECT substr(m.recorded_at,1,10) AS date,SUM(m.steps) AS steps,AVG(m.heart_rate) AS averageHeartRate FROM measurements m JOIN devices d ON d.id=m.device_id WHERE d.user_id=? AND m.recorded_at>=? AND m.recorded_at<? GROUP BY date ORDER BY date").all(...args) });
      }
      fail(404, 'Endpoint not found');
    } catch (error) {
      if (!error.status) console.error(error);
      if (!res.headersSent) send(error.status || 500, { error: error.status ? error.message : 'Internal server error' });
    }
  });
  server.on('close', () => db.close());
  server.requestTimeout = 15000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const app = createApp();
  app.listen(Number(process.env.PORT || 3001), process.env.HOST || '127.0.0.1', () => console.log(`Spokiy API listening on http://${process.env.HOST || '127.0.0.1'}:${process.env.PORT || 3001}`));
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => app.close());
}
